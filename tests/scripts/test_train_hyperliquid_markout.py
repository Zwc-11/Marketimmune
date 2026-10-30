"""Tests for the Hyperliquid CatBoost training CLI helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from marketimmune.ingest.hyperliquid_lake import write_parquet_records
from marketimmune.models.walk_forward import CvScheme, temporal_fold_arrays
from scripts import train_hyperliquid_markout as trainer
from scripts.hyperliquid_markout_data import (
    FEATURE_COLUMNS,
    TrainingPartition,
    leakage_report_path,
    load_training_panel,
    parse_date_spec,
    parse_symbol_spec,
    parse_threshold_grid,
    partition_leakage_status,
    partition_row_counts,
    prepare_training_frame,
    requested_training_partitions,
    resolve_training_partitions,
    split_existing_missing_partitions,
    training_path,
    use_feature_set,
)
from scripts.train_hyperliquid_markout import (
    apply_isotonic_calibrator,
    evaluate_holdout_split,
    event_ofi_probabilities,
    fit_isotonic_calibrator,
    metric_deltas,
    split_model_calibration_indices,
    train_oof_catboost,
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

    assert model_indices.tolist() == [1, 4, 3]
    assert calibration_indices.tolist() == [2, 0]


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


@pytest.mark.parametrize("scheme", ["walk_forward", "purged_kfold"])
@pytest.mark.parametrize("fixed_threshold", [False, True])
@pytest.mark.parametrize("skip_first", [False, True])
def test_cli_preserves_fitted_folds_through_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scheme: CvScheme,
    fixed_threshold: bool,
    skip_first: bool,
) -> None:
    # Replace only CatBoost's external fitting boundary; exercise the real split,
    # OOF, threshold-selection, baseline, and report-writing pipeline.
    class Classifier:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def fit(self, _pool: object) -> None:
            pass

        def predict_proba(self, rows: np.ndarray) -> np.ndarray:
            risk = np.where(rows[:, 1] > 0, 0.8, 0.2)
            return np.column_stack((1 - risk, risk))

        def save_model(self, path: str) -> None:
            Path(path).write_text("stub model", encoding="utf-8")

    monkeypatch.setitem(sys.modules, "catboost", SimpleNamespace(
        CatBoostClassifier=Classifier,
        Pool=lambda x, y, **kwargs: (x, y),
    ))
    records = [
        _training_record(
            float(i * 1000),
            toxic=bool(i % 2) if not skip_first or i >= 20 else False,
            maker_side=1 if i % 2 else -1,
            markout=-4.0 if i % 2 else 1.0,
        )
        for i in range(120)
    ]
    write_parquet_records(training_path(tmp_path, "SOL", "20260601"), records)
    report_path = tmp_path / "report.json"
    argv = [
        "train_hyperliquid_markout", "--lake-root", str(tmp_path),
        "--report", str(report_path), "--model-out", str(tmp_path / "model.cbm"),
        "--n-splits", "5", "--purge-ms", "1000", "--embargo-ms", "1000",
        "--cv-scheme", scheme, "--disable-calibration",
    ]
    if fixed_threshold:
        argv.extend(["--decision-threshold", "0.5"])
    monkeypatch.setattr(sys, "argv", argv)
    assert trainer.main() == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    timestamps = [record["ts_ms"] for record in records]
    original = temporal_fold_arrays(
        timestamps, n_splits=5, purge_ms=1000, embargo_ms=1000, scheme=scheme,
    )
    trained = [fold for fold in payload["fold_training"] if "skipped" not in fold]
    expected_rows = sum(fold["n_test"] for fold in trained)
    assert payload["oof_rows"] == expected_rows
    for report in (payload, payload["uncalibrated"], payload["baselines"]["event_ofi"]):
        assert report["n_evaluated"] == expected_rows
        assert len(report["folds"]) == len(trained)
        for actual, fitted in zip(report["folds"], trained, strict=True):
            fold = original[fitted["fold_id"] - 1]
            assert actual["fold_id"] == fitted["fold_id"]
            assert actual["n_train"] == fitted["n_train"]
            assert actual["n_test"] == fitted["n_test"]
            assert actual["test_start_ms"] == fold.test_start_ms
            assert actual["test_end_ms"] == fold.test_end_ms
    if not fixed_threshold:
        for key in ("candidate_threshold_folds", "baseline_threshold_folds"):
            summaries = payload["policy"][key]
            assert [fold["fold_id"] for fold in summaries] == [f["fold_id"] for f in trained]
            assert [fold["n_test"] for fold in summaries] == [f["n_test"] for f in trained]
            if scheme == "walk_forward":
                assert summaries[0]["n_threshold_train"] == 0
                assert summaries[0]["threshold"] == pytest.approx(0.5)


def test_feature_sets_l0_is_default_and_drops_fill_vs_mid() -> None:
    try:
        assert "fill_vs_mid_bps" not in FEATURE_COLUMNS
        assert "maker_fee_bps" in FEATURE_COLUMNS
        assert "fill_vs_mid_bps" in use_feature_set("v2")
        assert "fill_vs_mid_bps" in FEATURE_COLUMNS  # same list object, swapped in place
        with pytest.raises(ValueError, match="unknown feature set"):
            use_feature_set("v9")
    finally:
        use_feature_set("l0")


def test_partition_leakage_status_requires_a_passing_report(tmp_path: Path) -> None:
    parts = tuple(
        TrainingPartition(coin="SOL", date=d, path=tmp_path / f"SOL-training-{d}.parquet")
        for d in ("20251201", "20251202")
    )
    ok, details = partition_leakage_status(parts)
    assert ok is False and details[0]["reason"] == "no leakage report"
    leakage_report_path(parts[0].path).write_text(json.dumps({"passed": True, "n_checked": 5}))
    leakage_report_path(parts[1].path).write_text("{not json")
    ok, details = partition_leakage_status(parts)
    assert ok is False and details[0]["passed"] is True
    assert "unreadable" in details[1]["reason"]
    leakage_report_path(parts[1].path).write_text(json.dumps({"passed": True}))
    assert partition_leakage_status(parts)[0] is True
    assert partition_leakage_status(())[0] is False


def test_train_oof_catboost_rolling_daily_and_tail_calibrator() -> None:
    pytest.importorskip("catboost")
    rng = np.random.default_rng(0)
    n_days, per_day = 4, 120
    ts = np.repeat(np.arange(n_days), per_day) * 86_400_000.0 + np.tile(
        np.linspace(0, 86_000_000, per_day), n_days
    )
    frame = pd.DataFrame({column: rng.normal(size=ts.size) for column in FEATURE_COLUMNS})
    frame["maker_side"] = rng.choice([-1.0, 1.0], size=ts.size)
    frame["ts_ms"] = ts
    signal = frame["l2_ofi_10s"] * -frame["maker_side"]
    frame["toxic_10s"] = (signal + rng.normal(scale=0.5, size=ts.size)) > 0
    result = train_oof_catboost(
        frame, horizon="10s", n_splits=2, purge_ms=60_000.0, embargo_ms=0.0,
        iterations=20, learning_rate=0.2, depth=3, seed=1,
        scheme="rolling_daily", train_days=2,
    )
    tested = ~np.isnan(result.probabilities)
    # days 0-1 are training-only; days 2-3 are each tested once
    assert tested.sum() == 2 * per_day and not tested[: 2 * per_day].any()
    assert [f["n_train"] for f in result.fold_summaries] == [2 * per_day, 2 * per_day]
    assert result.calibrator is not None
