"""Tests for Hyperliquid asset-contexts parsing + derivatives signals (100% coverage)."""

import pytest

from marketimmune.ingest.hyperliquid_asset_ctxs import (
    AssetCtx,
    AssetCtxColumns,
    funding_rate_of_change,
    load_asset_ctxs,
    open_interest_delta,
    parse_asset_ctx_row,
    parse_asset_ctxs_csv,
)

DEFAULT_CSV = (
    "coin,funding,openInterest,oraclePx,markPx,midPx,premium\n"
    "BTC,0.0000125,688.11,100.0,100.5,100.4,0.00031774\n"
    "ETH,-0.00001,1200.0,50.0,49.9,49.95,-0.0002\n"
)

ARCHIVE_CSV = (
    "time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,"
    "oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px\n"
    "2023-09-16T00:00:00Z,SOL,0.00001,50173,19.0,2387765.9,"
    "-0.0002,19.10,19.11,19.105,19.09,19.12\n"
)


def test_parse_row_default_columns() -> None:
    ctx = parse_asset_ctx_row(
        {
            "coin": "BTC",
            "funding": "0.0000125",
            "openInterest": "688.11",
            "oraclePx": "100.0",
            "markPx": "100.5",
            "midPx": "100.4",
            "premium": "0.0003",
        }
    )
    assert ctx.coin == "BTC"
    assert ctx.open_interest == pytest.approx(688.11)


def test_parse_row_uses_mark_when_mid_px_is_null() -> None:
    ctx = parse_asset_ctx_row(
        {
            "coin": "BTC",
            "funding": "0.0000125",
            "openInterest": "688.11",
            "oraclePx": "100.0",
            "markPx": "100.5",
            "midPx": None,
            "premium": None,
        }
    )
    assert ctx.mid_px == pytest.approx(100.5)
    assert ctx.premium == 0.0


def test_parse_row_rejects_missing_required_numeric() -> None:
    with pytest.raises(ValueError, match="funding is required"):
        parse_asset_ctx_row(
            {
                "coin": "BTC",
                "funding": None,
                "openInterest": "688.11",
                "oraclePx": "100.0",
                "markPx": "100.5",
                "midPx": "100.5",
                "premium": "0.0",
            }
        )


def test_parse_row_custom_columns() -> None:
    cols = AssetCtxColumns(
        coin="symbol", funding="fr", open_interest="oi",
        oracle_px="ox", mark_px="mx", mid_px="mid", premium="prem",
    )
    ctx = parse_asset_ctx_row(
        {"symbol": "ETH", "fr": "0.0", "oi": "1.0", "ox": "50.0",
         "mx": "50.1", "mid": "50.05", "prem": "0.0"},
        columns=cols,
    )
    assert ctx.coin == "ETH"
    assert ctx.mark_px == pytest.approx(50.1)


def test_parse_csv() -> None:
    ctxs = parse_asset_ctxs_csv(DEFAULT_CSV)
    assert [c.coin for c in ctxs] == ["BTC", "ETH"]


def test_parse_csv_auto_detects_historical_archive_columns() -> None:
    ctxs = parse_asset_ctxs_csv(ARCHIVE_CSV)
    assert ctxs[0].coin == "SOL"
    assert ctxs[0].ts_ms == 1_694_822_400_000
    assert ctxs[0].open_interest == pytest.approx(50173)
    assert ctxs[0].oracle_px == pytest.approx(19.10)
    assert ctxs[0].mark_px == pytest.approx(19.11)


def test_parse_csv_respects_custom_columns_even_with_archive_headers() -> None:
    csv_text = (
        "symbol,fr,oi,ox,mx,mid,prem,open_interest,oracle_px,mark_px\n"
        "BTC,0.0,1.0,100.0,101.0,100.5,0.001,999,999,999\n"
    )
    cols = AssetCtxColumns(
        coin="symbol",
        funding="fr",
        open_interest="oi",
        oracle_px="ox",
        mark_px="mx",
        mid_px="mid",
        premium="prem",
    )

    ctxs = parse_asset_ctxs_csv(csv_text, columns=cols)

    assert ctxs[0].open_interest == pytest.approx(1.0)
    assert ctxs[0].oracle_px == pytest.approx(100.0)


def test_parse_row_accepts_numeric_timestamp() -> None:
    ctx = parse_asset_ctx_row(
        {
            "time": "1694822400000",
            "coin": "BTC",
            "funding": "0.0000125",
            "openInterest": "688.11",
            "oraclePx": "100.0",
            "markPx": "100.5",
            "midPx": "100.4",
            "premium": "0.0003",
        }
    )
    assert ctx.ts_ms == 1_694_822_400_000


def test_parse_row_accepts_fractional_timezone_timestamp() -> None:
    ctx = parse_asset_ctx_row(
        {
            "time": "2023-09-16T00:00:00.123456789+00:00",
            "coin": "BTC",
            "funding": "0.0000125",
            "openInterest": "688.11",
            "oraclePx": "100.0",
            "markPx": "100.5",
            "midPx": "100.4",
            "premium": "0.0003",
        }
    )
    assert ctx.ts_ms == 1_694_822_400_123


def test_parse_row_accepts_naive_timestamp_as_utc() -> None:
    ctx = parse_asset_ctx_row(
        {
            "time": "2023-09-16T00:00:00",
            "coin": "BTC",
            "funding": "0.0000125",
            "openInterest": "688.11",
            "oraclePx": "100.0",
            "markPx": "100.5",
            "midPx": "100.4",
            "premium": "0.0003",
        }
    )
    assert ctx.ts_ms == 1_694_822_400_000


def test_basis_bps() -> None:
    ctx = AssetCtx("BTC", 0.0, 1.0, oracle_px=100.0, mark_px=100.5, mid_px=100.4, premium=0.0)
    assert ctx.basis_bps == pytest.approx((100.5 - 100.0) / 100.0 * 10_000.0)


def test_basis_bps_rejects_nonpositive_oracle() -> None:
    ctx = AssetCtx("BTC", 0.0, 1.0, oracle_px=0.0, mark_px=1.0, mid_px=1.0, premium=0.0)
    with pytest.raises(ValueError, match="oracle_px"):
        _ = ctx.basis_bps


def test_funding_rate_of_change() -> None:
    assert funding_rate_of_change([0.1, 0.3, 0.2]) == pytest.approx([0.0, 0.2, -0.1])
    assert funding_rate_of_change([0.1]) == [0.0]  # single point -> no change


def test_open_interest_delta() -> None:
    assert open_interest_delta([100.0, 110.0]) == pytest.approx([0.0, 10.0])
    assert open_interest_delta([100.0]) == [0.0]


def test_load_asset_ctxs_with_injected_io() -> None:
    captured: dict[str, str] = {}

    def fake_fetch(key: str) -> bytes:
        captured["key"] = key
        return DEFAULT_CSV.encode("utf-8")

    ctxs = load_asset_ctxs(fake_fetch, lambda raw: raw, "20230916")
    assert captured["key"] == "asset_ctxs/20230916.csv.lz4"
    assert len(ctxs) == 2
