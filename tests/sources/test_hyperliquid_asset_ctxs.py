from __future__ import annotations

import pytest

from marketimmune.sources.hyperliquid_asset_ctxs import AssetCtx, asset_ctxs_key, parse_asset_ctxs_csv

ARCHIVE_CSV = (
    "time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px\n"
    "2023-09-16T00:00:00Z,SOL,0.00001,50173,19.0,2387765.9,-0.0002,19.10,19.11,19.105,19.09,19.12\n"
    "2023-09-16T00:00:00.123456789Z,DEAD,0.0,0.0,1.0,0.0,,2.0,2.5,,,\n"
)


def test_asset_ctxs_key() -> None:
    assert asset_ctxs_key("20230916") == "asset_ctxs/20230916.csv.lz4"


def test_parse_archive_csv() -> None:
    sol, dead = parse_asset_ctxs_csv(ARCHIVE_CSV)
    assert sol == AssetCtx("SOL", 0.00001, 50173.0, oracle_px=19.10, mark_px=19.11, mid_px=19.105, premium=-0.0002, ts_ms=1_694_822_400_000)
    # No two-sided book: mid falls back to mark, premium to zero.
    assert (dead.mid_px, dead.premium, dead.ts_ms) == (2.5, 0.0, 1_694_822_400_123)


def test_parse_rejects_naive_time() -> None:
    with pytest.raises(AssertionError, match="time zone"):
        parse_asset_ctxs_csv(ARCHIVE_CSV.replace("2023-09-16T00:00:00Z", "2023-09-16T00:00:00"))


def test_basis_bps() -> None:
    ctx = AssetCtx("BTC", 0.0, 1.0, oracle_px=100.0, mark_px=100.5, mid_px=100.4, premium=0.0, ts_ms=0)
    assert ctx.basis_bps == pytest.approx((100.5 - 100.0) / 100.0 * 10_000.0)
    with pytest.raises(AssertionError, match="oracle_px"):
        _ = AssetCtx("BTC", 0.0, 1.0, oracle_px=0.0, mark_px=1.0, mid_px=1.0, premium=0.0, ts_ms=0).basis_bps
