"""Tests for the promoted Hyperliquid markout runtime scorer."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

import marketimmune.serving.scorer as scorer_module
from marketimmune.serving.scorer import (
    HyperliquidMarkoutScorer,
    IsotonicCalibrator,
    MarkoutPrediction,
    MarkoutScorerError,
    MissingFeatureError,
    _decision_threshold,
    _feature_columns,
    _percentile,
    _positive_class_probabilities,
    _read_json,
    _require_file,
)


class FakeProbabilityModel:
    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.rows: list[list[float]] = []

    def predict_proba(self, rows: Sequence[Sequence[float]]) -> list[list[float]]:
        self.rows.extend([list(row) for row in rows])
        return [[1.0 - self.probability, self.probability] for _ in rows]


class FakeCatBoostModel:
    loaded_path: str | None = None

    def load_model(self, path: str) -> None:
        self.loaded_path = path

    def predict_proba(self, rows: Sequence[Sequence[float]]) -> list[list[float]]:
        return [[0.35, 0.65] for _ in rows]


class FakeCatBoostModule:
    CatBoostClassifier = FakeCatBoostModel


def scorer(probability: float = 0.5) -> HyperliquidMarkoutScorer:
    calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(0.0, 0.5, 1.0),
        y_thresholds=(0.0, 0.4, 1.0),
        feature_columns=("maker_side", "l2_ofi_10s"),
        deployment_decision_threshold=0.55,
    )
    return HyperliquidMarkoutScorer(
        model=FakeProbabilityModel(probability),
        calibrator=calibrator,
        report={"model_name": "catboost_markout_SOL_10s"},
        model_path=Path(__file__),
        calibrator_path=Path(__file__),
        report_path=Path(__file__),
        model_name="catboost_markout_SOL_10s",
        feature_columns=calibrator.feature_columns,
        decision_threshold=calibrator.deployment_decision_threshold,
    )


def test_calibrator_interpolates_and_clamps() -> None:
    calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(0.0, 0.5, 1.0),
        y_thresholds=(0.1, 0.4, 0.9),
        feature_columns=("x",),
        deployment_decision_threshold=None,
    )

    assert calibrator.transform_one(-1.0) == pytest.approx(0.1)
    assert calibrator.transform_one(0.25) == pytest.approx(0.25)
    assert calibrator.transform_one(1.5) == pytest.approx(0.9)


def test_calibrator_can_be_disabled_or_built_from_file(tmp_path: Path) -> None:
    artifact = {
        "enabled": False,
        "x_thresholds": [0.0, 1.0],
        "y_thresholds": [0.2, 0.8],
        "feature_columns": ["maker_side"],
        "deployment_decision_threshold": "0.4",
    }
    path = tmp_path / "calibrator.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    calibrator = IsotonicCalibrator.from_path(path)

    assert calibrator.transform_one(0.7) == pytest.approx(0.7)
    assert calibrator.deployment_decision_threshold == pytest.approx(0.4)


def test_calibrator_rejects_mismatched_threshold_arrays() -> None:
    with pytest.raises(MarkoutScorerError, match="equal length"):
        IsotonicCalibrator.from_mapping(
            {
                "x_thresholds": [0.0],
                "y_thresholds": [0.0, 1.0],
            }
        )


def test_predict_vectorizes_features_in_artifact_order() -> None:
    runtime = scorer(probability=0.75)

    prediction = runtime.predict({"l2_ofi_10s": 4.0, "maker_side": -1.0})

    assert prediction.raw_score == pytest.approx(0.75)
    assert prediction.calibrated_score == pytest.approx(0.7)
    assert prediction.action == "withhold_quote"
    fake_model = runtime.model
    assert isinstance(fake_model, FakeProbabilityModel)
    assert fake_model.rows == [[-1.0, 4.0]]


def test_prediction_serializes_for_api_payloads() -> None:
    prediction = MarkoutPrediction(
        raw_score=0.6,
        calibrated_score=0.55,
        decision_threshold=0.5,
        action="withhold_quote",
    )

    assert prediction.as_dict() == {
        "raw_score": 0.6,
        "calibrated_score": 0.55,
        "decision_threshold": 0.5,
        "action": "withhold_quote",
    }


def test_predict_requires_feature_completeness_by_default() -> None:
    runtime = scorer(probability=0.25)

    with pytest.raises(MissingFeatureError, match="l2_ofi_10s"):
        runtime.predict({"maker_side": 1.0})


def test_predict_can_fill_missing_features_for_smoke_checks() -> None:
    runtime = scorer(probability=0.25)

    prediction = runtime.predict({"maker_side": 1.0}, fill_missing=0.0)

    assert prediction.action == "quote"
    fake_model = runtime.model
    assert isinstance(fake_model, FakeProbabilityModel)
    assert fake_model.rows == [[1.0, 0.0]]


def test_latency_summary_uses_the_runtime_predict_path() -> None:
    runtime = scorer(probability=0.25)

    summary = runtime.latency_ms(runtime.zero_feature_sample(), samples=3)

    assert summary["p50_ms"] >= 0.0
    assert summary["p95_ms"] >= summary["p50_ms"]


def test_latency_summary_clamps_sample_count() -> None:
    runtime = scorer(probability=0.25)

    summary = runtime.latency_ms(runtime.zero_feature_sample(), samples=0)

    assert summary["mean_ms"] >= 0.0


def test_load_builds_runtime_from_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.cbm"
    calibrator_path = tmp_path / "model.isotonic.json"
    report_path = tmp_path / "report.json"
    model_path.write_text("model", encoding="utf-8")
    calibrator_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "x_thresholds": [0.0, 1.0],
                "y_thresholds": [0.0, 1.0],
                "feature_columns": ["maker_side", "l2_ofi_10s"],
                "deployment_decision_threshold": 0.6,
            }
        ),
        encoding="utf-8",
    )
    report_path.write_text(json.dumps({"model_name": "candidate"}), encoding="utf-8")
    monkeypatch.setattr(
        scorer_module,
        "import_module",
        lambda _name: FakeCatBoostModule,
    )

    runtime = HyperliquidMarkoutScorer.load(model_path, calibrator_path, report_path)
    prediction = runtime.predict({"maker_side": 1.0, "l2_ofi_10s": 2.0})

    assert runtime.model_name == "candidate"
    assert runtime.decision_threshold == pytest.approx(0.6)
    assert prediction.raw_score == pytest.approx(0.65)
    assert prediction.action == "withhold_quote"


def test_load_uses_report_features_and_policy_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = tmp_path / "model.cbm"
    calibrator_path = tmp_path / "model.isotonic.json"
    report_path = tmp_path / "report.json"
    model_path.write_text("model", encoding="utf-8")
    calibrator_path.write_text(
        json.dumps({"enabled": True, "x_thresholds": [], "y_thresholds": []}),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(
            {
                "feature_columns": ["maker_side"],
                "policy": {"deployment_decision_threshold": 0.7},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        scorer_module,
        "import_module",
        lambda _name: FakeCatBoostModule,
    )

    runtime = HyperliquidMarkoutScorer.load(model_path, calibrator_path, report_path)

    assert runtime.model_name == "model"
    assert runtime.feature_columns == ("maker_side",)
    assert runtime.decision_threshold == pytest.approx(0.7)


def test_load_reports_missing_catboost_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "model.cbm"
    path.write_text("model", encoding="utf-8")

    def missing_module(_name: str) -> object:
        raise ImportError("missing")

    monkeypatch.setattr(scorer_module, "import_module", missing_module)

    with pytest.raises(MarkoutScorerError, match="CatBoost is not installed"):
        scorer_module._load_catboost_model(path)


def test_feature_columns_require_report_or_calibrator_columns() -> None:
    empty_calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(),
        y_thresholds=(),
        feature_columns=(),
        deployment_decision_threshold=None,
    )

    assert _feature_columns({"feature_columns": ["x"]}, empty_calibrator) == ("x",)
    with pytest.raises(MarkoutScorerError, match="feature_columns"):
        _feature_columns({}, empty_calibrator)


def test_decision_threshold_can_fall_back_to_report_field() -> None:
    empty_calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(),
        y_thresholds=(),
        feature_columns=("x",),
        deployment_decision_threshold=None,
    )

    assert _decision_threshold({"decision_threshold": "0.2"}, empty_calibrator) == pytest.approx(
        0.2
    )
    assert _decision_threshold({}, empty_calibrator) is None


def test_probability_parser_accepts_single_column_and_rejects_bad_shape() -> None:
    assert _positive_class_probabilities([[0.8]], 1) == pytest.approx([0.8])

    with pytest.raises(MarkoutScorerError, match="predict_proba"):
        _positive_class_probabilities([], 1)
    with pytest.raises(MarkoutScorerError, match="predict_proba"):
        _positive_class_probabilities([[]], 1)


def test_percentile_helpers_cover_edge_cases() -> None:
    assert _percentile([3.0], 95) == pytest.approx(3.0)
    assert _percentile([1.0, 3.0], 50) == pytest.approx(2.0)
    with pytest.raises(ValueError, match="empty"):
        _percentile([], 50)


def test_json_and_file_guards(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        _require_file(missing, "report")

    directory = tmp_path / "dir"
    directory.mkdir()
    with pytest.raises(MarkoutScorerError, match="not a file"):
        _require_file(directory, "report")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("[]", encoding="utf-8")
    with pytest.raises(MarkoutScorerError, match="JSON object"):
        _read_json(bad_json)


def _linear_scan_reference(calibrator: IsotonicCalibrator, probability: float) -> float:
    xs, ys = calibrator.x_thresholds, calibrator.y_thresholds
    probability = min(1.0, max(0.0, probability))
    if probability <= xs[0]:
        return ys[0]
    if probability >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if probability <= xs[i]:
            weight = (probability - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + (ys[i] - ys[i - 1]) * weight
    raise AssertionError("unreachable")


def test_isotonic_binary_search_matches_linear_scan() -> None:
    calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(0.0, 0.1, 0.1, 0.35, 0.5, 0.8, 1.0),
        y_thresholds=(0.0, 0.05, 0.2, 0.3, 0.45, 0.7, 0.95),
        feature_columns=("a",),
        deployment_decision_threshold=0.4,
    )
    probes = [i / 200 for i in range(201)] + [0.1, 0.35, 0.5000001]
    for probe in probes:
        assert calibrator.transform_one(probe) == pytest.approx(
            _linear_scan_reference(calibrator, probe), abs=0.0
        )
    assert calibrator.transform(probes) == [calibrator.transform_one(p) for p in probes]


class RowDependentModel:
    """Score depends only on the row, so batching must not change it."""

    def predict_proba(self, rows: Sequence[Sequence[float]]) -> list[list[float]]:
        out = []
        for row in rows:
            score = (sum(row) % 1.0) * 0.9 + 0.05
            out.append([1.0 - score, score])
        return out


def test_predict_batch_is_batch_invariant() -> None:
    base = scorer()
    batch_scorer = HyperliquidMarkoutScorer(
        model=RowDependentModel(),
        calibrator=base.calibrator,
        report=base.report,
        model_path=base.model_path,
        calibrator_path=base.calibrator_path,
        report_path=base.report_path,
        model_name=base.model_name,
        feature_columns=base.feature_columns,
        decision_threshold=base.decision_threshold,
    )
    rows = [
        {name: (i * 0.37 + j * 0.11) for j, name in enumerate(base.feature_columns)}
        for i in range(25)
    ]
    singles = [batch_scorer.predict(row) for row in rows]
    assert batch_scorer.predict_batch(rows) == singles
    assert batch_scorer.predict_batch(rows[7:19]) == singles[7:19]
    assert batch_scorer.predict_batch([]) == []


def test_predict_batch_is_batch_invariant_with_real_catboost() -> None:
    catboost = pytest.importorskip("catboost")
    import numpy as np

    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, 3))
    y = (x[:, 0] + rng.normal(size=400) > 0).astype(int)
    model = catboost.CatBoostClassifier(
        iterations=20, depth=3, verbose=False, random_seed=1, allow_writing_files=False
    )
    model.fit(x, y)
    base = scorer()
    real = HyperliquidMarkoutScorer(
        model=model,
        calibrator=IsotonicCalibrator(
            enabled=True,
            x_thresholds=(0.0, 0.5, 1.0),
            y_thresholds=(0.0, 0.4, 1.0),
            feature_columns=("a", "b", "c"),
            deployment_decision_threshold=0.3,
        ),
        report=base.report,
        model_path=base.model_path,
        calibrator_path=base.calibrator_path,
        report_path=base.report_path,
        model_name="real",
        feature_columns=("a", "b", "c"),
        decision_threshold=0.3,
    )
    rows = [dict(zip(("a", "b", "c"), map(float, row), strict=True)) for row in x[:64]]
    assert real.predict_batch(rows) == [real.predict(row) for row in rows]


def test_scorer_loads_compact_json_without_catboost(tmp_path: Path) -> None:
    compact = {
        "format": "marketimmune.oblivious.v1",
        "feature_columns": ["a", "b"],
        "scale": 1.0,
        "bias": 0.0,
        "trees": [{"f": [0], "b": [0.5], "v": [-2.0, 2.0]}],
    }
    model_path = tmp_path / "markout.json"
    model_path.write_text(json.dumps(compact), encoding="utf-8")
    calibrator_path = tmp_path / "markout.isotonic.json"
    calibrator_path.write_text(
        json.dumps({"enabled": False, "feature_columns": ["a", "b"]}), encoding="utf-8"
    )
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps({"model_name": "compact", "policy": {"deployment_decision_threshold": 0.5}}),
        encoding="utf-8",
    )

    loaded = HyperliquidMarkoutScorer.load(model_path, calibrator_path, report_path)

    high = loaded.predict({"a": 1.0, "b": 0.0})
    low = loaded.predict({"a": 0.0, "b": 0.0})
    assert high.raw_score == pytest.approx(1.0 / (1.0 + math.exp(-2.0)))
    assert high.action == "withhold_quote"
    assert low.action == "quote"
