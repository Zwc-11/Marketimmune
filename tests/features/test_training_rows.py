"""Tests for point-in-time Hyperliquid feature joins."""

from __future__ import annotations

import pytest

from marketimmune.features.training_rows import (
    HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    TRAINING_ROW_FEATURE_COLUMNS,
    build_hyperliquid_training_rows,
    l2_rows_with_ofi,
    prepare_markout_feature_row,
    verify_training_rows_no_lookahead,
)

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
    rows = l2_rows_with_ofi(
        [
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
        ]
    )

    assert rows[0]["ofi_event"] == 0.0
    assert rows[1]["ofi_event"] == pytest.approx(0.1)
    assert rows[1]["ofi_1s"] == pytest.approx(0.1)
    assert rows[2]["ofi_event"] == pytest.approx(-0.575)
    assert rows[2]["ofi_1s"] == pytest.approx(-0.575)
    assert rows[2]["ofi_10s"] == pytest.approx(-0.475)


def test_l2_rows_with_ofi_handles_zero_top_size() -> None:
    rows = l2_rows_with_ofi(
        [
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
        ]
    )

    assert rows[1]["ofi_event"] == pytest.approx(0.0)
    assert rows[1]["ofi_10s"] == pytest.approx(0.0)


def test_build_training_rows_indexes_large_asof_inputs() -> None:
    labels = [{**LABEL, "ts_ms": 2_000 + i, "px": 100.0 + i} for i in range(5)]
    l2_rows = [_l2(1_000 + i, 100.0 + i) for i in range(2_000)]
    asset_rows = [{"coin": "BTC", "ts_ms": 1_000 + i, "basis_bps": float(i)} for i in range(2_000)]

    rows = build_hyperliquid_training_rows(labels, l2_rows, asset_rows)

    assert len(rows) == 5
    # Strict as-of (fix L1): the label at 2_004 sees the 2_003 rows, not 2_004's.
    assert rows[-1]["l2_mid"] == pytest.approx(1103.0)
    assert rows[-1]["asset_basis_bps"] == pytest.approx(1003.0)
    assert rows[-1]["feature_ts_ms"] < rows[-1]["ts_ms"]


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


GAP_MS = 35 * 60_000  # the 2025-12-12 Albers archive gap (17:40:43 -> 18:16:01 UTC, plus warm-up)


def _book(ts_ms: int, bid_sz: float, ask_sz: float) -> dict[str, object]:
    return {
        "coin": "BTC",
        "ts_ms": ts_ms,
        "bid_px": 100.0,
        "bid_sz": bid_sz,
        "ask_px": 101.0,
        "ask_sz": ask_sz,
        "mid": 100.5,
        "spread_bps": 99.5,
        "microprice": 100.5,
        "top_imbalance": 0.0,
    }


def _books(start: int, n: int, bid_base: float) -> list[dict[str, object]]:
    return [_book(start + 500 * i, bid_base + i % 7, 10.0 + i % 5) for i in range(n)]


def test_ofi_does_not_difference_across_a_book_reset() -> None:
    # A jump of more than 30 s resets the Silver book: the first row after it has no previous
    # book, exactly like the first row of the data, and no window reaches back over the jump.
    before, after = _books(0, 40, bid_base=10.0), _books(GAP_MS, 40, bid_base=30.0)
    joined = l2_rows_with_ofi(before + after)
    alone = l2_rows_with_ofi(after)
    names = ("ofi_event", "ofi_1s", "ofi_5s", "ofi_10s")
    assert joined[40]["ofi_event"] == joined[40]["ofi_10s"] == 0.0
    for got, want in zip(joined[40:], alone, strict=True):
        assert [got[name] for name in names] == pytest.approx([want[name] for name in names], abs=1e-12)
    # a 29 s pause is not a reset: the event still differences against the older row
    paused = l2_rows_with_ofi([_book(1_000, 10.0, 10.0), _book(30_000, 12.0, 8.0)])
    assert paused[1]["ofi_event"] == pytest.approx(0.1)


def test_no_lookahead_check_passes_just_after_a_book_reset() -> None:
    # The fill before the gap makes the check's uncut run start before the gap, as with a
    # day's sample; the cut runs after the gap only see rows from 300 s before each fill.
    labels = [{**LABEL, "ts_ms": 15_000}, *({**LABEL, "ts_ms": GAP_MS + 300 + 400 * i} for i in range(30))]
    report = verify_training_rows_no_lookahead(labels, _books(0, 40, bid_base=10.0) + _books(GAP_MS, 40, bid_base=30.0), sample=31)
    assert report.passed and report.n_checked == 31
    assert report.columns == TRAINING_ROW_FEATURE_COLUMNS


def test_training_row_columns_keep_the_gold_schema_order() -> None:
    (row,) = build_hyperliquid_training_rows([LABEL], [_l2(1_500, 100.0)], [{"coin": "BTC", "ts_ms": 1_000, "basis_bps": 1.0}])
    assert list(row)[len(LABEL) :] == ["feature_ts_ms", *(c for c in TRAINING_ROW_FEATURE_COLUMNS[1:9]), "asset_basis_bps"]
