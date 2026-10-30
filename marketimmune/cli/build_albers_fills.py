"""Albers December 2025 trades -> Silver fills (one row per match).

    python -m marketimmune.cli.build_albers_fills --coin SOL --dates 20251201..20251231

Reads ``trades_2025_12.tar`` (hourly gz JSON lines, all coins) by seek and writes
``silver/hyperliquid/fills/<COIN>/<COIN>-<date>.parquet`` with maker and taker
wallets, oids and start positions. ``liquidation`` is set when the taker oid is a
forced-liquidation order in that date's Silver order events (written by
``build_albers_silver.py``; run that first, or every row says ``False``).
Albers trades carry no fees, so the fee columns are null.
"""

from __future__ import annotations

import argparse
import json
import tarfile
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.lake.tables import HyperliquidLakeLayout, write_silver_fills
from marketimmune.sources.albers_l4 import albers_trades_member_to_matches, gunzip
from marketimmune.sources.hyperliquid_node_fills import MatchFill


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201")
    parser.add_argument(
        "--albers-dir", type=Path, default=Path("data/bronze/albers")
    )
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
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
                raw = gunzip(handle.read())
                matches.extend(albers_trades_member_to_matches(raw, coin, liq or set()))
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
