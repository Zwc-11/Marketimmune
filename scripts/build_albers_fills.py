"""Albers December 2025 trades -> Silver fills (one row per match).

    python scripts/build_albers_fills.py --coin SOL --dates 20251201..20251231

Reads ``trades_2025_12.tar`` (hourly gz JSON lines, all coins) by seek and writes
``silver/hyperliquid/fills/<COIN>/<COIN>-<date>.parquet`` with maker and taker
wallets, oids and start positions. ``liquidation`` is set when the taker oid is a
forced-liquidation order in that date's Silver order events (written by
``build_albers_silver_l2.py``; run that first, or every row says ``False``).
Albers trades carry no fees, so the fee columns are null.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pyarrow.parquet as pq

from marketimmune.ingest.albers import albers_trades_to_matches
from marketimmune.ingest.hyperliquid_fills import MatchFill
from marketimmune.ingest.hyperliquid_lake import HyperliquidLakeLayout, write_silver_fills
from scripts.hyperliquid_markout_data import parse_date_spec


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201")
    parser.add_argument(
        "--albers-dir", type=Path, default=Path("price-of-priority/data/bronze/albers")
    )
    parser.add_argument("--lake-root", type=Path, default=Path("data/hyperliquid"))
    return parser.parse_args(argv)


def liquidation_oids(layout: HyperliquidLakeLayout, coin: str, date: str) -> set[int] | None:
    path = layout.silver_order_events_path(coin, date)
    if not path.exists():
        return None
    table = pq.read_table(path, columns=["kind", "oid"]).to_pydict()
    return {o for k, o in zip(table["kind"], table["oid"], strict=True) if k == "liquidation"}


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    with tarfile.open(args.albers_dir / "trades_2025_12.tar", mode="r:") as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
        for date in parse_date_spec(args.dates):
            liq = liquidation_oids(layout, coin, date)
            matches: list[MatchFill] = []
            for hour in range(24):
                name = f"{date}/{hour}.gz"
                if name not in names:
                    continue
                handle = tar.extractfile(name)
                assert handle is not None
                with gzip.open(io.BufferedReader(handle), "rt", encoding="utf-8") as lines:
                    matches.extend(albers_trades_to_matches(lines, coin, liq or set()))
            if not matches:
                continue
            matches.sort(key=lambda m: m.ts_ms)
            write = write_silver_fills(layout, coin=coin, date=date, fills=matches)
            summary = {
                "date": date,
                "matches": len(matches),
                "liquidation_matches": sum(m.liquidation for m in matches),
                "liquidation_source": "order_events" if liq is not None else "missing",
                "path": str(write.path),
                "elapsed_s": round(time.perf_counter() - t0, 1),
            }
            summaries.append(summary)
            print(json.dumps(summary), flush=True)
    return summaries


def main(argv: list[str] | None = None) -> int:
    build(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
