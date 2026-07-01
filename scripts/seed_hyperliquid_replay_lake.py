"""Fetch live Hyperliquid public API data and seed the local replay lake."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

from marketimmune.ingest.hyperliquid_api import HyperliquidInfoAPI
from marketimmune.ingest.hyperliquid_archive import BookSnapshot
from marketimmune.ingest.hyperliquid_asset_ctxs import AssetCtx
from marketimmune.ingest.hyperliquid_lake import (
    HyperliquidLakeLayout,
    LakeWrite,
    write_silver_asset_ctxs,
    write_silver_candles,
    write_silver_l2_book,
)
from marketimmune.ingest.hyperliquid_replay_seed import (
    ReplayLakeSeed,
    write_replay_lake_seed,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coin", default="BTC", help="Hyperliquid perp coin, e.g. BTC.")
    parser.add_argument("--symbol", default="BTCUSDT", help="Replay-engine symbol.")
    parser.add_argument("--interval", default="1m", help="Candle interval. Only 1m seeds replay.")
    parser.add_argument("--lookback-minutes", type=int, default=120)
    parser.add_argument("--rows", type=int, default=90, help="Max recent candles to keep.")
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument(
        "--replay-lake-root",
        type=Path,
        default=Path("data/lake/binance_usdm"),
        help="Current replay lake consumed by ReplayBuilder.",
    )
    parser.add_argument(
        "--hyperliquid-lake-root",
        type=Path,
        default=Path("data/hyperliquid"),
        help="Native Hyperliquid Bronze/Silver/Gold lake root.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.lookback_minutes < 1:
        raise ValueError("--lookback-minutes must be >= 1")
    if args.interval != "1m":
        raise ValueError("--interval must be 1m when seeding the replay lake")

    api = HyperliquidInfoAPI.live(timeout_s=args.timeout_s)
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.lookback_minutes * 60_000

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

    seed = write_replay_lake_seed(
        lake_root=args.replay_lake_root,
        symbol=args.symbol,
        candles=candles,
        book=book,
        max_candles=args.rows,
    )
    silver_writes = _write_native_silver(args.hyperliquid_lake_root, seed, book, contexts)

    summary: dict[str, object] = {
        "source": "hyperliquid public info api",
        "coin": seed.coin,
        "symbol": seed.symbol,
        "date": seed.date,
        "mids": len(mids),
        "candles": len(seed.selected_candles),
        "dropped_candles": seed.dropped_candles,
        "l2_levels": seed.depth_write.rows,
        "asset_contexts": len(contexts),
        "replay_paths": [str(seed.kline_write.path), str(seed.depth_write.path)],
        "hyperliquid_paths": [str(write.path) for write in silver_writes],
    }
    print(json.dumps(summary, indent=2))
    return 0


def _write_native_silver(
    root: Path,
    seed: ReplayLakeSeed,
    book: BookSnapshot,
    contexts: list[AssetCtx],
) -> list[LakeWrite]:
    layout = HyperliquidLakeLayout(root)
    date_compact = seed.date.replace("-", "")
    return [
        write_silver_l2_book(layout, coin=seed.coin, date=date_compact, snapshots=[book]),
        write_silver_asset_ctxs(layout, date=date_compact, contexts=contexts),
        write_silver_candles(
            layout,
            coin=seed.coin,
            interval="1m",
            date=date_compact,
            candles=seed.selected_candles,
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
