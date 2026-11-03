"""Pull Hyperliquid perp candles from the ``info`` endpoint (HYPE's USD price for priority fees).

    python -m marketimmune.cli.pull_candles --coin HYPE --intervals 1h,4h --dates 20260301..20261031

``priorityGas`` on a fill is the burned fee in HYPE, converted at HYPE's spot mark when the order
filled (docs: priority fees), so turning it into bps of notional needs HYPE's USD price. The
endpoint keeps only the latest 5,000 candles per interval: 1h reaches back about 208 days, 4h
about 833. Writes ``<out>/<COIN>-<interval>.parquet`` (``t`` open time in ms, ``o``, ``h``,
``l``, ``c``), merged with what is already there.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from marketimmune.sources.hyperliquid_meta import fetch_candles
from marketimmune.utils import DAY_MS, day_start_ms, parse_date_spec, split_csv

SCHEMA = {"t": pl.Int64, "o": pl.Float64, "h": pl.Float64, "l": pl.Float64, "c": pl.Float64}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="HYPE")
    parser.add_argument("--intervals", default="1h,4h")
    parser.add_argument("--dates", default="20260301..20261031")
    parser.add_argument("--out", type=Path, default=Path("data/bronze/hyperliquid/candles"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dates = parse_date_spec(args.dates)
    start, end = day_start_ms(dates[0]), day_start_ms(dates[-1]) + DAY_MS
    args.out.mkdir(parents=True, exist_ok=True)
    for interval in split_csv(args.intervals):
        rows = fetch_candles(args.coin, interval, start, end)
        new = pl.DataFrame([{k: (c[k] if k == "t" else float(c[k])) for k in SCHEMA} for c in rows], schema=SCHEMA)
        path = args.out / f"{args.coin}-{interval}.parquet"
        if path.exists():
            new = pl.concat([pl.read_parquet(path).filter(~pl.col("t").is_in(new["t"].implode())), new])
        new = new.sort("t")
        new.write_parquet(path)
        span = f"{new.select(pl.col('t').min()).item()} .. {new.select(pl.col('t').max()).item()}" if new.height else "none"
        print(f"{args.coin} {interval}: {len(rows)} fetched, {new.height} stored, open times {span} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
