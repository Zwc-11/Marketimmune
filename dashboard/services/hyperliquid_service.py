"""Live Hyperliquid market snapshot service for the dashboard API."""

from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from marketimmune.ingest.hyperliquid_api import HyperliquidInfoAPI
from marketimmune.ingest.hyperliquid_archive import L2Level
from marketimmune.ingest.hyperliquid_asset_ctxs import AssetCtx

DEFAULT_COIN = "BTC"
DEFAULT_CACHE_TTL_MS = 1_000.0
DEFAULT_CANDLE_CACHE_TTL_MS = 15_000.0
DEFAULT_CANDLE_INTERVAL = "1m"
DEFAULT_CANDLE_LOOKBACK_MINUTES = 240
DEFAULT_TIMEOUT_S = 0.8
SUPPORTED_CANDLE_INTERVALS = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CANDLE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def live_hyperliquid_snapshot(
    *,
    coin: str = DEFAULT_COIN,
    api: HyperliquidInfoAPI | None = None,
    now: Callable[[], float] = time.monotonic,
    cache_ttl_ms: float = DEFAULT_CACHE_TTL_MS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Return a current Hyperliquid snapshot, using short-lived local cache."""
    normalized = _normalize_coin(coin)
    started = now()
    cached = _CACHE.get(normalized)
    if cached is not None:
        cached_at, payload = cached
        if (started - cached_at) * 1000.0 <= cache_ttl_ms:
            out = deepcopy(payload)
            out["cache_hit"] = True
            out["elapsed_ms"] = _elapsed_ms(started, now())
            return out

    client = api or HyperliquidInfoAPI.live(timeout_s=timeout_s)
    book = client.l2_book(normalized)
    ctx = _find_context(client.meta_and_asset_ctxs(), normalized)
    features = book.features()
    best_bid = book.bids[0]
    best_ask = book.asks[0]
    payload = {
        "source": "hyperliquid public info api",
        "coin": normalized,
        "symbol": f"{normalized}-PERP",
        "ts_ms": book.ts_ms,
        "mid": features["mid"],
        "bid_px": best_bid.px,
        "bid_sz": best_bid.sz,
        "ask_px": best_ask.px,
        "ask_sz": best_ask.sz,
        "bids": _levels_payload(book.bids),
        "asks": _levels_payload(book.asks),
        "spread_bps": features["spread_bps"],
        "microprice": features["microprice"],
        "top_imbalance": features["top_imbalance"],
        "asset_context": _asset_context_payload(ctx),
        "cache_hit": False,
        "elapsed_ms": _elapsed_ms(started, now()),
    }
    _CACHE[normalized] = (now(), deepcopy(payload))
    return payload


def live_hyperliquid_candles(
    *,
    coin: str = DEFAULT_COIN,
    interval: str = DEFAULT_CANDLE_INTERVAL,
    lookback_minutes: int = DEFAULT_CANDLE_LOOKBACK_MINUTES,
    api: HyperliquidInfoAPI | None = None,
    now: Callable[[], float] = time.monotonic,
    wall_time_ms: Callable[[], int] = lambda: int(time.time() * 1000),
    cache_ttl_ms: float = DEFAULT_CANDLE_CACHE_TTL_MS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Return recent Hyperliquid candles, using a short process cache."""
    normalized = _normalize_coin(coin)
    candle_interval = _normalize_interval(interval)
    if lookback_minutes <= 0:
        raise ValueError("lookback_minutes must be positive")

    cache_key = f"{normalized}:{candle_interval}:{lookback_minutes}"
    started = now()
    cached = _CANDLE_CACHE.get(cache_key)
    if cached is not None:
        cached_at, payload = cached
        if (started - cached_at) * 1000.0 <= cache_ttl_ms:
            out = deepcopy(payload)
            out["cache_hit"] = True
            out["elapsed_ms"] = _elapsed_ms(started, now())
            return out

    end_time_ms = wall_time_ms()
    start_time_ms = end_time_ms - lookback_minutes * 60_000
    client = api or HyperliquidInfoAPI.live(timeout_s=timeout_s)
    candles = client.candles(
        coin=normalized,
        interval=candle_interval,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    payload = {
        "source": "hyperliquid public info api",
        "coin": normalized,
        "symbol": f"{normalized}-PERP",
        "interval": candle_interval,
        "lookback_minutes": lookback_minutes,
        "start_time_ms": start_time_ms,
        "end_time_ms": end_time_ms,
        "candles": [candle.to_dict() for candle in candles],
        "cache_hit": False,
        "elapsed_ms": _elapsed_ms(started, now()),
    }
    _CANDLE_CACHE[cache_key] = (now(), deepcopy(payload))
    return payload


def clear_hyperliquid_snapshot_cache() -> None:
    """Clear the process-local cache. Tests use this to stay isolated."""
    _CACHE.clear()
    _CANDLE_CACHE.clear()


def _normalize_coin(coin: str) -> str:
    value = coin.strip().upper()
    if not value:
        raise ValueError("coin must be non-empty")
    return value.removesuffix("-PERP")


def _normalize_interval(interval: str) -> str:
    value = interval.strip()
    if value not in SUPPORTED_CANDLE_INTERVALS:
        raise ValueError("unsupported candle interval")
    return value


def _levels_payload(levels: tuple[L2Level, ...]) -> list[dict[str, float | int]]:
    return [{"px": level.px, "sz": level.sz, "n": level.n} for level in levels[:20]]


def _find_context(contexts: list[AssetCtx], coin: str) -> AssetCtx | None:
    return next((ctx for ctx in contexts if ctx.coin.upper() == coin), None)


def _asset_context_payload(ctx: AssetCtx | None) -> dict[str, float] | None:
    if ctx is None:
        return None
    return {
        "funding": ctx.funding,
        "open_interest": ctx.open_interest,
        "oracle_px": ctx.oracle_px,
        "mark_px": ctx.mark_px,
        "mid_px": ctx.mid_px,
        "premium": ctx.premium,
        "basis_bps": ctx.basis_bps,
    }


def _elapsed_ms(started: float, finished: float) -> float:
    return round((finished - started) * 1000.0, 3)
