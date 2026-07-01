"""Rebuild Hyperliquid Gold training rows from local lake artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marketimmune.features.hyperliquid_features import build_hyperliquid_training_rows
from marketimmune.ingest.hyperliquid_lake import (
    HyperliquidLakeLayout,
    read_parquet_records,
    write_gold_training_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--date", default="20260601")
    parser.add_argument(
        "--lake-root",
        type=Path,
        default=Path("data/hyperliquid"),
        help="Hyperliquid lake root.",
    )
    return parser.parse_args()


def rebuild_training_rows(
    *,
    lake_root: Path,
    coin: str,
    date: str,
) -> dict[str, object]:
    layout = HyperliquidLakeLayout(lake_root)
    markout_path = layout.gold_markout_path(coin, date)
    l2_path = layout.silver_l2_book_path(coin, date)
    asset_path = layout.silver_asset_ctxs_path(date)

    label_rows = read_parquet_records(markout_path)
    l2_rows = read_parquet_records(l2_path)
    asset_rows = read_parquet_records(asset_path) if asset_path.exists() else []

    training_rows = build_hyperliquid_training_rows(
        label_rows,
        l2_rows,
        asset_rows,
    )
    write = write_gold_training_rows(
        layout,
        coin=coin,
        date=date,
        rows=training_rows,
    )
    return {
        "coin": coin.upper(),
        "date": date,
        "markout_rows": len(label_rows),
        "l2_rows": len(l2_rows),
        "asset_rows": len(asset_rows),
        "training_rows": len(training_rows),
        "path": str(write.path),
    }


def main() -> int:
    args = parse_args()
    result = rebuild_training_rows(
        lake_root=args.lake_root,
        coin=args.coin,
        date=args.date,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
