"""Tests for point-in-time Hyperliquid feature joins."""

from __future__ import annotations

import pytest

from marketimmune.features.hyperliquid_features import (
    HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    build_hyperliquid_training_rows,
    l2_rows_with_ofi,
    prepare_markout_feature_row,
    training_row_from_asof,
)
from marketimmune.labels.leakage import LeakageError

LABEL = {
    "coin": "BTC",
    "ts_ms": 2_000,
    "px": 100.0,
    "markout_bps_1s": -50.0,
    "toxic_1s": True,
}


def _l2(ts_ms: int, mid: float) -> dict[str, object]:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid_px": mid - 0.5,
        "bid_sz": 2.0,
        "ask_px": mid + 0.5,
        "ask_sz": 2.0,
        "mid": mid,
        "spread_bps": 10.0,
        "microprice": mid + 0.1,
        "top_imbalance": 0.2,
        "ofi_event": 0.0,
        "ofi_1s": 0.0,
        "ofi_5s": 0.0,
        "ofi_10s": 0.0,
    }


def test_training_row_from_asof_attaches_l2_and_asset_features() -> None:
    row = training_row_from_asof(
        LABEL,
        _l2(1_500, 100.0),
        {
            "coin": "BTC",
            "basis_bps": 3.0,
            "funding": 0.01,
            "open_interest": 10.0,
            "premium": 0.001,
        },
    )
    assert row["feature_ts_ms"] == pytest.approx(1_500.0)
    assert row["l2_mid"] == pytest.approx(100.0)
    assert row["l2_ofi_10s"] == pytest.approx(0.0)
    assert row["asset_basis_bps"] == pytest.approx(3.0)
    assert row["toxic_1s"] is True


def test_training_row_from_asof_rejects_future_l2_feature() -> None:
    with pytest.raises(LeakageError, match="look-ahead"):
        training_row_from_asof(LABEL, _l2(2_001, 100.0))


def test_training_row_from_asof_rejects_future_timed_asset_context() -> None:
    with pytest.raises(LeakageError, match="look-ahead"):
        training_row_from_asof(
            LABEL,
            _l2(1_500, 100.0),
            {"coin": "BTC", "ts_ms": 2_001, "basis_bps": 1.0},
        )


def test_build_training_rows_uses_latest_prior_l2_not_future() -> None:
    rows = build_hyperliquid_training_rows(
        [LABEL],
        [_l2(1_000, 99.0), _l2(1_900, 100.0), _l2(2_100, 200.0)],
    )
    assert len(rows) == 1
    assert rows[0]["l2_mid"] == pytest.approx(100.0)
    assert rows[0]["feature_ts_ms"] == pytest.approx(1_900.0)


def test_build_training_rows_skips_when_no_prior_l2() -> None:
    assert build_hyperliquid_training_rows([LABEL], [_l2(2_100, 200.0)]) == []


def test_build_training_rows_ignores_untimestamped_l2_rows() -> None:
    rows = build_hyperliquid_training_rows(
        [LABEL],
        [
            {"coin": "BTC", "mid": 99.0, "spread_bps": 1.0},
            _l2(1_900, 100.0),
        ],
    )

    assert len(rows) == 1
    assert rows[0]["l2_mid"] == pytest.approx(100.0)


def test_build_training_rows_uses_latest_timed_asset_context() -> None:
    rows = build_hyperliquid_training_rows(
        [LABEL],
        [_l2(1_500, 100.0)],
        [
            {"coin": "BTC", "ts_ms": 1_000, "basis_bps": 1.0},
            {"coin": "BTC", "ts_ms": 1_900, "basis_bps": 2.0},
            {"coin": "BTC", "ts_ms": 2_100, "basis_bps": 99.0},
        ],
    )
    assert rows[0]["asset_basis_bps"] == pytest.approx(2.0)
    assert rows[0]["feature_ts_ms"] == pytest.approx(1_900.0)


def test_l2_rows_with_ofi_computes_event_and_rolling_windows() -> None:
    rows = l2_rows_with_ofi([
        {
            "coin": "BTC",
            "ts_ms": 1_000,
            "bid_px": 100.0,
            "bid_sz": 10.0,
            "ask_px": 101.0,
            "ask_sz": 10.0,
        },
        {
            "coin": "BTC",
            "ts_ms": 1_500,
            "bid_px": 100.0,
            "bid_sz": 12.0,
            "ask_px": 101.0,
            "ask_sz": 8.0,
        },
        {
            "coin": "BTC",
            "ts_ms": 7_000,
            "bid_px": 99.0,
            "bid_sz": 9.0,
            "ask_px": 100.5,
            "ask_sz": 11.0,
        },
    ])

    assert rows[0]["ofi_event"] == 0.0
    assert rows[1]["ofi_event"] == pytest.approx(0.1)
    assert rows[1]["ofi_1s"] == pytest.approx(0.1)
    assert rows[2]["ofi_event"] == pytest.approx(-0.575)
    assert rows[2]["ofi_1s"] == pytest.approx(-0.575)
    assert rows[2]["ofi_10s"] == pytest.approx(-0.475)


