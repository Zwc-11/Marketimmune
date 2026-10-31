"""Score fills with a promoted markout model: the CatBoost ``.cbm`` or its compact JSON trees,
then the trainer's isotonic calibrator and deployment threshold.

The maths is pinned to ``frontend/src/lib/obliviousTrees.ts`` by the parity fixture
(``marketimmune.cli.make_parity_fixtures``).
"""

from __future__ import annotations

import json
import time
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np

from marketimmune.serving.oblivious_trees import load_compact


class ProbabilityModel(Protocol):
    def predict_proba(self, rows: Sequence[Sequence[float]]) -> Any: ...


@dataclass(frozen=True)
class IsotonicCalibrator:
    """The trainer's JSON calibrator: a piecewise-linear map through the isotonic knots."""

    enabled: bool
    x_thresholds: tuple[float, ...]
    y_thresholds: tuple[float, ...]
    feature_columns: tuple[str, ...]
    deployment_decision_threshold: float | None

    @classmethod
    def from_path(cls, path: Path) -> IsotonicCalibrator:
        return cls.from_mapping(_read_json(path))

    @classmethod
    def from_mapping(cls, artifact: Mapping[str, Any]) -> IsotonicCalibrator:
        # A disabled calibrator is written without knots.
        xs = tuple(float(item) for item in artifact.get("x_thresholds", ()))
        ys = tuple(float(item) for item in artifact.get("y_thresholds", ()))
        assert len(xs) == len(ys), f"isotonic calibrator thresholds must have equal length: {len(xs)=} {len(ys)=}"
        threshold = artifact.get("deployment_decision_threshold")
        return cls(
            enabled=bool(artifact.get("enabled", True)),
            x_thresholds=xs,
            y_thresholds=ys,
            feature_columns=tuple(str(item) for item in artifact.get("feature_columns", ())),
            deployment_decision_threshold=None if threshold is None else float(threshold),
        )

    def transform_one(self, probability: float) -> float:
        """Calibrate one raw probability (binary search over the knots)."""
        probability = _clamp01(probability)
        xs, ys = self.x_thresholds, self.y_thresholds
        if not self.enabled or not xs:
            return probability
        if probability <= xs[0]:
            return _clamp01(ys[0])
        if probability >= xs[-1]:
            return _clamp01(ys[-1])
        # NOTE: the first knot with x >= p, so a repeated knot takes its left segment.
        right = bisect_left(xs, probability)
        left = right - 1
        weight = (probability - xs[left]) / (xs[right] - xs[left])
        return _clamp01(ys[left] + (ys[right] - ys[left]) * weight)


@dataclass(frozen=True)
class MarkoutPrediction:
    """One calibrated toxicity decision."""

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
    """A loaded model, its calibrator and report; scores feature dicts keyed by column name."""

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
    def load(cls, model_path: Path, calibrator_path: Path, report_path: Path) -> HyperliquidMarkoutScorer:
        model_path, calibrator_path, report_path = model_path.resolve(), calibrator_path.resolve(), report_path.resolve()
        if not model_path.is_file():
            raise FileNotFoundError(f"Promoted markout artifact not found: {model_path}")
        report = _read_json(report_path)
        calibrator = IsotonicCalibrator.from_path(calibrator_path)
        feature_columns = calibrator.feature_columns or tuple(str(item) for item in report.get("feature_columns", ()))
        assert feature_columns, f"{report_path} defines no feature_columns"
        threshold = calibrator.deployment_decision_threshold
        if threshold is None and "policy" in report:
            value = report["policy"].get("deployment_decision_threshold")
            threshold = None if value is None else float(value)
        return cls(
            model=_load_model(model_path),
            calibrator=calibrator,
            report=report,
            model_path=model_path,
            calibrator_path=calibrator_path,
            report_path=report_path,
            model_name=str(report.get("model_name") or model_path.stem),
            feature_columns=feature_columns,
            decision_threshold=threshold,
        )

    def predict(self, features: Mapping[str, float]) -> MarkoutPrediction:
        return self.predict_batch([features])[0]

    def predict_batch(self, rows: Sequence[Mapping[str, float]]) -> list[MarkoutPrediction]:
        """Score many fills in one model call.

        Batch-invariant: a fill scores the same alone or inside any batch (trees are
        evaluated per row, calibration is per row).
        """
        if not rows:
            return []
        matrix = [self._vector(features) for features in rows]
        raw_scores = [_clamp01(float(row[1])) for row in self.model.predict_proba(matrix)]
        assert len(raw_scores) == len(rows), f"{len(raw_scores)=} {len(rows)=}"
        threshold = self.decision_threshold
        predictions: list[MarkoutPrediction] = []
        for raw_score in raw_scores:
            calibrated = self.calibrator.transform_one(raw_score)
            action = "withhold_quote" if threshold is not None and calibrated >= threshold else "quote"
            predictions.append(MarkoutPrediction(raw_score, calibrated, threshold, action))
        return predictions

    def latency_ms(self, features: Mapping[str, float], *, samples: int = 128) -> dict[str, float]:
        """Wall time of single-fill ``predict`` calls."""
        values: list[float] = []
        for _ in range(max(1, samples)):
            started = time.perf_counter()
            self.predict(features)
            values.append((time.perf_counter() - started) * 1000.0)
        p50, p95, p99 = np.percentile(values, (50, 95, 99)).tolist()
        return {"p50_ms": p50, "p95_ms": p95, "p99_ms": p99, "mean_ms": sum(values) / len(values)}

    def zero_feature_sample(self) -> dict[str, float]:
        return dict.fromkeys(self.feature_columns, 0.0)

    def _vector(self, features: Mapping[str, float]) -> list[float]:
        missing = [name for name in self.feature_columns if name not in features]
        if missing:
            raise ValueError(
                f"Missing markout model features: {', '.join(missing[:5])}{f', +{len(missing) - 5} more' if len(missing) > 5 else ''}"
            )
        return [float(features[name]) for name in self.feature_columns]


def _load_model(path: Path) -> ProbabilityModel:
    """The compact JSON needs no CatBoost; a ``.cbm`` needs the training extra."""
    if path.suffix == ".json":
        return cast(ProbabilityModel, load_compact(path))
    from catboost import CatBoostClassifier

    model = CatBoostClassifier()
    model.load_model(str(path))
    return cast(ProbabilityModel, model)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Promoted markout artifact not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path} must contain a JSON object"
    return payload


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
