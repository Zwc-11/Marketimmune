"""Rebuild a coin's December 2025 book from the Albers L4 archives -> Silver L2 and order events.

    python -m marketimmune.cli.build_albers_silver --coin SOL --dates 20251201..20251231

Writes, per UTC date, ``silver/hyperliquid/l2_book/<COIN>/<COIN>-<date>.parquet`` (one row
per block whose top five levels changed) with a ``.validation.json`` beside it, and
``silver/hyperliquid/order_events/<COIN>/<COIN>-<date>.parquet`` (forced-liquidation fills
and unfilled IOCs, see :meth:`AlbersBook.replay_hour`).

Order statuses are a sequential ``.tar.xz``, so a run always decompresses from Dec 1 up
to its last date; a thread decodes the next hour while this one replays (lzma and isal
release the GIL). Book diffs are an uncompressed tar read by offset. The book starts
empty, so rows from the first ``--warmup-minutes`` of a run, and of the book rebuilt
after each data gap, are dropped. Statuses the archive repeats after jumping back in time
are dropped first (:func:`drop_replayed`). Each hourly diff member holds every coin (about 1.6 GB
of JSON) and parsing it takes about twice as long as replaying the hour, so ``--diff-workers``
processes parse the next hours' diffs while this one replays.
"""

from __future__ import annotations

import argparse
import io
import json
import tarfile
import time
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.logger import init_logger
from marketimmune.sources.albers_l4 import (
    EVENT_SCHEMA,
    L2_SCHEMA,
    SOURCE,
    AlbersBook,
    ReplayStats,
    Rested,
    drop_replayed,
    gunzip,
    l2_table,
    merge_rested,
    read_status_records,
    read_users_csv,
    rested_orders_gz,
)
from marketimmune.utils import parse_date_spec, prefetch, shift_date

logger = init_logger(__name__)

_EMPTY: Rested = (np.zeros(0, dtype=np.uint64), np.zeros(0))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201", help="YYYYMMDD, lists or a..b ranges")
    parser.add_argument("--hours", default="0-23", help="e.g. 0-23 or 0-1 (for a probe)")
    parser.add_argument("--albers-dir", type=Path, default=Path("data/bronze/albers"))
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--warmup-minutes", type=float, default=10.0)
    parser.add_argument(
        "--gap-seconds", type=float, default=30.0, help="a jump between blocks longer than this resets the book and restarts warm-up"
    )
    parser.add_argument("--diff-workers", type=int, default=4, help="processes parsing book diffs ahead of the replay")
    return parser.parse_args(argv)


def parse_hours(spec: str) -> list[int]:
    hours: list[int] = []
    for token in spec.split(","):
        a, _, b = token.strip().partition("-")
        hours.extend(range(int(a), int(b or a) + 1))
    assert hours and min(hours) >= 0 and max(hours) <= 23, f"hours must be within 0-23: {spec=}"
    return sorted(set(hours))


def next_hour(date: str, hour: int) -> tuple[str, int]:
    return (shift_date(date, 1), 0) if hour == 23 else (date, hour + 1)


def diff_member(date: str, hour: int) -> str:
    return f"{date}/ex{hour}.gz"