def test_l2_rows_with_ofi_handles_zero_top_size() -> None:
    rows = l2_rows_with_ofi([
        {
            "coin": "BTC",
            "ts_ms": 1_000,
            "bid_px": 100.0,
            "bid_sz": 0.0,
            "ask_px": 101.0,
            "ask_sz": 0.0,
        },
        {
            "coin": "BTC",
            "ts_ms": 1_500,
            "bid_px": 100.0,
            "bid_sz": 0.0,
            "ask_px": 101.0,
            "ask_sz": 0.0,
        },
    ])

    assert rows[1]["ofi_event"] == pytest.approx(0.0)
    assert rows[1]["ofi_10s"] == pytest.approx(0.0)


def test_build_training_rows_indexes_large_asof_inputs() -> None:
    labels = [
        {**LABEL, "ts_ms": 2_000 + i, "px": 100.0 + i}
        for i in range(5)
    ]
    l2_rows = [_l2(1_000 + i, 100.0 + i) for i in range(2_000)]
    asset_rows = [
        {"coin": "BTC", "ts_ms": 1_000 + i, "basis_bps": float(i)}
        for i in range(2_000)
    ]

    rows = build_hyperliquid_training_rows(labels, l2_rows, asset_rows)

    assert len(rows) == 5
    assert rows[-1]["l2_mid"] == pytest.approx(1104.0)
    assert rows[-1]["asset_basis_bps"] == pytest.approx(1004.0)


def test_build_training_rows_ignores_other_coin_asset_context() -> None:
    rows = build_hyperliquid_training_rows(
        [LABEL],
        [_l2(1_500, 100.0)],
        [{"coin": "ETH", "basis_bps": 9.0}],
    )
    assert "asset_basis_bps" not in rows[0]


def test_prepare_markout_feature_row_matches_deployment_contract() -> None:
    row = {
        "px": 101.0,
        "sz": 2.0,
        "maker_side": -1,
        "l2_mid": 100.0,
        "l2_spread_bps": 2.0,
        "l2_microprice": 100.5,
        "l2_top_imbalance": 0.2,
        "l2_ofi_10s": 0.4,
        "asset_basis_bps": 1.0,
        "asset_funding": 0.0001,
        "asset_open_interest": 10_000.0,
        "asset_premium": 0.001,
    }

    features = prepare_markout_feature_row(row)

    assert tuple(features) == HYPERLIQUID_MARKOUT_FEATURE_COLUMNS
    assert features["fee_bps"] == pytest.approx(0.0)
    assert features["l2_ofi_event"] == pytest.approx(0.0)
    assert features["l2_ofi_10s"] == pytest.approx(0.4)
    assert features["l2_microprice_offset_bps"] == pytest.approx(50.0)
    assert features["fill_vs_mid_bps"] == pytest.approx(-100.0)


def test_prepare_markout_feature_row_requires_positive_mid() -> None:
    row = {
        "px": 101.0,
        "sz": 2.0,
        "maker_side": 1,
        "l2_mid": 0.0,
        "l2_spread_bps": 2.0,
        "l2_microprice": 100.5,
        "l2_top_imbalance": 0.2,
        "asset_basis_bps": 1.0,
        "asset_funding": 0.0001,
        "asset_open_interest": 10_000.0,
        "asset_premium": 0.001,
    }

    with pytest.raises(ValueError, match="l2_mid"):
        prepare_markout_feature_row(row)


def test_prepare_markout_feature_row_reports_missing_features() -> None:
    row = {
        "px": 101.0,
        "sz": 2.0,
        "maker_side": 1,
        "l2_mid": 100.0,
        "l2_spread_bps": 2.0,
        "l2_microprice": 100.5,
        "l2_top_imbalance": 0.2,
        "asset_basis_bps": 1.0,
        "asset_funding": 0.0001,
        "asset_open_interest": 10_000.0,
    }
    with pytest.raises(ValueError, match="asset_premium"):
        prepare_markout_feature_row(row)


def test_prepare_markout_feature_row_reports_large_missing_set() -> None:
    with pytest.raises(ValueError, match=r"\+"):
        prepare_markout_feature_row({"px": 101.0})
