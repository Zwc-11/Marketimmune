"""Tests for the CatBoost training CLI and its Gold partition loading."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.cli import train as trainer
from marketimmune.cli._train_data import (
    FEATURE_COLUMNS,
    TrainingPartition,
    load_training_panel,
    partition_leakage_status,
    partition_row_counts,
    prepare_training_frame,
    resolve_training_partitions,
    use_feature_set,
)
from marketimmune.cli.train import (
    apply_isotonic_calibrator,
    evaluate_holdout_split,
    event_ofi_probabilities,
    fit_isotonic_calibrator,
    metric_deltas,
    split_model_calibration_indices,
    train_oof_catboost,
    write_isotonic_calibrator,
)
from marketimmune.lake.tables import HyperliquidLakeLayout, write_parquet_records
from marketimmune.utils import DAY_MS, day_start_ms


def _training_record(
    ts_ms: float, *, toxic: bool = True, markout: float = -1.5, maker_side: int = 1, ofi: float = 0.3
) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "px": 101.0,
        "sz": 2.0,
        "maker_side": maker_side,
        "maker_fee_bps": 0.0,
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


def _gold_path(root: Path, date: str) -> Path:
    return HyperliquidLakeLayout(root).gold_training_path("SOL", date)


def test_resolve_training_partitions_requires_local_files(tmp_path: Path) -> None:
    write_parquet_records(_gold_path(tmp_path, "20260601"), [_training_record(10.0)])
    (partition,) = resolve_training_partitions(tmp_path, coins=("SOL",), dates=("20260601",))
    assert partition == TrainingPartition("SOL", "20260601", _gold_path(tmp_path, "20260601"))
    with pytest.raises(FileNotFoundError, match="SOL:20260602"):
        resolve_training_partitions(tmp_path, coins=("SOL",), dates=("20260601", "20260602"))


def test_load_training_panel_sorts_across_partitions(tmp_path: Path) -> None:
    write_parquet_records(_gold_path(tmp_path, "20260601"), [_training_record(30.0), _training_record(40.0)])
    write_parquet_records(_gold_path(tmp_path, "20250727"), [_training_record(20.0), _training_record(10.0)])
    partitions = resolve_training_partitions(tmp_path, coins=("SOL",), dates=("20250727", "20260601"))
    panel = load_training_panel(partitions, horizon="10s")
    assert panel["ts_ms"].tolist() == [10.0, 20.0, 30.0, 40.0]
    assert panel["partition_date"].tolist() == ["20250727", "20250727", "20260601", "20260601"]
    assert partition_row_counts(panel) == [{"coin": "SOL", "date": "20250727", "rows": 2}, {"coin": "SOL", "date": "20260601", "rows": 2}]


def test_prepare_training_frame_fills_fees_and_ofi_and_drops_bad_rows() -> None:
    records = [_training_record(3.0), _training_record(1.0), _training_record(2.0, markout=float("nan")), _training_record(4.0)]
    frame = pd.DataFrame(records).drop(columns=["maker_fee_bps", "l2_ofi_event", "l2_ofi_1s", "l2_ofi_5s", "l2_ofi_10s"])
    frame.loc[3, "l2_spread_bps"] = float("inf")
    prepared = prepare_training_frame(frame, horizon="10s")
    assert prepared["ts_ms"].tolist() == [1.0, 3.0]
    assert prepared["maker_fee_bps"].tolist() == prepared["l2_ofi_10s"].tolist() == [0.0, 0.0]
    assert prepared["l2_microprice_offset_bps"].tolist() == pytest.approx([50.0, 50.0])
    assert prepared["toxic_10s"].dtype == bool


def test_event_ofi_probabilities_are_maker_signed() -> None:
    frame = pd.DataFrame({"maker_side": [1, -1, 1, -1], "l2_ofi_10s": [-2.0, 2.0, 2.0, -2.0]})
    high, low = 0.5 + 0.5 * np.tanh(2.0), 0.5 - 0.5 * np.tanh(2.0)
    assert event_ofi_probabilities(frame).tolist() == pytest.approx([high, high, low, low])


def test_split_model_calibration_indices_reserves_tail_by_time() -> None:
    model, calibration = split_model_calibration_indices(
        (0, 1, 2, 3, 4), np.asarray([50.0, 10.0, 40.0, 30.0, 20.0]), calibration_fraction=0.4
    )
    assert (model.tolist(), calibration.tolist()) == ([1, 4, 3], [2, 0])
    model, calibration = split_model_calibration_indices((0, 1, 2), np.asarray([1.0, 2.0, 3.0]), calibration_fraction=0.0)
    assert (model.tolist(), calibration.size) == ([0, 1, 2], 0)


def test_isotonic_calibrator_needs_both_classes_and_writes_artifact(tmp_path: Path) -> None:
    raw = np.asarray([0.1, 0.2, 0.3])
    assert fit_isotonic_calibrator(raw, np.asarray([0, 0, 0])) is None
    assert apply_isotonic_calibrator(None, raw).tolist() == pytest.approx(raw)
    calibrator = fit_isotonic_calibrator(np.asarray([0.1, 0.2, 0.8, 0.9]), np.asarray([0, 0, 1, 1]))
    assert apply_isotonic_calibrator(calibrator, np.asarray([0.15, 0.85])).tolist() == pytest.approx([0.0, 1.0])
    out = tmp_path / "calibrator.json"
    write_isotonic_calibrator(out, calibrator, metadata={"coin": "SOL", "feature_columns": ["x"]})
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert (payload["method"], payload["enabled"], payload["coin"], payload["feature_columns"]) == ("isotonic", True, "SOL", ["x"])
    assert payload["x_thresholds"] and payload["y_thresholds"]


def test_metric_deltas_compare_candidate_minus_baseline() -> None:
    candidate = {"pr_auc": 0.6, "brier": 0.2, "ece": 0.1, "markout_lift_bps": 1.5, "quote_rate": 0.7}
    baseline = {"pr_auc": 0.5, "brier": 0.3, "ece": 0.2, "markout_lift_bps": 0.5, "quote_rate": 0.6}
    assert metric_deltas(candidate, baseline) == pytest.approx(
        {"pr_auc": 0.1, "brier": -0.1, "ece": -0.1, "markout_lift_bps": 1.0, "quote_rate": 0.1}
    )


def test_evaluate_holdout_split_writes_candidate_and_baseline_metrics() -> None:
    records = [
        _training_record(10.0, toxic=False, markout=1.0, maker_side=1, ofi=-2.0),
        _training_record(11.0, toxic=True, markout=-4.0, maker_side=1, ofi=2.0),
        _training_record(12.0, toxic=False, markout=2.0, maker_side=-1, ofi=2.0),
        _training_record(13.0, toxic=True, markout=-5.0, maker_side=-1, ofi=-2.0),
    ]
    frame = prepare_training_frame(pd.DataFrame(records), horizon="10s").assign(partition_coin="SOL", partition_date="20260601")
    probs = np.asarray([0.1, 0.9, 0.2, 0.8])
    payload = evaluate_holdout_split(
        frame,
        horizon="10s",
        train_rows=100,
        model_name="candidate",
        raw_probabilities=probs,
        probabilities=probs,
        candidate_threshold=0.5,
        baseline_threshold=0.5,
    )
    assert payload["n_splits"] == payload["baselines"]["event_ofi"]["n_splits"] == 1
    assert payload["pr_auc"] == pytest.approx(1.0)
    assert payload["markout_lift_bps"] == pytest.approx(2.25)
    assert payload["policy"]["candidate_decision_threshold"] == pytest.approx(0.5)
    assert payload["baseline_comparison"]["event_ofi"]["markout_lift_bps"] == pytest.approx(3.0)
    assert payload["partition_rows"] == [{"coin": "SOL", "date": "20260601", "rows": 4}]


class _StubClassifier:
    """Stands in for CatBoost: risk from the maker side alone."""

    def __init__(self, **_kwargs: object) -> None:
        pass

    def fit(self, _pool: object) -> None:
        pass

    def predict_proba(self, rows: np.ndarray) -> np.ndarray:
        risk = np.where(rows[:, FEATURE_COLUMNS.index("maker_side")] > 0, 0.8, 0.2)
        return np.column_stack((1 - risk, risk))

    def save_model(self, path: str) -> None:
        Path(path).write_text("stub model", encoding="utf-8")


@pytest.mark.parametrize("skip_first", [False, True])
def test_cli_writes_report_oof_model_and_calibrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip_first: bool) -> None:
    # Only CatBoost's fitting is replaced: the folds, OOF, thresholds, baseline, holdout and
    # every artifact come from the real pipeline.
    monkeypatch.setattr(trainer, "CatBoostClassifier", _StubClassifier)
    monkeypatch.setattr(trainer, "Pool", lambda x, y, **_kwargs: (x, y))
    dates = ("20251201", "20251202", "20251203", "20251204", "20251205")
    for day, date in enumerate(dates):
        start = day_start_ms(date)
        records = [
            _training_record(
                float(start + i * 60_000),
                toxic=bool(i % 2) and not (skip_first and day < 2),
                maker_side=1 if i % 2 else -1,
                markout=-4.0 if i % 2 else 1.0,
            )
            for i in range(40)
        ]
        write_parquet_records(_gold_path(tmp_path, date), records)
    (_gold_path(tmp_path, "20251201").with_suffix(".leakage.json")).write_text(json.dumps({"passed": True}))
    report_path, model_path = tmp_path / "report.json", tmp_path / "model.cbm"
    argv = ["--lake-root", str(tmp_path), "--dates", "20251201..20251204", "--holdout-date", "20251205", "--train-days", "2"]
    assert trainer.main([*argv, "--report", str(report_path), "--model-out", str(model_path)]) == 0

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    trained = [fold for fold in payload["fold_training"] if "skipped" not in fold]
    assert [fold["fold_id"] for fold in payload["fold_training"]] == [1, 2]  # days 3 and 4
    assert len(trained) == (1 if skip_first else 2)
    assert payload["oof_rows"] == sum(fold["n_test"] for fold in trained)
    assert payload["leakage_safe"] is False  # only one partition has a passing check
    for report in (payload, payload["uncalibrated"], payload["baselines"]["event_ofi"]):
        assert report["cv_scheme"] == "rolling_daily"
        assert report["n_evaluated"] == payload["oof_rows"]
        assert [fold["fold_id"] for fold in report["folds"]] == [fold["fold_id"] for fold in trained]
        assert [fold["n_train"] for fold in report["folds"]] == [fold["n_train"] for fold in trained]
    summaries = payload["policy"]["candidate_threshold_folds"]
    assert [fold["fold_id"] for fold in summaries] == [fold["fold_id"] for fold in trained]
    if not skip_first:  # the first tested day has no earlier OOF rows to tune on
        assert summaries[0]["fallback"] and summaries[0]["threshold"] == 0.5
    assert payload["holdout_split"]["n_rows"] == 40 and payload["holdout_split"]["dates"] == ["20251205"]
    assert payload["partition_rows"] == [{"coin": "SOL", "date": f"2025120{d}", "rows": 40} for d in (3, 4)][2 - len(trained) :]

    oof = pq.read_table(payload["oof_predictions"])
    assert oof.num_rows == payload["oof_rows"]
    assert oof.column_names == [
        "ts_ms",
        "partition_coin",
        "partition_date",
        "px",
        "sz",
        "maker_side",
        "label",
        "markout_bps",
        "prob",
        "raw_prob",
        "baseline_prob",
    ]
    assert oof.schema.metadata == {b"feature_set": b"l0", b"horizon": b"10s"}
    calibrator = json.loads(model_path.with_suffix(".isotonic.json").read_text(encoding="utf-8"))
    assert calibrator["feature_columns"] == FEATURE_COLUMNS
    assert calibrator["deployment_decision_threshold"] == payload["policy"]["deployment_decision_threshold"]
    assert model_path.read_text(encoding="utf-8") == "stub model"


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
    parts = tuple(TrainingPartition("SOL", d, tmp_path / f"SOL-training-{d}.parquet") for d in ("20251201", "20251202"))
    for part in parts:
        pq.write_table(pa.table({"ts_ms": [2.0], "feature_ts_ms": [1.0]}), part.path)
    ok, details = partition_leakage_status(parts)
    assert ok is False and details[0]["reason"] == "no leakage report"
    parts[0].path.with_suffix(".leakage.json").write_text(json.dumps({"passed": True, "n_checked": 5}))
    parts[1].path.with_suffix(".leakage.json").write_text(json.dumps({"passed": False}))
    ok, details = partition_leakage_status(parts)
    assert ok is False and details[0]["passed"] is True and details[0]["n_checked"] == 5
    parts[1].path.with_suffix(".leakage.json").write_text(json.dumps({"passed": True}))
    assert partition_leakage_status(parts)[0] is True
    assert partition_leakage_status(())[0] is False


def test_train_oof_catboost_rolling_daily_and_tail_calibrator() -> None:
    rng = np.random.default_rng(0)
    n_days, per_day = 4, 120
    ts = np.repeat(np.arange(n_days), per_day) * float(DAY_MS) + np.tile(np.linspace(0, 86_000_000, per_day), n_days)
    frame = pd.DataFrame({column: rng.normal(size=ts.size) for column in FEATURE_COLUMNS})
    frame["maker_side"] = rng.choice([-1.0, 1.0], size=ts.size)
    frame["ts_ms"] = ts
    frame["toxic_10s"] = (frame["l2_ofi_10s"] * -frame["maker_side"] + rng.normal(scale=0.5, size=ts.size)) > 0
    result = train_oof_catboost(frame, horizon="10s", purge_ms=60_000.0, train_days=2, iterations=20, learning_rate=0.2, depth=3, seed=1)
    tested = ~np.isnan(result.probabilities)
    # days 0-1 are training-only; days 2-3 are each tested once
    assert tested.sum() == 2 * per_day and not tested[: 2 * per_day].any()
    assert [f["n_train"] for f in result.fold_summaries] == [2 * per_day, 2 * per_day]
    assert [f["n_calibration"] for f in result.fold_summaries] == [48, 48]
    assert result.calibrator is not None


def test_a_forward_holdout_is_disjoint_and_later() -> None:
    # Audit B04: the same partition, or an earlier one, must not pass as a forward holdout.
    from marketimmune.cli.train import check_forward_holdout

    check_forward_holdout(("20260527", "20260528"), ("20260601",))
    with pytest.raises(ValueError, match="also training"):
        check_forward_holdout(("20260601",), ("20260601",))
    with pytest.raises(ValueError, match="not after"):
        check_forward_holdout(("20260527", "20260601"), ("20260530",))


def test_holdout_rows_wait_for_the_last_training_label() -> None:
    from marketimmune.cli.train import label_gap_ms, purge_holdout_gap

    gap = label_gap_ms("10s")
    assert gap == 40_000.0  # 10 s horizon plus the label's 30 s lag bound
    train = pd.DataFrame({"ts_ms": [0.0, 100_000.0]})
    holdout = pd.DataFrame({"ts_ms": [120_000.0, 140_000.0, 150_000.0]})
    kept, dropped = purge_holdout_gap(train, holdout, gap)
    assert dropped == 2 and kept["ts_ms"].tolist() == [150_000.0]


def test_training_refuses_features_stamped_after_their_fill(tmp_path: Path) -> None:
    # Audit B05: a Gold row whose features are from after its fill must not train a model.
    from marketimmune.cli._train_data import check_feature_times

    good = pd.DataFrame({"ts_ms": [10.0, 20.0], "feature_ts_ms": [9.0, 19.0]})
    check_feature_times(good, tmp_path / "x.parquet")
    for bad in ([9.0, 20.0], [9.0, None]):
        with pytest.raises(ValueError, match="at or after their fill"):
            check_feature_times(pd.DataFrame({"ts_ms": [10.0, 20.0], "feature_ts_ms": bad}), tmp_path / "x.parquet")
    part = TrainingPartition("SOL", "20251201", tmp_path / "SOL-training-20251201.parquet")
    pq.write_table(pa.table({"ts_ms": [2.0]}), part.path)
    part.path.with_suffix(".leakage.json").write_text(json.dumps({"passed": True, "n_checked": 5}))
    ok, details = partition_leakage_status((part,))
    assert ok is False and "feature_ts_ms" in details[0]["reason"]


def test_purge_must_cover_the_label(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="shorter than"):
        trainer.main(["--coins", "SOL", "--dates", "20260601", "--horizon", "60s", "--purge-ms", "60000", "--lake-root", str(tmp_path)])
