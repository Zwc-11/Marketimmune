"""Tests for the promoted Hyperliquid markout runtime scorer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

import marketimmune.models.hyperliquid_markout_scorer as scorer_module
from marketimmune.models.hyperliquid_markout_scorer import (
    HyperliquidMarkoutScorer,
    IsotonicCalibrator,
    MarkoutPrediction,
    MarkoutScorerError,
    MissingFeatureError,
    _decision_threshold,
    _feature_columns,
    _percentile,
    _positive_class_probability,
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
    assert _positive_class_probability([[0.8]]) == pytest.approx(0.8)

    with pytest.raises(MarkoutScorerError, match="predict_proba"):
        _positive_class_probability([])


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
