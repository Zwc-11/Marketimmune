"""Hyperliquid public Info API ingestion.

This is the free, lightweight path for current/recent market data. It is useful for
smoke tests, live snapshots, and bootstrapping small local samples. It is not a
replacement for the requester-pays S3 archive when training needs historical fills.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from marketimmune.ingest.hyperliquid_archive import BookSnapshot, parse_book_snapshot
from marketimmune.ingest.hyperliquid_asset_ctxs import AssetCtx, parse_asset_ctx_row

INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True, slots=True)
class Candle:
    """One Hyperliquid candle snapshot row."""

    coin: str
    interval: str
    open_ts_ms: int
    close_ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "interval": self.interval,
            "open_ts_ms": self.open_ts_ms,
            "close_ts_ms": self.close_ts_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trade_count": self.trade_count,
        }


@dataclass(frozen=True, slots=True)
class HyperliquidInfoAPI:
    """Small wrapper around the public ``/info`` endpoint."""

    post: Callable[[Mapping[str, Any]], Any]

    @classmethod
    def live(cls, *, timeout_s: float = 10.0) -> HyperliquidInfoAPI:
        return cls(post=httpx_info_post(timeout_s=timeout_s))

    def all_mids(self) -> dict[str, float]:
        """Return current mids keyed by coin."""
        data = self.post({"type": "allMids"})
        if not isinstance(data, Mapping):
            raise ValueError("allMids response must be an object")
        return {str(coin): float(mid) for coin, mid in data.items()}

    def l2_book(self, coin: str) -> BookSnapshot:
        """Return the current L2 book snapshot for one coin."""
        data = self.post({"type": "l2Book", "coin": coin})
        if not isinstance(data, Mapping):
            raise ValueError("l2Book response must be an object")
        return parse_book_snapshot(data)

    def meta_and_asset_ctxs(self) -> list[AssetCtx]:
        """Return current perpetual asset contexts with coin names attached."""
        data = self.post({"type": "metaAndAssetCtxs"})
        return parse_meta_and_asset_ctxs(data)

    def candles(
        self,
        *,
        coin: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> list[Candle]:
        """Return recent candles. Hyperliquid returns at most 5000 candles."""
        data = self.post({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        })
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise ValueError("candleSnapshot response must be a list")
        return [parse_candle(row) for row in data]


def parse_meta_and_asset_ctxs(data: object) -> list[AssetCtx]:
    """Parse ``metaAndAssetCtxs`` response into named asset contexts."""
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)) or len(data) != 2:
        raise ValueError("metaAndAssetCtxs response must be [meta, asset_contexts]")
    meta, ctxs = data
    if not isinstance(meta, Mapping) or not isinstance(ctxs, Sequence):
        raise ValueError("metaAndAssetCtxs response has invalid parts")
    universe = meta.get("universe")
    if not isinstance(universe, Sequence) or isinstance(universe, (str, bytes)):
        raise ValueError("metaAndAssetCtxs meta.universe must be a list")
    names = [_asset_name(asset) for asset in universe]
    if len(names) != len(ctxs):
        raise ValueError("meta universe and asset context lengths differ")
    out: list[AssetCtx] = []
    for name, ctx in zip(names, ctxs, strict=True):
        if not isinstance(ctx, Mapping):
            raise ValueError("asset context rows must be objects")
        out.append(parse_asset_ctx_row(dict(ctx) | {"coin": name}))
    return out


def parse_candle(row: Mapping[str, Any]) -> Candle:
    """Parse one candle row from the documented abbreviated field names."""
    return Candle(
        coin=str(row["s"]),
        interval=str(row["i"]),
        open_ts_ms=int(row["t"]),
        close_ts_ms=int(row["T"]),
        open=float(row["o"]),
        high=float(row["h"]),
        low=float(row["l"]),
        close=float(row["c"]),
        volume=float(row["v"]),
        trade_count=int(row["n"]),
    )


def httpx_info_post(
    *,
    url: str = INFO_URL,
    timeout_s: float = 10.0,
) -> Callable[[Mapping[str, Any]], Any]:  # pragma: no cover - network boundary
    """Build a live POST callable for the public Info API."""

    def _post(payload: Mapping[str, Any]) -> Any:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(
                url,
                json=dict(payload),
                headers={"Content-Type": "application/json"},
            )
        response.raise_for_status()
        return response.json()

    return _post


def _asset_name(asset: object) -> str:
    if not isinstance(asset, Mapping) or "name" not in asset:
        raise ValueError("universe assets must be objects with a name")
    return str(asset["name"])
