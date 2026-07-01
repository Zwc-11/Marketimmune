"""Tests for Hyperliquid public Info API parsing."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from marketimmune.ingest.hyperliquid_api import (
    Candle,
    HyperliquidInfoAPI,
    parse_candle,
    parse_meta_and_asset_ctxs,
)

BOOK = {
    "coin": "BTC",
    "time": 1_700_000_000_000,
    "levels": [
        [{"px": "100.0", "sz": "2.0", "n": 1}],
        [{"px": "101.0", "sz": "3.0", "n": 2}],
    ],
}

CANDLE = {
    "s": "BTC",
    "i": "1m",
    "t": 1_700_000_000_000,
    "T": 1_700_000_059_999,
    "o": "100.0",
    "h": "102.0",
    "l": "99.5",
    "c": "101.0",
    "v": "12.5",
    "n": 42,
}

META_AND_CTXS = [
    {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
    [
        {
            "funding": "0.0001",
            "openInterest": "10.0",
            "oraclePx": "100.0",
            "markPx": "100.2",
            "midPx": "100.1",
            "premium": "0.0002",
        },
        {
            "funding": "-0.0002",
            "openInterest": "20.0",
            "oraclePx": "50.0",
            "markPx": "49.9",
            "midPx": "49.95",
            "premium": "-0.0001",
        },
    ],
]


def test_api_methods_build_documented_payloads() -> None:
    calls: list[dict[str, object]] = []

    def post(payload: Mapping[str, object]) -> object:
        calls.append(dict(payload))
        if payload["type"] == "allMids":
            return {"BTC": "100.5"}
        if payload["type"] == "l2Book":
            return BOOK
        if payload["type"] == "metaAndAssetCtxs":
            return META_AND_CTXS
        return [CANDLE]

    api = HyperliquidInfoAPI(post=post)

    assert api.all_mids() == {"BTC": 100.5}
    assert api.l2_book("BTC").features()["mid"] == pytest.approx(100.5)
    assert [ctx.coin for ctx in api.meta_and_asset_ctxs()] == ["BTC", "ETH"]
    candles = api.candles(coin="BTC", interval="1m", start_time_ms=1, end_time_ms=2)
    assert candles == [
        Candle(
            "BTC", "1m", 1_700_000_000_000, 1_700_000_059_999, 100.0, 102.0, 99.5,
            101.0, 12.5, 42,
        )
    ]
    assert calls == [
        {"type": "allMids"},
        {"type": "l2Book", "coin": "BTC"},
        {"type": "metaAndAssetCtxs"},
        {
            "type": "candleSnapshot",
            "req": {"coin": "BTC", "interval": "1m", "startTime": 1, "endTime": 2},
        },
    ]


def test_live_uses_http_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, float] = {}

    def fake_httpx_info_post(*, timeout_s: float):
        captured["timeout_s"] = timeout_s
        return lambda _payload: {"BTC": "100.5"}

    monkeypatch.setattr(
        "marketimmune.ingest.hyperliquid_api.httpx_info_post",
        fake_httpx_info_post,
    )

    api = HyperliquidInfoAPI.live(timeout_s=3.5)
    assert api.all_mids() == {"BTC": 100.5}
    assert captured["timeout_s"] == pytest.approx(3.5)


def test_parse_candle() -> None:
    candle = parse_candle(CANDLE)
    assert candle.to_dict()["close"] == pytest.approx(101.0)
    assert candle.trade_count == 42


def test_meta_and_asset_contexts_parses_named_contexts() -> None:
    ctxs = parse_meta_and_asset_ctxs(META_AND_CTXS)
    assert ctxs[0].coin == "BTC"
    assert ctxs[0].basis_bps == pytest.approx(20.0)
    assert ctxs[1].coin == "ETH"


def test_api_rejects_wrong_top_level_shapes() -> None:
    with pytest.raises(ValueError, match="allMids"):
        _api_with(["not", "object"]).all_mids()
    with pytest.raises(ValueError, match="l2Book"):
        _api_with(["not", "object"]).l2_book("BTC")
    with pytest.raises(ValueError, match="candleSnapshot"):
        _api_with({"not": "list"}).candles(
            coin="BTC", interval="1m", start_time_ms=1, end_time_ms=2
        )
    with pytest.raises(ValueError, match="candleSnapshot"):
        _api_with("not-list").candles(coin="BTC", interval="1m", start_time_ms=1, end_time_ms=2)


def test_meta_and_asset_contexts_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match=r"\[meta, asset_contexts\]"):
        parse_meta_and_asset_ctxs({"not": "a list"})
    with pytest.raises(ValueError, match=r"\[meta, asset_contexts\]"):
        parse_meta_and_asset_ctxs("bad")
    with pytest.raises(ValueError, match=r"\[meta, asset_contexts\]"):
        parse_meta_and_asset_ctxs([{"universe": []}])
    with pytest.raises(ValueError, match="invalid parts"):
        parse_meta_and_asset_ctxs([[], []])
    with pytest.raises(ValueError, match="meta.universe"):
        parse_meta_and_asset_ctxs([{"universe": "BTC"}, []])
    with pytest.raises(ValueError, match="lengths differ"):
        parse_meta_and_asset_ctxs([{"universe": [{"name": "BTC"}]}, []])
    with pytest.raises(ValueError, match="asset context rows"):
        parse_meta_and_asset_ctxs([{"universe": [{"name": "BTC"}]}, ["bad"]])
    with pytest.raises(ValueError, match="with a name"):
        parse_meta_and_asset_ctxs([{"universe": [{}]}, [{}]])


def _api_with(response: object) -> HyperliquidInfoAPI:
    return HyperliquidInfoAPI(post=lambda _payload: response)
