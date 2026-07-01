"""Calibration metrics for model-evaluation reports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    """One non-empty probability bin."""

    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float


def brier_score(y_true: Sequence[bool], y_prob: Sequence[float]) -> float:
    """Mean squared error between binary outcomes and predicted probabilities."""
    _validate_inputs(y_true, y_prob)
    squared_errors = (
        (float(label) - prob) ** 2 for label, prob in zip(y_true, y_prob, strict=True)
    )
    return sum(squared_errors) / len(y_true)


def calibration_bins(
    y_true: Sequence[bool],
    y_prob: Sequence[float],
    *,
    bins: int = 10,
) -> tuple[CalibrationBin, ...]:
    """Return non-empty equal-width reliability bins over ``[0, 1]``."""
    _validate_inputs(y_true, y_prob)
    if bins < 1:
        raise ValueError("bins must be >= 1")
    grouped: list[list[tuple[bool, float]]] = [[] for _ in range(bins)]
    for label, prob in zip(y_true, y_prob, strict=True):
        idx = min(bins - 1, int(prob * bins))
        grouped[idx].append((label, prob))
    out: list[CalibrationBin] = []
    for idx, values in enumerate(grouped):
        if not values:
            continue
        count = len(values)
        out.append(CalibrationBin(
            lower=idx / bins,
            upper=(idx + 1) / bins,
            count=count,
            mean_prediction=sum(prob for _label, prob in values) / count,
            observed_rate=sum(float(label) for label, _prob in values) / count,
        ))
    return tuple(out)


def expected_calibration_error(
    y_true: Sequence[bool],
    y_prob: Sequence[float],
    *,
    bins: int = 10,
) -> float:
    """Weighted average |observed rate - mean prediction| across reliability bins."""
    total = len(y_true)
    return sum(
        item.count / total * abs(item.observed_rate - item.mean_prediction)
        for item in calibration_bins(y_true, y_prob, bins=bins)
    )


def _validate_inputs(y_true: Sequence[bool], y_prob: Sequence[float]) -> None:
    if not y_true or not y_prob:
        raise ValueError("y_true and y_prob must be non-empty")
    if len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must have the same length")
    bad = [prob for prob in y_prob if prob < 0.0 or prob > 1.0]
    if bad:
        raise ValueError("probabilities must be in [0, 1]")
