"""Rebuild Gold training rows (and their ``.leakage.json`` sidecar) from a day's Gold markout and Silver L2.

python -m marketimmune.cli.rebuild_training_rows --coin SOL --date 20251201 --lake-root data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marketimmune.features.training_rows import L2_JOIN_COLUMNS, build_hyperliquid_training_rows, verify_training_rows_no_lookahead
from marketimmune.lake.tables import HyperliquidLakeLayout, read_parquet_records, write_gold_training_rows, write_leakage_report


def rebuild_training_rows(*, lake_root: Path, coin: str, date: str) -> dict[str, object]:
    """Join one day's labels to features known before each fill; asset contexts join when the day has them."""
    layout = HyperliquidLakeLayout(lake_root)
    asset_path = layout.silver_asset_ctxs_path(date)
    label_rows = read_parquet_records(layout.gold_markout_path(coin, date))
    l2_rows = read_parquet_records(layout.silver_l2_book_path(coin, date), columns=L2_JOIN_COLUMNS)
    asset_rows = read_parquet_records(asset_path) if asset_path.exists() else []  # Albers days have none
    training_rows = build_hyperliquid_training_rows(label_rows, l2_rows, asset_rows)
    write = write_gold_training_rows(layout, coin=coin, date=date, rows=training_rows)
    leakage = verify_training_rows_no_lookahead(label_rows, l2_rows, asset_rows).to_dict()
    leakage_path = write_leakage_report(layout, coin=coin, date=date, report=leakage)
    return {
        "coin": coin.upper(),
        "date": date,
        "markout_rows": len(label_rows),
        "l2_rows": len(l2_rows),
        "asset_rows": len(asset_rows),
        "training_rows": len(training_rows),
        "path": str(write.path),
        "leakage_check": {k: leakage[k] for k in ("passed", "n_checked", "n_mismatched")},
        "leakage_report": str(leakage_path),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coin", default="SOL")
    ap.add_argument("--date", default="20260601", help="YYYYMMDD")
    ap.add_argument("--lake-root", type=Path, default=Path("data"))
    args = ap.parse_args(argv)
    print(json.dumps(rebuild_training_rows(lake_root=args.lake_root, coin=args.coin, date=args.date), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
