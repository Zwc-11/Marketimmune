"""Rebuild a coin's December 2025 book from the Albers L4 archives -> Silver L2.

Reads the archives from data/bronze/albers (``make download-albers``; nothing is extracted
to disk) and writes, per UTC date:

* ``silver/hyperliquid/l2_book/<COIN>/<COIN>-<date>.parquet``: one row per block
  whose top five levels changed (archive-snapshot Silver L2 columns plus ``ts_ns``),
  and ``<same>.validation.json``;
* ``silver/hyperliquid/order_events/<COIN>/<COIN>-<date>.parquet``: forced-liquidation
  fills and unfilled IOCs, with the wallet address and whether the IOC was
  marketable at the start of its block.

    python -m marketimmune.cli.build_albers_silver --coin SOL --dates 20251201..20251231

Order statuses are a sequential ``.tar.xz``, so a run always decompresses from
Dec 1 up to its last date; book diffs are an uncompressed tar read by seek. The
book starts empty, so rows from the first ``--warmup-minutes`` of a run are
dropped (orders resting from before the run never appear).

Each hourly diff member holds every coin (about 1.6 GB of JSON), and parsing it
costs about as much as replaying the hour. ``--diff-workers`` processes parse the
next hours' diffs while this one replays (default 1; 0 parses in-process).
"""

from __future__ import annotations

import argparse
import io
import json
import tarfile
import time
from collections.abc import Iterator
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.lake.tables import L2_DEPTH, HyperliquidLakeLayout
from marketimmune.sources.albers_l4 import (
    AlbersBook,
    ReplayStats,
    gunzip,
    read_status_records,
    read_users_csv,
    rested_orders_gz,
)

