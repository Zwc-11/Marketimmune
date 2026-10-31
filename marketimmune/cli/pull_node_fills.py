"""Pull some coins' fills from ``node_fills_by_block`` into one Parquet per coin and day (run in Tokyo).

    python -m marketimmune.cli.pull_node_fills --dates 20260301..20261031 --coins BTC,ETH,SOL --out data/bronze/node_fills

Each hourly LZ4 file (every coin, 0.4 to 1.4 GiB a day) is streamed from the requester-pays
bucket. Transfer to an EC2 instance in ap-northeast-1 is free. Only the legs of ``--coins`` are
kept, with every field: the priority fee, builder fee, and the liquidation method, mark price and
wallet. They are written to ``<out>/<COIN>/<COIN>-<YYYYMMDD>.parquet`` (``priority.fills.FILL_SCHEMA``).
A day whose files all exist is skipped, so an interrupted spot run resumes where it stopped.
Prints a JSON line per day: legs per coin, bytes read, seconds.
"""

from __future__ import annotations

import argparse
import io
import json
import time
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import lz4.frame
import polars as pl

from marketimmune.priority.fills import FILL_SCHEMA, parse
from marketimmune.sources.hyperliquid_s3 import NODE_BUCKET, NODE_REGION, RP, client, fills_day
from marketimmune.utils import parse_date_spec, parse_symbol_spec


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dates", required=True, help="YYYYMMDD, lists or a..b ranges")
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--workers", type=int, default=2, help="days pulled in parallel")
    return parser.parse_args(argv)


def coin_frames(hours: Iterable[Iterable[str]], coins: Sequence[str]) -> dict[str, pl.DataFrame]:
    """The legs of ``coins`` in a day's hourly files (each an iterable of block lines), one frame per coin."""
    needles = [f'"{c}"' for c in coins]
    # NOTE: one hour at a time; a day decompressed is up to 10 GB of JSON
    parts = [parse(line for line in lines if any(n in line for n in needles)) for lines in hours]
    day = pl.concat(parts) if parts else pl.DataFrame(schema=FILL_SCHEMA)
    return {c: day.filter(pl.col("coin") == c).sort("block_number", "tid", "crossed") for c in coins}


def _lines(s3: Any, key: str) -> Iterator[str]:
    """Block lines of one hourly file, decompressed as they are read."""
    with lz4.frame.open(io.BytesIO(s3.get_object(Bucket=NODE_BUCKET, Key=key, **RP)["Body"].read()), "rt") as fh:
        yield from fh


def pull_day(out: Path, coins: tuple[str, ...], day: str) -> dict[str, Any]:
    paths = {c: out / c / f"{c}-{day}.parquet" for c in coins}
    if all(p.exists() for p in paths.values()):
        return {"day": day, "skipped": True}
    t0 = time.perf_counter()
    s3 = client(NODE_REGION)
    objs = fills_day(s3, day)
    assert len(objs) == 24, f"{day}: {len(objs)} hourly files"
    frames = coin_frames((_lines(s3, o.key) for o in objs), coins)
    for coin, frame in frames.items():
        paths[coin].parent.mkdir(parents=True, exist_ok=True)
        tmp = paths[coin].with_suffix(".part")
        frame.write_parquet(tmp, compression="zstd")
        tmp.replace(paths[coin])  # whole files only, so a resumed run trusts what exists
    return {
        "day": day,
        "legs": {c: f.height for c, f in frames.items()},
        "gib_read": round(sum(o.size for o in objs) / 2**30, 3),
        "seconds": round(time.perf_counter() - t0, 1),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    coins, dates = parse_symbol_spec(args.coins), parse_date_spec(args.dates)
    with ProcessPoolExecutor(min(args.workers, len(dates)), mp_context=get_context("spawn")) as pool:
        for result in pool.map(pull_day, [args.out] * len(dates), [coins] * len(dates), dates):
            print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
