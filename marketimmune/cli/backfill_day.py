"""Backfill one Hyperliquid coin-day from the requester-pays S3 buckets into the lake (``aws`` extra).

python -m marketimmune.cli.backfill_day --coin SOL --date 20250727 --hour 0-23 --fill-hour 0-23
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from marketimmune.lake.backfill import parse_hours, run_backfill
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.sources import hyperliquid_s3 as s3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--coin", required=True)
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--hour", action="append", required=True, help="L2 book hours, e.g. 0-23 or 8,9 (repeatable)")
    ap.add_argument("--fill-hour", action="append", default=[], help="node_fills_by_block hours, same syntax")
    ap.add_argument("--lake-root", type=Path, default=Path("data"))
    ap.add_argument("--skip-asset-ctxs", action="store_true", help="do not fetch asset_ctxs/<date>.csv.lz4")
    args = ap.parse_args(argv)
    result = run_backfill(
        HyperliquidLakeLayout(args.lake_root),
        archive=s3.fetcher(s3.ARCHIVE_BUCKET, s3.ARCHIVE_REGION),
        node=s3.fetcher(s3.NODE_BUCKET, s3.NODE_REGION),
        coin=args.coin,
        date=args.date,
        hours=parse_hours(args.hour),
        fill_hours=parse_hours(args.fill_hour) if args.fill_hour else (),
        include_asset_ctxs=not args.skip_asset_ctxs,
    )
    summary = {
        "coin": result.coin,
        "date": result.date,
        "book_snapshots": result.book_snapshots,
        "asset_contexts": result.asset_contexts,
        "fills": result.fills,
        "gold_rows": result.gold_rows,
        "training_rows": result.training_rows,
        "writes": [str(write.path) for write in result.writes],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