SOURCE = "albers-l4 doi:10.5281/zenodo.18184441"
_INT_COLUMNS = {"ts_ms", "ts_ns", "bid_n", "ask_n"} | {
    f"{side}_n_{i}" for side in ("bid", "ask") for i in range(1, L2_DEPTH + 1)
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201", help="YYYYMMDD, lists or a..b ranges")
    parser.add_argument("--hours", default="0-23", help="e.g. 0-23 or 0-1 (for a probe)")
    parser.add_argument(
        "--albers-dir",
        type=Path,
        default=Path("data/bronze/albers"),
    )
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--warmup-minutes", type=float, default=10.0)
    parser.add_argument(
        "--diff-workers", type=int, default=1, help="processes parsing book diffs ahead (0: none)"
    )
    return parser.parse_args(argv)


def parse_hours(spec: str) -> list[int]:
    hours: list[int] = []
    for token in spec.split(","):
        a, _, b = token.strip().partition("-")
        hours.extend(range(int(a), int(b or a) + 1))
    if not hours or min(hours) < 0 or max(hours) > 23:
        raise ValueError(f"hours must be within 0-23: {spec!r}")
    return sorted(set(hours))


def iter_status_members(path: Path, coin: str, wanted: set[str]) -> Iterator[tuple[str, bytes]]:
    """Yield ``(member name, decompressed bytes)`` for wanted members, in archive order."""
    last = ""
    with tarfile.open(path, mode="r|xz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            if member.name < last:
                raise ValueError(f"{path.name} is not in name order at {member.name}")
            last = member.name
            if member.name in wanted:
                handle = tf.extractfile(member)
                assert handle is not None
                yield member.name, gunzip(handle.read())
                wanted.discard(member.name)
                if not wanted:
                    return


RestedArrays = tuple[npt.NDArray[np.uint64], npt.NDArray[np.float64]]
_PREFETCH_HOURS = 3


def parse_diff_member(tar_path: str, name: str, coin: str) -> RestedArrays:
    """``(oids, sizes)`` of ``coin``'s ``new`` diffs in one hourly member; empty if absent.

    Module-level so a worker process can run it; arrays pickle as one buffer each.
    """
    with tarfile.open(tar_path, mode="r:") as tar:
        try:
            member = tar.getmember(name)
        except KeyError:
            return np.zeros(0, dtype=np.uint64), np.zeros(0, dtype=np.float64)
        handle = tar.extractfile(member)
        assert handle is not None
        rested = rested_orders_gz(handle.read(), coin)
    oids = np.fromiter(rested.keys(), dtype=np.uint64, count=len(rested))
    sizes = np.fromiter(rested.values(), dtype=np.float64, count=len(rested))
    return oids, sizes


class DiffReader:
    """``rested`` sets per hour from ``book_diffs_202512.tar``, parsed ahead of use.

    ``names`` is every member the run will ask for, in order; up to
    ``_PREFETCH_HOURS`` of them are parsed by ``executor`` while earlier hours replay.
    """

    def __init__(
        self, tar_path: Path, coin: str, names: list[str], executor: Executor | None = None
    ) -> None:
        self.tar_path = str(tar_path)
        self.coin = coin
        self.executor = executor
        self._todo = list(dict.fromkeys(names))
        self._pending: dict[str, Future[RestedArrays]] = {}
        self._cache: dict[str, dict[int, float]] = {}

    def _load(self, name: str) -> RestedArrays:
        if self.executor is None:
            return parse_diff_member(self.tar_path, name, self.coin)
        while self._todo and len(self._pending) < _PREFETCH_HOURS:
            nxt = self._todo.pop(0)
            if nxt not in self._cache and nxt not in self._pending:
                self._pending[nxt] = self.executor.submit(
                    parse_diff_member, self.tar_path, nxt, self.coin
                )
        future = self._pending.pop(name, None)
        if future is None:
            return parse_diff_member(self.tar_path, name, self.coin)
        return future.result()

    def rested(self, date: str, hour: int) -> dict[int, float]:
        name = f"{date}/ex{hour}.gz"
        if name not in self._cache:
            oids, sizes = self._load(name)
            self._cache[name] = dict(zip(oids.tolist(), sizes.tolist(), strict=True))
        return self._cache[name]

    def forget(self, date: str, hour: int) -> None:
        self._cache.pop(f"{date}/ex{hour}.gz", None)


def next_hour(date: str, hour: int) -> tuple[str, int]:
    stamp = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC) + timedelta(hours=hour + 1)
    return stamp.strftime("%Y%m%d"), stamp.hour


EVENT_SCHEMA = pa.schema(
    [
        ("coin", pa.string()), ("ts_ns", pa.int64()), ("ts_ms", pa.int64()),
        ("kind", pa.string()), ("oid", pa.int64()), ("user_id", pa.int64()),
        ("user", pa.string()), ("is_ask", pa.bool_()), ("limit_px", pa.float64()),
        ("sz", pa.float64()), ("orig_sz", pa.float64()), ("tif", pa.string()),
        ("opposite_best_px", pa.float64()), ("marketable_at_block_start", pa.bool_()),
    ],
    metadata={"source": SOURCE},
)


def load_users(albers_dir: Path) -> dict[int, str]:
    path = albers_dir / "mapdir.tar.xz"
    if not path.exists():
        return {}
    with tarfile.open(path, mode="r:xz") as tf:
        handle = tf.extractfile("mapdir/users.csv")
        assert handle is not None
        return read_users_csv(io.TextIOWrapper(handle, encoding="utf-8"))


def table_from_rows(rows: list[dict[str, Any]]) -> pa.Table:
    columns = list(rows[0])
    schema = pa.schema(
        [
            pa.field(
                name,
                pa.string()
                if name == "coin"
                else pa.int64() if name in _INT_COLUMNS else pa.float64(),
            )
            for name in columns
        ],
        metadata={"source": SOURCE},
    )
    return pa.Table.from_pylist(rows, schema=schema)


def build(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    dates = parse_date_spec(args.dates)
    hours = parse_hours(args.hours)
    plan = [(d, h) for d in dates for h in hours]
    status_path = args.albers_dir / f"{coin.lower()}_orders_202512.tar.xz"
    diff_names: list[str] = []
    for d, h in plan:
        nd, nh = next_hour(d, h)
        diff_names += [f"{d}/ex{h}.gz", f"{nd}/ex{nh}.gz"]
    executor = (
        ProcessPoolExecutor(args.diff_workers, mp_context=get_context("spawn"))
        if args.diff_workers > 0
        else None
    )
    diffs = DiffReader(args.albers_dir / "book_diffs_202512.tar", coin, diff_names, executor)
    layout = HyperliquidLakeLayout(args.lake_root)
    wanted = {f"{d}/{coin.lower()}_{h:02d}.data.gz": (d, h) for d, h in plan}
    book = AlbersBook(coin)
    users = load_users(args.albers_dir)
    event_writers: dict[str, pq.ParquetWriter] = {}
    run_start_ns: int | None = None
    warmup_ns = int(args.warmup_minutes * 60e9)
    writers: dict[str, pq.ParquetWriter] = {}
    report: dict[str, list[dict[str, Any]]] = {d: [] for d in dates}
    t0 = time.perf_counter()
    try:
        for name, raw in iter_status_members(status_path, coin, set(wanted)):
            date, hour = wanted[name]
            records = read_status_records(raw)
            rested = dict(diffs.rested(date, hour))
            rested.update(diffs.rested(*next_hour(date, hour)))
            diffs.forget(date, hour)
            events: list[dict[str, Any]] = []
            rows, stats = book.replay_hour(records, rested, ReplayStats(), events)
            for event in events:
                event["user"] = users.get(event["user_id"])
            if events:
                if date not in event_writers:
                    path = layout.silver_order_events_path(coin, date)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    event_writers[date] = pq.ParquetWriter(path, EVENT_SCHEMA, compression="zstd")
                event_writers[date].write_table(
                    pa.Table.from_pylist(events, schema=EVENT_SCHEMA)
                )
            if run_start_ns is None and records.size:
                run_start_ns = int(records["ts"][0])
            if run_start_ns is not None:
                rows = [r for r in rows if r["ts_ns"] >= run_start_ns + warmup_ns]
            entry = {"hour": hour, **stats.to_dict(), "rows_written": len(rows)}
            report[date].append(entry)
            if rows:
                table = table_from_rows(rows)
                if date not in writers:
                    path = layout.silver_l2_book_path(coin, date)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    writers[date] = pq.ParquetWriter(path, table.schema, compression="zstd")
                writers[date].write_table(table)
            print(
                f"{name}: {stats.records:,} statuses, {stats.blocks:,} blocks, "
                f"{len(rows):,} rows, crossed={stats.crossed_blocks}, "
                f"fills at touch={entry['fill_at_touch_share']}, "
                f"{time.perf_counter() - t0:.0f}s",
                flush=True,
            )
    finally:
        if executor is not None:
            executor.shutdown(cancel_futures=True)
        for writer in (*writers.values(), *event_writers.values()):
            writer.close()
    for date, hours_report in report.items():
        if not hours_report:
            continue
        path = layout.silver_l2_book_path(coin, date).with_suffix(".validation.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "coin": coin,
            "date": date,
            "source": SOURCE,
            "warmup_minutes": args.warmup_minutes,
            "hours": hours_report,
        }
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"dates": list(writers), "elapsed_s": round(time.perf_counter() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(build(parse_args(argv)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
