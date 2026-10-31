"""Albers December 2025 trades -> Silver fills (one row per match).

    python -m marketimmune.cli.build_albers_fills --coin SOL --dates 20251201..20251231

Reads ``trades_2025_12.tar`` (hourly gz JSON lines, all coins) by seek and writes
``silver/hyperliquid/fills/<COIN>/<COIN>-<date>.parquet`` with maker and taker wallets,
oids and start positions. ``liquidation`` is set when the taker oid is a
forced-liquidation order in that date's Silver order events, so ``build_albers_silver``
runs first. Albers trades carry no fees, so the fee columns are null.
"""

from __future__ import annotations

import argparse
import json
import tarfile
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from marketimmune.lake.tables import HyperliquidLakeLayout, write_silver_fills
from marketimmune.logger import init_logger
from marketimmune.sources.albers_l4 import albers_trades_member_to_matches, gunzip
from marketimmune.sources.hyperliquid_node_fills import MatchFill
from marketimmune.utils import parse_date_spec

logger = init_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201")
    parser.add_argument("--albers-dir", type=Path, default=Path("data/bronze/albers"))
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    return parser.parse_args(argv)


def liquidation_oids(layout: HyperliquidLakeLayout, coin: str, date: str) -> set[int]:
    path = layout.silver_order_events_path(coin, date)
    assert path.exists(), f"{path} is missing: run build_albers_silver for {date} first"
    return set(pq.read_table(path, columns=["oid"], filters=[("kind", "==", "liquidation")])["oid"].to_pylist())


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    with tarfile.open(args.albers_dir / "trades_2025_12.tar", mode="r:") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        for date in parse_date_spec(args.dates):
            hours = [members[name] for hour in range(24) if (name := f"{date}/{hour}.gz") in members]
            if not hours:
                continue
            liquidations = liquidation_oids(layout, coin, date)
            matches: list[MatchFill] = []
            for member in hours:
                handle = tar.extractfile(member)
                assert handle is not None
                matches += albers_trades_member_to_matches(gunzip(handle.read()), coin, liquidations)
            if not matches:
                continue
            matches.sort(key=lambda m: m.ts_ms)
            write = write_silver_fills(layout, coin=coin, date=date, fills=matches)
            summary = {
                "date": date,
                "matches": len(matches),
                "liquidation_matches": sum(m.liquidation for m in matches),
                "path": str(write.path),
                "elapsed_s": round(time.perf_counter() - t0, 1),
            }
            summaries.append(summary)
            logger.info(json.dumps(summary))
    return summaries


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(build(parse_args(argv)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
