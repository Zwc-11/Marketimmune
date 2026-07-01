"""Fetch a small public Hyperliquid API sample into the local lake.

This uses the free ``https://api.hyperliquid.xyz/info`` endpoint. It is for live
smoke data and recent market context, not historical fill-label training.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from marketimmune.ingest.hyperliquid_api import HyperliquidInfoAPI
from marketimmune.ingest.hyperliquid_lake import (
    HyperliquidLakeLayout,
    LakeWrite,
    write_silver_asset_ctxs,
    write_silver_candles,
    write_silver_l2_book,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coin", default="BTC", help="Perp coin, e.g. BTC.")
    parser.add_argument("--interval", default="1m", help="Candle interval, e.g. 1m or 15m.")
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=60,
        help="Recent candle lookback window.",
    )
    parser.add_argument(
        "--lake-root",
        type=Path,
        default=Path("data/hyperliquid"),
        help="Output lake root.",
    )
    parser.add_argument("--timeout-s", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.lookback_minutes < 1:
        raise ValueError("--lookback-minutes must be >= 1")

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.lookback_minutes * 60_000
    api = HyperliquidInfoAPI.live(timeout_s=args.timeout_s)
    layout = HyperliquidLakeLayout(args.lake_root)

    try:
        mids = api.all_mids()
        book = api.l2_book(args.coin)
        contexts = api.meta_and_asset_ctxs()
        candles = api.candles(
            coin=args.coin,
            interval=args.interval,
            start_time_ms=start_ms,
            end_time_ms=now_ms,
        )
    except httpx.HTTPError as exc:
        print(
            json.dumps({
                "error": "hyperliquid public api request failed",
                "detail": str(exc),
            }),
            file=sys.stderr,
        )
        return 2
    date = datetime.fromtimestamp(book.ts_ms / 1000.0, UTC).strftime("%Y%m%d")

    writes: list[LakeWrite] = [
        write_silver_l2_book(layout, coin=args.coin, date=date, snapshots=[book]),
        write_silver_asset_ctxs(layout, date=date, contexts=contexts),
    ]
    if candles:
        writes.append(
            write_silver_candles(
                layout,
                coin=args.coin,
                interval=args.interval,
                date=date,
                candles=candles,
            )
        )

    summary: dict[str, Any] = {
        "source": "hyperliquid public info api",
        "coin": args.coin,
        "date": date,
        "mids": len(mids),
        "l2_snapshots": 1,
        "asset_contexts": len(contexts),
        "candles": len(candles),
        "paths": [str(write.path) for write in writes],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
