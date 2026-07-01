"""Tests for the live Hyperliquid dashboard service."""

from __future__ import annotations

import pytest

from dashboard.services.hyperliquid_service import (
    clear_hyperliquid_snapshot_cache,
    live_hyperliquid_candles,
    live_hyperliquid_snapshot,
)
from marketimmune.ingest.hyperliquid_api import HyperliquidInfoAPI

BOOK = {
    "coin": "BTC",
    "time": 1_700_000_000_000,
    "levels": [
        [{"px": "100.0", "sz": "2.0", "n": 1}],
        [{"px": "101.0", "sz": "3.0", "n": 2}],
    ],
}

CANDLES = [
    {
        "s": "BTC",
        "i": "1m",
        "t": 1_700_000_000_000,
        "T": 1_700_000_059_999,
        "o": "100.0",
        "h": "102.0",
        "l": "99.0",
        "c": "101.0",
        "v": "12.5",
        "n": 42,
    }
]

META_AND_CTXS = [
    {"universe": [{"name": "BTC"}]},
    [
        {
            "funding": "0.0001",
            "openInterest": "10.0",
            "oraclePx": "100.0",
            "markPx": "100.2",
            "midPx": "100.1",
            "premium": "0.0002",
        }
    ],
]


class Clock:
    def __init__(self) -> None:
        self.t = 10.0

    def __call__(self) -> float:
        current = self.t
        self.t += 0.001
        return current


def setup_function() -> None:
    clear_hyperliquid_snapshot_cache()


def test_live_snapshot_uses_api_values() -> None:
    api = HyperliquidInfoAPI(
        post=lambda payload: BOOK if payload["type"] == "l2Book" else META_AND_CTXS
    )

    snapshot = live_hyperliquid_snapshot(coin="btc-perp", api=api, now=Clock())

    assert snapshot["coin"] == "BTC"
    assert snapshot["symbol"] == "BTC-PERP"
    assert snapshot["mid"] == pytest.approx(100.5)
    assert snapshot["bid_px"] == pytest.approx(100.0)
    assert snapshot["ask_px"] == pytest.approx(101.0)
    assert snapshot["spread_bps"] == pytest.approx((1.0 / 100.5) * 10_000)
    assert snapshot["bids"] == [{"px": 100.0, "sz": 2.0, "n": 1}]
    assert snapshot["asks"] == [{"px": 101.0, "sz": 3.0, "n": 2}]
    assert snapshot["asset_context"]["basis_bps"] == pytest.approx(20.0)
    assert snapshot["cache_hit"] is False


def test_live_snapshot_cache_returns_copy() -> None:
    calls = 0

    def post(payload):
        nonlocal calls
        calls += 1
        return BOOK if payload["type"] == "l2Book" else META_AND_CTXS

    clock = Clock()
    api = HyperliquidInfoAPI(post=post)
    first = live_hyperliquid_snapshot(api=api, now=clock)
    first["mid"] = -1.0
    second = live_hyperliquid_snapshot(api=api, now=clock)

    assert calls == 2  # l2Book + metaAndAssetCtxs only once.
    assert second["mid"] == pytest.approx(100.5)
    assert second["cache_hit"] is True


def test_live_snapshot_rejects_empty_coin() -> None:
    with pytest.raises(ValueError, match="coin"):
        live_hyperliquid_snapshot(coin=" ", api=HyperliquidInfoAPI(post=lambda _payload: {}))


def test_live_candles_use_api_values() -> None:
    observed = {}

    def post(payload):
        observed.update(payload)
        return CANDLES

    series = live_hyperliquid_candles(
        api=HyperliquidInfoAPI(post=post),
        now=Clock(),
        wall_time_ms=lambda: 1_700_000_060_000,
        lookback_minutes=5,
    )

    assert observed == {
        "type": "candleSnapshot",
        "req": {
            "coin": "BTC",
            "interval": "1m",
            "startTime": 1_699_999_760_000,
            "endTime": 1_700_000_060_000,
        },
    }
    assert series["symbol"] == "BTC-PERP"
    assert series["interval"] == "1m"
    assert series["lookback_minutes"] == 5
    assert series["candles"][0]["close"] == pytest.approx(101.0)
    assert series["cache_hit"] is False


def test_live_candles_cache_returns_copy() -> None:
    calls = 0

    def post(_payload):
        nonlocal calls
        calls += 1
        return CANDLES

    clock = Clock()
    first = live_hyperliquid_candles(api=HyperliquidInfoAPI(post=post), now=clock)
    first["candles"][0]["close"] = -1.0
    second = live_hyperliquid_candles(api=HyperliquidInfoAPI(post=post), now=clock)

    assert calls == 1
    assert second["candles"][0]["close"] == pytest.approx(101.0)
    assert second["cache_hit"] is True


@pytest.mark.parametrize(
    ("interval", "lookback"),
    [("bad", 5), ("1m", 0)],
)
def test_live_candles_validate_inputs(interval: str, lookback: int) -> None:
    with pytest.raises(ValueError):
        live_hyperliquid_candles(
            interval=interval,
            lookback_minutes=lookback,
            api=HyperliquidInfoAPI(post=lambda _payload: CANDLES),
        )
