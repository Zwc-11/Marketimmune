"""Runtime scorer for promoted Hyperliquid markout CatBoost artifacts."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast


class MarkoutScorerError(RuntimeError):
    """Raised when a promoted markout artifact cannot be loaded or scored."""


class MissingFeatureError(ValueError):
    """Raised when a scoring request is missing required model features."""


class ProbabilityModel(Protocol):
    """Small protocol shared by CatBoost and test doubles."""

    def predict_proba(self, rows: Sequence[Sequence[float]]) -> Any:  # pragma: no cover
        """Return class probabilities for each row."""


@dataclass(frozen=True)
class IsotonicCalibrator:
    """Portable isotonic calibration artifact emitted by the trainer."""

    enabled: bool
    x_thresholds: tuple[float, ...]
    y_thresholds: tuple[float, ...]
    feature_columns: tuple[str, ...]
    deployment_decision_threshold: float | None

    @classmethod
    def from_path(cls, path: Path) -> IsotonicCalibrator:
        artifact = _read_json(path)
        return cls.from_mapping(artifact)

    @classmethod
    def from_mapping(cls, artifact: Mapping[str, Any]) -> IsotonicCalibrator:
        x_thresholds = tuple(float(item) for item in artifact.get("x_thresholds", ()))
        y_thresholds = tuple(float(item) for item in artifact.get("y_thresholds", ()))
        if len(x_thresholds) != len(y_thresholds):
            raise MarkoutScorerError("Isotonic calibrator threshold arrays must have equal length.")
        feature_columns = tuple(str(item) for item in artifact.get("feature_columns", ()))
        threshold = _optional_float(artifact.get("deployment_decision_threshold"))
        return cls(
            enabled=bool(artifact.get("enabled", True)),
            x_thresholds=x_thresholds,
            y_thresholds=y_thresholds,
            feature_columns=feature_columns,
            deployment_decision_threshold=threshold,
        )

    def transform_one(self, probability: float) -> float:
        """Calibrate one raw positive-class probability."""
        probability = _clamp01(probability)
        if not self.enabled or not self.x_thresholds:
            return probability
        if probability <= self.x_thresholds[0]:
            return _clamp01(self.y_thresholds[0])
        if probability >= self.x_thresholds[-1]:
            return _clamp01(self.y_thresholds[-1])

        previous_x = self.x_thresholds[0]
        previous_y = self.y_thresholds[0]
        for next_x, next_y in zip(self.x_thresholds[1:], self.y_thresholds[1:], strict=True):
            if probability <= next_x:
                weight = (probability - previous_x) / (next_x - previous_x)
                return _clamp01(previous_y + (next_y - previous_y) * weight)
            previous_x = next_x
            previous_y = next_y
        return _clamp01(self.y_thresholds[-1])  # pragma: no cover


@dataclass(frozen=True)
class MarkoutPrediction:
    """One calibrated toxicity decision from the promoted markout model."""

    raw_score: float
    calibrated_score: float
    decision_threshold: float | None
    action: str

    def as_dict(self) -> dict[str, float | str | None]:
        return {
            "raw_score": self.raw_score,
            "calibrated_score": self.calibrated_score,
            "decision_threshold": self.decision_threshold,
            "action": self.action,
        }


@dataclass(frozen=True)
class HyperliquidMarkoutScorer:
    """Load and score a promoted Hyperliquid CatBoost markout model."""

    model: ProbabilityModel
    calibrator: IsotonicCalibrator
    report: Mapping[str, Any]
    model_path: Path
    calibrator_path: Path
    report_path: Path
    model_name: str
    feature_columns: tuple[str, ...]
    decision_threshold: float | None

    @classmethod
    def load(
        cls,
        model_path: Path,
        calibrator_path: Path,
        report_path: Path,
    ) -> HyperliquidMarkoutScorer:
        model_path = model_path.resolve()
        calibrator_path = calibrator_path.resolve()
        report_path = report_path.resolve()
        _require_file(model_path, "model")
        _require_file(calibrator_path, "calibrator")
        _require_file(report_path, "report")

        report = _read_json(report_path)
        calibrator = IsotonicCalibrator.from_path(calibrator_path)
        feature_columns = _feature_columns(report, calibrator)
        model = _load_catboost_model(model_path)
        return cls(
            model=model,
            calibrator=calibrator,
            report=report,
            model_path=model_path,
            calibrator_path=calibrator_path,
            report_path=report_path,
            model_name=str(report.get("model_name") or model_path.stem),
            feature_columns=feature_columns,
            decision_threshold=_decision_threshold(report, calibrator),
        )

    def vectorize(
        self,
        features: Mapping[str, float],
        *,
        fill_missing: float | None = None,
    ) -> list[float]:
        missing = [name for name in self.feature_columns if name not in features]
        if missing and fill_missing is None:
            joined = ", ".join(missing[:5])
            suffix = "" if len(missing) <= 5 else f", +{len(missing) - 5} more"
            raise MissingFeatureError(f"Missing markout model features: {joined}{suffix}")
        if fill_missing is None:
            return [float(features[name]) for name in self.feature_columns]
        fallback = float(fill_missing)
        return [
            float(features[name]) if name in features else fallback
            for name in self.feature_columns
        ]

    def predict(
        self,
        features: Mapping[str, float],
        *,
        fill_missing: float | None = None,
    ) -> MarkoutPrediction:
        row = self.vectorize(features, fill_missing=fill_missing)
        raw_score = _positive_class_probability(self.model.predict_proba([row]))
        calibrated_score = self.calibrator.transform_one(raw_score)
        threshold = self.decision_threshold
        action = (
            "withhold_quote"
            if threshold is not None and calibrated_score >= threshold
            else "quote"
        )
        return MarkoutPrediction(
            raw_score=raw_score,
            calibrated_score=calibrated_score,
            decision_threshold=threshold,
            action=action,
        )

    def latency_ms(self, features: Mapping[str, float], *, samples: int = 128) -> dict[str, float]:
        samples = max(1, int(samples))
        values: list[float] = []
        for _ in range(samples):
            started = time.perf_counter()
            self.predict(features, fill_missing=0.0)
            values.append((time.perf_counter() - started) * 1000.0)
        return {
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
            "p99_ms": _percentile(values, 99),
            "mean_ms": sum(values) / len(values),
        }

    def zero_feature_sample(self) -> dict[str, float]:
        return {name: 0.0 for name in self.feature_columns}


def _load_catboost_model(path: Path) -> ProbabilityModel:
    try:
        catboost_module = import_module("catboost")
    except ImportError as exc:
        raise MarkoutScorerError(
            "CatBoost is not installed. Install the training extra to load promoted artifacts."
        ) from exc
    classifier_type = catboost_module.__dict__["CatBoostClassifier"]
    model = classifier_type()
    model.load_model(str(path))
    return cast(ProbabilityModel, model)


def _feature_columns(
    report: Mapping[str, Any],
    calibrator: IsotonicCalibrator,
) -> tuple[str, ...]:
    if calibrator.feature_columns:
        return calibrator.feature_columns
    columns = report.get("feature_columns", ())
    feature_columns = tuple(str(item) for item in columns)
    if not feature_columns:
        raise MarkoutScorerError("Promoted markout report does not define feature_columns.")
    return feature_columns


def _decision_threshold(
    report: Mapping[str, Any],
    calibrator: IsotonicCalibrator,
) -> float | None:
    if calibrator.deployment_decision_threshold is not None:
        return calibrator.deployment_decision_threshold
    policy = report.get("policy")
    if isinstance(policy, Mapping):
        return _optional_float(policy.get("deployment_decision_threshold"))
    return _optional_float(report.get("decision_threshold"))


def _positive_class_probability(probabilities: Any) -> float:
    try:
        row = probabilities[0]
        value = row[1] if len(row) > 1 else row[0]
    except (IndexError, KeyError, TypeError) as exc:
        raise MarkoutScorerError("Model predict_proba did not return class probabilities.") from exc
    return _clamp01(float(value))


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute percentile for an empty sequence")
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise MarkoutScorerError(f"{path} must contain a JSON object.")
    return payload


def _require_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Promoted markout {label} artifact not found: {path}")
    if not path.is_file():
        raise MarkoutScorerError(f"Promoted markout {label} path is not a file: {path}")


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
