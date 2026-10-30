"""Calibration metrics for model-evaluation reports (vectorized)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    """One non-empty probability bin."""

    lower: float
    upper: float
    count: int
    mean_prediction: float
    observed_rate: float


def brier_score(
    y_true: Sequence[bool] | npt.ArrayLike,
    y_prob: Sequence[float] | npt.ArrayLike,
) -> float:
    """Mean squared error between binary outcomes and predicted probabilities."""
    labels, probs = _arrays(y_true, y_prob)
    return float(np.mean((labels - probs) ** 2))


def calibration_bins(
    y_true: Sequence[bool] | npt.ArrayLike,
    y_prob: Sequence[float] | npt.ArrayLike,
    *,
    bins: int = 10,
) -> tuple[CalibrationBin, ...]:
    """Return non-empty equal-width reliability bins over ``[0, 1]``."""
    labels, probs = _arrays(y_true, y_prob)
    if bins < 1:
        raise ValueError("bins must be >= 1")
    counts, prob_sums, label_sums = _bin_sums(labels, probs, bins)
    return tuple(
        CalibrationBin(
            lower=idx / bins,
            upper=(idx + 1) / bins,
            count=int(counts[idx]),
            mean_prediction=float(prob_sums[idx] / counts[idx]),
            observed_rate=float(label_sums[idx] / counts[idx]),
        )
        for idx in np.flatnonzero(counts).tolist()
    )


def expected_calibration_error(
    y_true: Sequence[bool] | npt.ArrayLike,
    y_prob: Sequence[float] | npt.ArrayLike,
    *,
    bins: int = 10,
) -> float:
    """Weighted average |observed rate - mean prediction| across reliability bins.

    Equals ``sum_b |sum(y_b) - sum(p_b)| / n``, which needs no per-bin division.
    """
    labels, probs = _arrays(y_true, y_prob)
    if bins < 1:
        raise ValueError("bins must be >= 1")
    _counts, prob_sums, label_sums = _bin_sums(labels, probs, bins)
    return float(np.abs(label_sums - prob_sums).sum() / labels.size)


def _bin_sums(
    labels: FloatArray,
    probs: FloatArray,
    bins: int,
) -> tuple[npt.NDArray[np.int64], FloatArray, FloatArray]:
    index = np.minimum((probs * bins).astype(np.int64), bins - 1)
    counts = np.bincount(index, minlength=bins)
    prob_sums = np.bincount(index, weights=probs, minlength=bins)
    label_sums = np.bincount(index, weights=labels, minlength=bins)
    return counts, prob_sums, label_sums


def _arrays(
    y_true: Sequence[bool] | npt.ArrayLike,
    y_prob: Sequence[float] | npt.ArrayLike,
) -> tuple[FloatArray, FloatArray]:
    labels = np.asarray(y_true, dtype=np.float64)
    probs = np.asarray(y_prob, dtype=np.float64)
    if labels.size == 0 or probs.size == 0:
        raise ValueError("y_true and y_prob must be non-empty")
    if labels.shape != probs.shape:
        raise ValueError("y_true and y_prob must have the same length")
    if np.any((probs < 0.0) | (probs > 1.0)):
        raise ValueError("probabilities must be in [0, 1]")
    return labels, probs