def iter_status_members(path: Path, wanted: set[str]) -> Iterator[tuple[str, bytes]]:
    """Yield ``(member name, decompressed bytes)`` for wanted members, in archive order."""
    last = ""
    with tarfile.open(path, mode="r|xz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            assert member.name >= last, f"{path.name} is not in name order at {member.name}"
            last = member.name
            if member.name in wanted:
                handle = tf.extractfile(member)
                assert handle is not None
                yield member.name, gunzip(handle.read())
                wanted.discard(member.name)
                if not wanted:
                    return


def parse_diff_member(tar_path: str, offset: int, size: int, coin: str) -> Rested:
    """``coin``'s ``new`` diffs in the member stored at ``offset``. Module-level so a
    worker process can run it; the arrays pickle as one buffer each."""
    with open(tar_path, "rb") as fh:
        fh.seek(offset)
        return rested_orders_gz(fh.read(size), coin)


class DiffReader:
    """Each hour's diffs from ``book_diffs_202512.tar``, parsed ahead of use.

    ``names`` is every member the run will ask for, in order; up to ``workers + 2``
    of them are queued on the worker processes while earlier hours replay. A
    member the archive lacks has no diffs.
    """

    def __init__(self, tar_path: Path, coin: str, names: list[str], workers: int) -> None:
        assert workers >= 1, f"{workers=}"
        with tarfile.open(tar_path, mode="r:") as tar:
            spans = {m.name: (m.offset_data, m.size) for m in tar.getmembers()}
        self._todo = deque((name, spans.get(name)) for name in dict.fromkeys(names))
        self._args = (str(tar_path), coin)
        self._ahead: deque[tuple[str, Future[Rested] | None]] = deque()
        self._depth = workers + 2
        self.pool = ProcessPoolExecutor(workers, mp_context=get_context("spawn"))

    def get(self, name: str) -> Rested:
        """Diffs of member ``name``; members queued before it that nobody asked for are dropped."""
        while True:
            while self._todo and len(self._ahead) < self._depth:
                nxt, span = self._todo.popleft()
                path, coin = self._args
                self._ahead.append((nxt, None if span is None else self.pool.submit(parse_diff_member, path, *span, coin)))
            assert self._ahead, f"{name} was not planned"
            got, future = self._ahead.popleft()
            if got == name:
                return _EMPTY if future is None else future.result()
            if future is not None:
                future.cancel()


def split_at_gaps(records: npt.NDArray[np.void], last_ts: int | None, gap_ns: int) -> list[tuple[npt.NDArray[np.void], int | None]]:
    """Cut an hour of statuses where consecutive blocks are more than ``gap_ns`` apart
    (including the jump from the previous hour). Each piece comes with the time the
    gap before it started, or None when no gap precedes it."""
    if records.size == 0:
        return [(records, None)]
    ts = records["ts"].astype(np.int64)
    cuts = (np.flatnonzero(np.diff(ts) > gap_ns) + 1).tolist()
    befores = [last_ts if last_ts is not None and int(ts[0]) - last_ts > gap_ns else None, *(int(ts[a - 1]) for a in cuts)]
    return [(records[a:b], before) for a, b, before in zip([0, *cuts], [*cuts, ts.size], befores, strict=True)]


def load_users(albers_dir: Path) -> dict[int, str]:
    with tarfile.open(albers_dir / "mapdir.tar.xz", mode="r:xz") as tf:
        handle = tf.extractfile("mapdir/users.csv")
        assert handle is not None
        return read_users_csv(io.TextIOWrapper(handle, encoding="utf-8"))


def build(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    dates = parse_date_spec(args.dates)
    plan = [(d, h) for d in dates for h in parse_hours(args.hours)]
    layout = HyperliquidLakeLayout(args.lake_root)
    wanted = {f"{d}/{coin.lower()}_{h:02d}.data.gz": (d, h) for d, h in plan}
    names = [name for d, h in plan for name in (diff_member(d, h), diff_member(*next_hour(d, h)))]
    diffs = DiffReader(args.albers_dir / "book_diffs_202512.tar", coin, names, args.diff_workers)
    book = AlbersBook(coin, load_users(args.albers_dir))
    warmup_ns, gap_ns = int(args.warmup_minutes * 60e9), int(args.gap_seconds * 1e9)
    last_ts: int | None = None
    warm_from = 0  # rows before this time are dropped (start of run, or after a gap)
    held: tuple[str, Rested] | None = None  # the next hour's diffs, read for the previous hour
    gaps: dict[str, list[dict[str, Any]]] = {d: [] for d in dates}
    report: dict[str, list[dict[str, Any]]] = {d: [] for d in dates}
    writers: dict[str, pq.ParquetWriter] = {}
    event_writers: dict[str, pq.ParquetWriter] = {}
    t0 = time.perf_counter()
    try:
        for name, raw in prefetch(iter_status_members(args.albers_dir / f"{coin.lower()}_orders_202512.tar.xz", set(wanted))):
            date, hour = wanted[name]
            raw_records = read_status_records(raw)
            records = drop_replayed(raw_records, last_ts)
            this_name, next_name = diff_member(date, hour), diff_member(*next_hour(date, hour))
            this = held[1] if held is not None and held[0] == this_name else diffs.get(this_name)
            held = (next_name, diffs.get(next_name))
            rested = merge_rested(this, held[1])
            if last_ts is None and records.size:
                warm_from = int(records["ts"][0]) + warmup_ns
            stats = ReplayStats(replayed_dropped=raw_records.size - records.size)
            rows: list[list[Any]] = []
            event_parts: list[pa.Table] = []
            for segment, gap_start in split_at_gaps(records, last_ts, gap_ns):
                if gap_start is not None:
                    book.reset()
                    gap_end = int(segment["ts"][0])
                    warm_from = gap_end + warmup_ns
                    gaps[date].append({"from_ns": gap_start, "to_ns": gap_end, "seconds": round((gap_end - gap_start) / 1e9, 1)})
                part, events = book.replay_hour(segment, rested, stats)
                rows += [r for r in part if r[-1] >= warm_from]  # ts_ns is the last column
                event_parts.append(events)
            if records.size:
                last_ts = int(records["ts"][-1])
            if date not in event_writers:  # every replayed date gets an events file
                path = layout.silver_order_events_path(coin, date)
                path.parent.mkdir(parents=True, exist_ok=True)
                event_writers[date] = pq.ParquetWriter(path, EVENT_SCHEMA, compression="zstd")
            events = pa.concat_tables(event_parts)
            if events.num_rows:
                event_writers[date].write_table(events)
            if rows:
                if date not in writers:
                    path = layout.silver_l2_book_path(coin, date)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    writers[date] = pq.ParquetWriter(path, L2_SCHEMA, compression="zstd")
                writers[date].write_table(l2_table(rows))
            entry = {"hour": hour, **stats.to_dict(), "rows_written": len(rows)}
            report[date].append(entry)
            logger.info(
                f"{name}: {stats.records:,} statuses, {stats.blocks:,} blocks, {len(rows):,} rows, crossed={stats.crossed_blocks}, "
                f"fills at touch={entry['fill_at_touch_share']}, {time.perf_counter() - t0:.0f}s"
            )
    finally:
        diffs.pool.shutdown(cancel_futures=True)
        for writer in (*writers.values(), *event_writers.values()):
            writer.close()
    for date, hours in report.items():
        if not hours:
            continue
        path = layout.silver_l2_book_path(coin, date).with_suffix(".validation.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "coin": coin,
            "date": date,
            "source": SOURCE,
            "warmup_minutes": args.warmup_minutes,
            "gap_seconds": args.gap_seconds,
            "gaps": gaps[date],
            "hours": hours,
        }
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"dates": list(writers), "elapsed_s": round(time.perf_counter() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(build(parse_args(argv)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
