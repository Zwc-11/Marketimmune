"""Tests for the Hyperliquid CatBoost training CLI helpers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.ingest.hyperliquid_lake import write_parquet_records
from scripts.train_hyperliquid_markout import (
    apply_isotonic_calibrator,
    evaluate_holdout_split,
    event_ofi_probabilities,
    fit_isotonic_calibrator,
    load_training_panel,
    metric_deltas,
    parse_date_spec,
    parse_symbol_spec,
    parse_threshold_grid,
    partition_row_counts,
    prepare_training_frame,
    requested_training_partitions,
    resolve_training_partitions,
    split_existing_missing_partitions,
    split_model_calibration_indices,
    training_path,
    write_isotonic_calibrator,
)


def test_training_path_points_at_gold_training_partition() -> None:
    path = training_path(Path("lake"), "sol", "20260601")

    assert path == Path(
        "lake/gold/hyperliquid/training/SOL/SOL-training-20260601.parquet"
    )


def test_parse_symbol_spec_normalizes_and_deduplicates() -> None:
    assert parse_symbol_spec("sol, SOL, btc/perp") == ("SOL", "BTC-PERP")


def test_parse_date_spec_accepts_commas_and_ranges() -> None:
    assert parse_date_spec("20260601,20260603..20260605,20260601") == (
        "20260601",
        "20260603",
        "20260604",
        "20260605",
    )


def test_parse_date_spec_rejects_bad_range() -> None:
    with pytest.raises(ValueError, match="end must be >= start"):
        parse_date_spec("20260605..20260601")


def test_parse_threshold_grid_accepts_ranges_and_lists() -> None:
    assert parse_threshold_grid("0.2:0.4:0.1") == pytest.approx((0.2, 0.3, 0.4))
    assert parse_threshold_grid("0.4,0.2,0.4") == pytest.approx((0.4, 0.2))
    with pytest.raises(ValueError, match="positive"):
        parse_threshold_grid("0.2:0.4:0")


def test_resolve_training_partitions_requires_local_files(tmp_path: Path) -> None:
    path = training_path(tmp_path, "SOL", "20260601")
    write_parquet_records(path, [_training_record(10.0)])

    partitions = resolve_training_partitions(
        tmp_path,
        coins=("SOL",),
        dates=("20260601",),
    )

    assert len(partitions) == 1
    assert partitions[0].path == path
    with pytest.raises(FileNotFoundError, match="Backfill the missing dates first"):
        resolve_training_partitions(tmp_path, coins=("SOL",), dates=("20260602",))


def test_resolve_training_partitions_can_skip_missing_when_requested(tmp_path: Path) -> None:
    existing_path = training_path(tmp_path, "SOL", "20260601")
    write_parquet_records(existing_path, [_training_record(10.0)])
    requested = requested_training_partitions(
        tmp_path,
        coins=("SOL",),
        dates=("20260601", "20260602"),
    )

    existing, missing = split_existing_missing_partitions(requested)
    partitions = resolve_training_partitions(
        tmp_path,
        coins=("SOL",),
        dates=("20260601", "20260602"),
        allow_missing=True,
    )

    assert [partition.label for partition in existing] == ["SOL:20260601"]
    assert [partition.label for partition in missing] == ["SOL:20260602"]
    assert partitions == existing


def test_resolve_training_partitions_rejects_when_all_requested_are_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError, match="no requested"):
        resolve_training_partitions(
            tmp_path,
            coins=("SOL",),
            dates=("20260601",),
            allow_missing=True,
        )


def test_load_training_panel_sorts_and_caps_across_partitions(tmp_path: Path) -> None:
    first = training_path(tmp_path, "SOL", "20260601")
    second = training_path(tmp_path, "SOL", "20250727")
    write_parquet_records(first, [_training_record(30.0), _training_record(40.0)])
    write_parquet_records(second, [_training_record(10.0), _training_record(20.0)])
    partitions = resolve_training_partitions(
        tmp_path,
        coins=("SOL",),
        dates=("20250727", "20260601"),
    )

    panel = load_training_panel(partitions, horizon="10s", max_rows=3)

    assert panel["ts_ms"].tolist() == [10.0, 20.0, 30.0]
    assert panel["partition_date"].tolist() == ["20250727", "20250727", "20260601"]
    assert partition_row_counts(panel) == [
        {"coin": "SOL", "date": "20250727", "rows": 2},
        {"coin": "SOL", "date": "20260601", "rows": 1},
    ]


def test_prepare_training_frame_defaults_missing_fee_column() -> None:
    frame = pd.DataFrame({
        "ts_ms": [3.0, 1.0],
        "px": [101.0, 99.0],
        "sz": [2.0, 1.0],
        "maker_side": [1, -1],
        "toxic_10s": [True, False],
        "markout_bps_10s": [-1.5, 0.4],
        "l2_mid": [100.0, 100.0],
        "l2_spread_bps": [2.0, 1.5],
        "l2_microprice": [100.5, 99.5],
        "l2_top_imbalance": [0.2, -0.1],
        "asset_basis_bps": [1.0, 0.5],
        "asset_funding": [0.0001, 0.0002],
        "asset_open_interest": [10_000.0, 9_000.0],
        "asset_premium": [0.001, 0.002],
    })

    prepared = prepare_training_frame(frame, horizon="10s")

    assert prepared["ts_ms"].tolist() == [1.0, 3.0]
    assert prepared["fee_bps"].tolist() == [0.0, 0.0]
    assert prepared["l2_ofi_10s"].tolist() == [0.0, 0.0]
    assert prepared["l2_microprice_offset_bps"].tolist() == pytest.approx([-50.0, 50.0])
    assert prepared["fill_vs_mid_bps"].tolist() == pytest.approx([100.0, 100.0])


def test_event_ofi_probabilities_are_maker_signed() -> None:
    frame = pd.DataFrame({
        "maker_side": [1, -1, 1, -1],
        "l2_ofi_10s": [-2.0, 2.0, 2.0, -2.0],
    })

    probabilities = event_ofi_probabilities(frame)

    assert probabilities.tolist() == pytest.approx([
        0.5 + 0.5 * 0.9640275801,
        0.5 + 0.5 * 0.9640275801,
        0.5 - 0.5 * 0.9640275801,
        0.5 - 0.5 * 0.9640275801,
    ])


def test_split_model_calibration_indices_reserves_tail_by_time() -> None:
    train_indices = (0, 1, 2, 3, 4)
    timestamps = np.asarray([50.0, 10.0, 40.0, 30.0, 20.0])

    model_indices, calibration_indices = split_model_calibration_indices(
        train_indices,
        timestamps,
        calibration_fraction=0.4,
    )

    assert model_indices == [1, 4, 3]
    assert calibration_indices == [2, 0]


def test_isotonic_calibrator_falls_back_for_single_class() -> None:
    raw = np.asarray([0.1, 0.2, 0.3])
    labels = np.asarray([0, 0, 0])

    calibrator = fit_isotonic_calibrator(raw, labels)

    assert calibrator is None
    assert apply_isotonic_calibrator(calibrator, raw).tolist() == pytest.approx(raw)


def test_isotonic_calibrator_maps_probabilities_and_writes_artifact(tmp_path: Path) -> None:
    raw = np.asarray([0.1, 0.2, 0.8, 0.9])
    labels = np.asarray([0, 0, 1, 1])
    calibrator = fit_isotonic_calibrator(raw, labels)

    calibrated = apply_isotonic_calibrator(calibrator, np.asarray([0.15, 0.85]))
    out = tmp_path / "calibrator.json"
    write_isotonic_calibrator(
        out,
        calibrator,
        metadata={"coin": "SOL", "feature_columns": ["x"]},
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert calibrated.tolist() == pytest.approx([0.0, 1.0])
    assert payload["enabled"] is True
    assert payload["method"] == "isotonic"
    assert payload["coin"] == "SOL"
    assert payload["feature_columns"] == ["x"]
    assert payload["x_thresholds"]
    assert payload["y_thresholds"]


def test_metric_deltas_compare_candidate_minus_baseline() -> None:
    deltas = metric_deltas(
        {
            "pr_auc": 0.6,
            "brier": 0.2,
            "ece": 0.1,
            "markout_lift_bps": 1.5,
            "quote_rate": 0.7,
        },
        {
            "pr_auc": 0.5,
            "brier": 0.3,
            "ece": 0.2,
            "markout_lift_bps": 0.5,
            "quote_rate": 0.6,
        },
    )

    assert deltas == pytest.approx({
        "pr_auc": 0.1,
        "brier": -0.1,
        "ece": -0.1,
        "markout_lift_bps": 1.0,
        "quote_rate": 0.1,
    })


def test_evaluate_holdout_split_writes_candidate_and_baseline_metrics() -> None:
    frame = prepare_training_frame(
        pd.DataFrame([
            _training_record(10.0, toxic=False, markout=1.0, maker_side=1, ofi=-2.0),
            _training_record(11.0, toxic=True, markout=-4.0, maker_side=1, ofi=2.0),
            _training_record(12.0, toxic=False, markout=2.0, maker_side=-1, ofi=2.0),
            _training_record(13.0, toxic=True, markout=-5.0, maker_side=-1, ofi=-2.0),
        ]),
        horizon="10s",
    )

    payload = evaluate_holdout_split(
        frame,
        horizon="10s",
        train_rows=100,
        model_name="candidate",
        raw_probabilities=np.asarray([0.1, 0.9, 0.2, 0.8]),
        probabilities=np.asarray([0.1, 0.9, 0.2, 0.8]),
        candidate_threshold=0.5,
        baseline_threshold=0.5,
    )

    assert payload["n_splits"] == 1
    assert payload["pr_auc"] == pytest.approx(1.0)
    assert payload["markout_lift_bps"] == pytest.approx(2.25)
    assert payload["baselines"]["event_ofi"]["n_splits"] == 1
    assert payload["policy"]["candidate_decision_threshold"] == pytest.approx(0.5)
    assert payload["baseline_comparison"]["event_ofi"]["markout_lift_bps"] == pytest.approx(3.0)


def _training_record(
    ts_ms: float,
    *,
    toxic: bool = True,
    markout: float = -1.5,
    maker_side: int = 1,
    ofi: float = 0.3,
) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "px": 101.0,
        "sz": 2.0,
        "maker_side": maker_side,
        "fee_bps": 0.0,
        "toxic_10s": toxic,
        "markout_bps_10s": markout,
        "l2_mid": 100.0,
        "l2_spread_bps": 2.0,
        "l2_microprice": 100.5,
        "l2_top_imbalance": 0.2,
        "l2_ofi_event": 0.1,
        "l2_ofi_1s": 0.1,
        "l2_ofi_5s": 0.2,
        "l2_ofi_10s": ofi,
        "asset_basis_bps": 1.0,
        "asset_funding": 0.0001,
        "asset_open_interest": 10_000.0,
        "asset_premium": 0.001,
    }
