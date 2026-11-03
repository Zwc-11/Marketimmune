"""Roll wallet positions forward through Silver fills, a day at a time.

    python -m marketimmune.cli.build_positions --coin SOL --dates 20251201..20251231

Writes ``silver/hyperliquid/positions/<COIN>/<COIN>-<date>.parquet`` (one row per wallet side
of every fill: position after it, average entry, whether the chain held) and
``<same>.stats.json`` (chain-break rate, forced liquidations that reduced the position,
long/short size over the wallets seen, open wallets). State carries across dates, so run the
dates in one call.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from marketimmune.forced.positions import FILL_COLUMNS, WalletState, long_short_open_interest, open_positions, roll_positions, wallet_events
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.logger import init_logger
from marketimmune.utils import parse_date_spec

logger = init_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    return parser.parse_args(argv)


def positions_path(lake_root: Path, coin: str, date: str) -> Path:
    symbol = coin.upper()
    return lake_root / "silver" / "hyperliquid" / "positions" / symbol / f"{symbol}-{date}.parquet"


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    state: dict[str, WalletState] = {}
    summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        fills_path = layout.silver_fills_path(coin, date)
        if not fills_path.exists():
            continue
        rolled, state, stats = roll_positions(wallet_events(pd.read_parquet(fills_path, columns=list(FILL_COLUMNS))), state)
        out = positions_path(args.lake_root, coin, date)
        out.parent.mkdir(parents=True, exist_ok=True)
        rolled.to_parquet(out, compression="zstd", index=False)
        summary = {
            "date": date,
            **stats.to_dict(),
            "open_wallets_end": len(open_positions(state)),
            "seen_size_end": long_short_open_interest(state),
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }
        out.with_suffix(".stats.json").write_text(json.dumps(summary, indent=2) + "\n")
        summaries.append(summary)
        logger.info(json.dumps(summary))
    return summaries


def main(argv: list[str] | None = None) -> int:
    build(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
