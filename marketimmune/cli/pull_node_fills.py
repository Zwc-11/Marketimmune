"""Pull some coins' fills from ``node_fills_by_block`` into one Parquet per coin and day (run in Tokyo).

    python -m marketimmune.cli.pull_node_fills --dates 20260301..20261031 --coins BTC,ETH,SOL --out data/bronze/node_fills

Each hourly LZ4 file (every coin, 0.4 to 1.4 GiB a day) is streamed from the requester-pays
bucket. Transfer to an EC2 instance in ap-northeast-1 is free. Only the legs of ``--coins`` are
kept, with every field: the priority fee, builder fee, and the liquidation method, mark price and
wallet. They are written to ``<out>/<COIN>/<COIN>-<YYYYMMDD>.parquet`` (``priority.fills.FILL_SCHEMA``),
sorted by block, trade id and side, ``--chunk-rows`` legs at a time, so memory stays flat on the
busiest days. A day whose files all exist is skipped, so an interrupted spot run resumes where it
stopped. Prints a JSON line per day: legs per coin, bytes read, seconds.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import lz4.frame
import polars as pl
import pyarrow.parquet as pq

from marketimmune.priority.fills import rows, to_frame
from marketimmune.sources.hyperliquid_s3 import NODE_BUCKET, NODE_REGION, RP, client, fills_day
from marketimmune.utils import parse_date_spec, parse_symbol_spec

# NOTE: the old whole-day parse held a Python dict per leg of every coin and was OOM-killed on
# busy days (2025-10-10, 2025-12-01, 2026-03-02) even alone on the 4 GB instance
CHUNK_ROWS = 200_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dates", required=True, help="YYYYMMDD, lists or a..b ranges")
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--workers", type=int, default=1, help="days pulled in parallel")
    parser.add_argument("--chunk-rows", type=int, default=CHUNK_ROWS, help="legs parsed and written at a time")
    return parser.parse_args(argv)


def write_day(
    hours: Iterable[Iterable[str]], coins: Sequence[str], paths: Mapping[str, Path], *, chunk_rows: int = CHUNK_ROWS
) -> dict[str, int]:
    """Write ``coins``' legs from a day's hourly files (each an iterable of block lines, in time
    order) to one Parquet per coin, sorted by (block, tid, crossed). Returns the legs per coin.

    Legs are parsed ``chunk_rows`` at a time and each chunk is written as row groups. A chunk
    ends at a block line, so a block never spans two chunks and chunks sorted on their own make
    a sorted file; if the blocks were not in order, that coin's file is sorted again at the end.
    """
    needles = [f'"{c}"' for c in coins]
    wanted = frozenset(coins)
    tmp = {c: paths[c].with_suffix(".part") for c in coins}
    writers: dict[str, pq.ParquetWriter] = {}
    legs = dict.fromkeys(coins, 0)
    last_block = dict.fromkeys(coins, -1)
    in_order = dict.fromkeys(coins, True)
    buf: list[dict[str, Any]] = []

    def flush() -> None:
        frame = to_frame(buf)
        buf.clear()
        for coin in coins:
            part = frame.filter(pl.col("coin") == coin).sort("block_number", "tid", "crossed")
            if part.height == 0:
                continue
            in_order[coin] &= int(part["block_number"][0]) > last_block[coin]
            last_block[coin] = int(part["block_number"][-1])
            table = part.to_arrow()
            if coin not in writers:
                tmp[coin].parent.mkdir(parents=True, exist_ok=True)
                writers[coin] = pq.ParquetWriter(tmp[coin], table.schema, compression="zstd")
            writers[coin].write_table(table)
            legs[coin] += part.height

    for lines in hours:
        for line in lines:
            if any(n in line for n in needles):
                buf.extend(rows([line], wanted))
                if len(buf) >= chunk_rows:
                    flush()
    if buf:
        flush()
    for coin in coins:
        if coin in writers:
            writers[coin].close()
            if not in_order[coin]:
                pl.read_parquet(tmp[coin]).sort("block_number", "tid", "crossed").write_parquet(tmp[coin], compression="zstd")
        else:
            tmp[coin].parent.mkdir(parents=True, exist_ok=True)
            to_frame([]).write_parquet(tmp[coin], compression="zstd")
        tmp[coin].replace(paths[coin])  # whole files only, so a resumed run trusts what exists
    return legs


def _lines(s3: Any, key: str) -> Iterator[str]:
    """Block lines of one hourly file, decompressed as they are read."""
    with lz4.frame.open(io.BytesIO(s3.get_object(Bucket=NODE_BUCKET, Key=key, **RP)["Body"].read()), "rt") as fh:
        yield from fh


def pull_day(out: Path, coins: tuple[str, ...], day: str, chunk_rows: int = CHUNK_ROWS) -> dict[str, Any]:
    paths = {c: out / c / f"{c}-{day}.parquet" for c in coins}
    if all(p.exists() for p in paths.values()):
        return {"day": day, "skipped": True}
    t0 = time.perf_counter()
    s3 = client(NODE_REGION)
    objs = fills_day(s3, day)
    assert len(objs) == 24, f"{day}: {len(objs)} hourly files"
    legs = write_day((_lines(s3, o.key) for o in objs), coins, paths, chunk_rows=chunk_rows)
    return {
        "day": day,
        "legs": legs,
        "gib_read": round(sum(o.size for o in objs) / 2**30, 3),
        "seconds": round(time.perf_counter() - t0, 1),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    coins, dates = parse_symbol_spec(args.coins), parse_date_spec(args.dates)
    with ProcessPoolExecutor(min(args.workers, len(dates)), mp_context=get_context("spawn")) as pool:
        for result in pool.map(pull_day, [args.out] * len(dates), [coins] * len(dates), dates, [args.chunk_rows] * len(dates)):
            print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
