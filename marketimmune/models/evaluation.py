"""Evaluation reports for markout-based toxicity models.

The trainer owns fitting. This module owns the honest accounting: given
out-of-fold probabilities, timestamps, labels, and realized markout, it reports
temporal fold metrics plus the quoting-policy markout lift.

Everything here is vectorized with NumPy. The quoting policy is "skip the fill when
``p(toxic) >= threshold``", so for a sorted probability vector the kept set for any
threshold is a prefix. A threshold sweep is therefore one sort, one cumulative sum,
and one ``searchsorted`` over the grid: ``O(n log n + g log n)`` instead of the
``O(n * g)`` Python loop it replaced.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.metrics import average_precision_score  # type: ignore[import-untyped]

from marketimmune.models.calibration import brier_score, expected_calibration_error
from marketimmune.models.cross_validation import CvScheme, FoldArrays, temporal_fold_arrays
from marketimmune.models.promotion import ModelMetrics

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IndexArray = npt.NDArray[np.intp]
FORWARD_HOLDOUT = "forward_holdout"


@dataclass(frozen=True, slots=True)
class MarkoutFoldReport:
    """Metrics for one temporal test fold."""

    fold_id: int
    n_train: int
    n_test: int
    test_start_ms: float
    test_end_ms: float
    decision_threshold: float
    pr_auc: float
    brier: float
    ece: float
    baseline_markout_bps: float
    policy_markout_bps: float
    markout_lift_bps: float
    quote_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold_id": self.fold_id,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "test_start_ms": self.test_start_ms,
            "test_end_ms": self.test_end_ms,
            "decision_threshold": self.decision_threshold,
            "pr_auc": self.pr_auc,
            "brier": self.brier,
            "ece": self.ece,
            "baseline_markout_bps": self.baseline_markout_bps,
            "policy_markout_bps": self.policy_markout_bps,
            "markout_lift_bps": self.markout_lift_bps,
            "quote_rate": self.quote_rate,
        }


@dataclass(frozen=True, slots=True)
class MarkoutEvaluationReport:
    """Aggregate model report ready for JSON output or promotion policy input."""

    model_name: str
    folds: tuple[MarkoutFoldReport, ...]
    n_rows: int
    n_splits: int
    purge_ms: float
    embargo_ms: float
    decision_threshold: float | None
    # False unless the caller shows a passing no-look-ahead check (fix B3); the
    # field used to default to True without any test behind it.
    leakage_safe: bool = False
    cv_scheme: str = "walk_forward"

    @property
    def pr_auc(self) -> float:
        return _weighted_mean((fold.pr_auc for fold in self.folds), self._weights())

    @property
    def brier(self) -> float:
        return _weighted_mean((fold.brier for fold in self.folds), self._weights())

    @property
    def ece(self) -> float:
        return _weighted_mean((fold.ece for fold in self.folds), self._weights())

    @property
    def markout_lift_bps(self) -> float:
        return _weighted_mean((fold.markout_lift_bps for fold in self.folds), self._weights())

    @property
    def quote_rate(self) -> float:
        return _weighted_mean((fold.quote_rate for fold in self.folds), self._weights())

    @property
    def n_evaluated(self) -> int:
        """Rows that landed in a test fold (walk-forward never tests its first block)."""
        return sum(fold.n_test for fold in self.folds)

    def promotion_metrics(self, *, latency_p95_ms: float) -> ModelMetrics:
        """Return the compact metric shape consumed by ``PromotionPolicy``."""
        return ModelMetrics(
            pr_auc=self.pr_auc,
            markout_lift_bps=self.markout_lift_bps,
            brier=self.brier,
            latency_p95_ms=latency_p95_ms,
            leakage_safe=self.leakage_safe,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "cv_scheme": self.cv_scheme,
            "n_rows": self.n_rows,
            "n_evaluated": self.n_evaluated,
            "n_splits": self.n_splits,
            "purge_ms": self.purge_ms,
            "embargo_ms": self.embargo_ms,
            "decision_threshold": self.decision_threshold,
            "leakage_safe": self.leakage_safe,
            "pr_auc": self.pr_auc,
            "brier": self.brier,
            "ece": self.ece,
            "markout_lift_bps": self.markout_lift_bps,
            "quote_rate": self.quote_rate,
            "folds": [fold.to_dict() for fold in self.folds],
        }

    def _weights(self) -> tuple[int, ...]:
        return tuple(fold.n_test for fold in self.folds)


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    """A candidate skip threshold evaluated on realized markout."""

    threshold: float
    baseline_markout_bps: float
    policy_markout_bps: float
    markout_lift_bps: float
    quote_rate: float
    eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "baseline_markout_bps": self.baseline_markout_bps,
            "policy_markout_bps": self.policy_markout_bps,
            "markout_lift_bps": self.markout_lift_bps,
            "quote_rate": self.quote_rate,
            "eligible": self.eligible,
        }


def evaluate_markout_predictions(
    timestamps_ms: Sequence[float] | npt.ArrayLike,
    y_true: Sequence[bool] | npt.ArrayLike,
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
    *,
    model_name: str,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    decision_threshold: float | None = 0.5,
    decision_thresholds: Sequence[float] | npt.ArrayLike | None = None,
    calibration_bin_count: int = 10,
    scheme: CvScheme = "walk_forward",
    folds: Sequence[FoldArrays] | None = None,
    train_days: int | None = None,
    leakage_safe: bool = False,
) -> MarkoutEvaluationReport:
    """Evaluate already-produced probabilities under temporal folds.

    ``probabilities`` should be out-of-fold predictions. A probability at or above
    the decision threshold means "skip this maker quote"; skipped fills contribute
    zero markout to opportunity-level policy PnL. Pass the original training
    ``folds`` and full row arrays for OOF evaluation; NaN predictions mark rows
    without a fitted model and are excluded without changing fold boundaries.
    """
    ts, labels, probs, markouts = _arrays(timestamps_ms, y_true, probabilities, markout_bps)
    _validate_inputs(ts, labels, probs, markouts, calibration_bin_count)
    thresholds = _row_thresholds(decision_threshold, decision_thresholds, ts.size)
    folds = folds if folds is not None else temporal_fold_arrays(
        ts,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        scheme=scheme,
        train_days=train_days,
    )
    fold_reports = tuple(
        _evaluate_fold(
            fold_id=idx,
            train_count=int(fold.train.size),
            test=test,
            test_start_ms=fold.test_start_ms,
            test_end_ms=fold.test_end_ms,
            labels=labels,
            probabilities=probs,
            markout_bps=markouts,
            thresholds=thresholds,
            calibration_bin_count=calibration_bin_count,
        )
        for idx, fold in enumerate(folds, start=1)
        for test in (fold.test[np.isfinite(probs[fold.test])],)
        if test.size
    )
    return MarkoutEvaluationReport(
        model_name=model_name,
        folds=fold_reports,
        n_rows=int(ts.size),
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        decision_threshold=decision_threshold if decision_thresholds is None else None,
        leakage_safe=leakage_safe,
        cv_scheme=scheme,
    )


def evaluate_holdout_predictions(
    timestamps_ms: Sequence[float] | npt.ArrayLike,
    y_true: Sequence[bool] | npt.ArrayLike,
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
    *,
    model_name: str,
    train_rows: int,
    decision_threshold: float,
    calibration_bin_count: int = 10,
) -> MarkoutEvaluationReport:
    """Evaluate one fully held-out partition with no internal re-splitting."""
    ts, labels, probs, markouts = _arrays(timestamps_ms, y_true, probabilities, markout_bps)
    _validate_inputs(ts, labels, probs, markouts, calibration_bin_count)
    thresholds = _row_thresholds(decision_threshold, None, ts.size)
    fold = _evaluate_fold(
        fold_id=1,
        train_count=train_rows,
        test=np.arange(ts.size, dtype=np.intp),
        test_start_ms=float(ts.min()),
        test_end_ms=float(ts.max()),
        labels=labels,
        probabilities=probs,
        markout_bps=markouts,
        thresholds=thresholds,
        calibration_bin_count=calibration_bin_count,
    )
    return MarkoutEvaluationReport(
        model_name=model_name,
        folds=(fold,),
        n_rows=int(ts.size),
        n_splits=1,
        purge_ms=0.0,
        embargo_ms=0.0,
        decision_threshold=decision_threshold,
        cv_scheme=FORWARD_HOLDOUT,
    )


def threshold_sweep(
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
    thresholds: Sequence[float],
    *,
    min_quote_rate: float = 0.0,
    max_quote_rate: float = 1.0,
) -> tuple[ThresholdSelection, ...]:
    """Evaluate every threshold in one pass (sorted prefix sums)."""
    probs = np.asarray(probabilities, dtype=np.float64)
    markouts = np.asarray(markout_bps, dtype=np.float64)
    grid = _validate_threshold_grid(thresholds)
    _validate_quote_rate_bounds(min_quote_rate, max_quote_rate)
    if probs.size == 0 or probs.shape != markouts.shape:
        raise ValueError("probabilities and markout_bps must be non-empty and aligned")
    order = np.argsort(probs, kind="stable")
    prefix = np.concatenate(([0.0], np.cumsum(markouts[order])))
    kept = np.searchsorted(probs[order], np.asarray(grid), side="left")
    n = float(probs.size)
    baseline = float(markouts.mean())
    policy = prefix[kept] / n
    quote_rate = kept / n
    return tuple(
        ThresholdSelection(
            threshold=threshold,
            baseline_markout_bps=baseline,
            policy_markout_bps=float(policy[i]),
            markout_lift_bps=float(policy[i]) - baseline,
            quote_rate=float(quote_rate[i]),
            eligible=bool(min_quote_rate <= quote_rate[i] <= max_quote_rate),
        )
        for i, threshold in enumerate(grid)
    )


def select_markout_threshold(
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
    thresholds: Sequence[float],
    *,
    min_quote_rate: float = 0.0,
    max_quote_rate: float = 1.0,
) -> ThresholdSelection:
    """Select the skip threshold with the best markout lift inside a quote budget."""
    selections = threshold_sweep(
        probabilities,
        markout_bps,
        thresholds,
        min_quote_rate=min_quote_rate,
        max_quote_rate=max_quote_rate,
    )
    pool = tuple(selection for selection in selections if selection.eligible) or selections
    target_quote_rate = (min_quote_rate + max_quote_rate) / 2.0
    return max(
        pool,
        key=lambda selection: (
            selection.markout_lift_bps,
            -abs(selection.quote_rate - target_quote_rate),
            -selection.threshold,
        ),
    )


def fold_local_markout_thresholds(
    timestamps_ms: Sequence[float] | npt.ArrayLike,
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    threshold_grid: Sequence[float],
    min_quote_rate: float = 0.0,
    max_quote_rate: float = 1.0,
    scheme: CvScheme = "walk_forward",
    folds: Sequence[FoldArrays] | None = None,
    train_days: int | None = None,
) -> tuple[tuple[float, ...], tuple[dict[str, Any], ...]]:
    """Choose thresholds from available OOF predictions in each original train slice.

    The first walk-forward fold has no earlier OOF predictions. It uses the
    middle grid threshold, fixed independently of its test outcomes.
    """
    ts = np.asarray(timestamps_ms, dtype=np.float64)
    probs = np.asarray(probabilities, dtype=np.float64)
    markouts = np.asarray(markout_bps, dtype=np.float64)
    if not (ts.shape == probs.shape == markouts.shape):
        raise ValueError("timestamps, probabilities, and markout_bps must align")
    grid = _validate_threshold_grid(threshold_grid)
    _validate_quote_rate_bounds(min_quote_rate, max_quote_rate)
    thresholds = np.full(ts.size, grid[len(grid) // 2], dtype=np.float64)
    summaries: list[dict[str, Any]] = []
    folds = folds if folds is not None else temporal_fold_arrays(
        ts,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        scheme=scheme,
        train_days=train_days,
    )
    for fold_id, fold in enumerate(folds, start=1):
        if not np.any(np.isfinite(probs[fold.test])):
            continue
        train = fold.train[np.isfinite(probs[fold.train])]
        if train.size == 0:
            summaries.append({
                "fold_id": fold_id,
                "n_train": int(fold.train.size),
                "n_threshold_train": 0,
                "n_test": int(fold.test.size),
                "threshold": grid[len(grid) // 2],
                "fallback": "no training-side OOF predictions",
            })
            continue
        selection = select_markout_threshold(
            probs[train],
            markouts[train],
            grid,
            min_quote_rate=min_quote_rate,
            max_quote_rate=max_quote_rate,
        )
        thresholds[fold.test] = selection.threshold
        summaries.append({
            "fold_id": fold_id,
            "n_train": int(fold.train.size),
            "n_threshold_train": int(train.size),
            "n_test": int(fold.test.size),
            **selection.to_dict(),
        })
    return tuple(thresholds.tolist()), tuple(summaries)


def _evaluate_fold(
    *,
    fold_id: int,
    train_count: int,
    test: IndexArray,
    test_start_ms: float,
    test_end_ms: float,
    labels: BoolArray,
    probabilities: FloatArray,
    markout_bps: FloatArray,
    thresholds: FloatArray,
    calibration_bin_count: int,
) -> MarkoutFoldReport:
    fold_labels = labels[test]
    fold_probs = probabilities[test]
    fold_markouts = markout_bps[test]
    fold_thresholds = thresholds[test]
    kept = fold_probs < fold_thresholds
    n = float(test.size)
    baseline = float(fold_markouts.mean())
    policy = float(np.where(kept, fold_markouts, 0.0).sum()) / n
    return MarkoutFoldReport(
        fold_id=fold_id,
        n_train=train_count,
        n_test=int(test.size),
        test_start_ms=test_start_ms,
        test_end_ms=test_end_ms,
        decision_threshold=float(fold_thresholds.mean()),
        pr_auc=_pr_auc(fold_labels, fold_probs),
        brier=brier_score(fold_labels, fold_probs),
        ece=expected_calibration_error(fold_labels, fold_probs, bins=calibration_bin_count),
        baseline_markout_bps=baseline,
        policy_markout_bps=policy,
        markout_lift_bps=policy - baseline,
        quote_rate=float(np.count_nonzero(kept)) / n,
    )


def _pr_auc(labels: BoolArray, probabilities: FloatArray) -> float:
    positives = int(np.count_nonzero(labels))
    if positives == 0 or positives == labels.size:
        return float("nan")
    return float(average_precision_score(labels, probabilities))


def _weighted_mean(values: Iterable[float], weights: Sequence[int]) -> float:
    pairs = [
        (value, weight)
        for value, weight in zip(values, weights, strict=True)
        if not math.isnan(value)
    ]
    if not pairs:
        return float("nan")
    weight_sum = sum(weight for _value, weight in pairs)
    return sum(value * weight for value, weight in pairs) / weight_sum


def _arrays(
    timestamps_ms: Sequence[float] | npt.ArrayLike,
    y_true: Sequence[bool] | npt.ArrayLike,
    probabilities: Sequence[float] | npt.ArrayLike,
    markout_bps: Sequence[float] | npt.ArrayLike,
) -> tuple[FloatArray, BoolArray, FloatArray, FloatArray]:
    return (
        np.asarray(timestamps_ms, dtype=np.float64),
        np.asarray(y_true, dtype=np.bool_),
        np.asarray(probabilities, dtype=np.float64),
        np.asarray(markout_bps, dtype=np.float64),
    )


def _row_thresholds(
    decision_threshold: float | None,
    decision_thresholds: Sequence[float] | npt.ArrayLike | None,
    n_rows: int,
) -> FloatArray:
    if decision_thresholds is not None:
        values = np.asarray(decision_thresholds, dtype=np.float64)
        if values.shape != (n_rows,):
            raise ValueError("decision_thresholds must align with timestamps")
        if np.any((values < 0.0) | (values > 1.0)):
            raise ValueError("decision_thresholds must be in [0, 1]")
        return values
    if decision_threshold is None:
        raise ValueError("decision_threshold is required without decision_thresholds")
    if not 0.0 <= decision_threshold <= 1.0:
        raise ValueError("decision_threshold must be in [0, 1]")
    return np.full(n_rows, float(decision_threshold), dtype=np.float64)


def _validate_inputs(
    timestamps_ms: FloatArray,
    y_true: BoolArray,
    probabilities: FloatArray,
    markout_bps: FloatArray,
    calibration_bin_count: int,
) -> None:
    if timestamps_ms.size == 0:
        raise ValueError("evaluation inputs must be non-empty")
    if not (timestamps_ms.shape == y_true.shape == probabilities.shape == markout_bps.shape):
        raise ValueError("timestamps, labels, probabilities, and markout_bps must align")
    if calibration_bin_count < 1:
        raise ValueError("calibration_bin_count must be >= 1")
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        raise ValueError("probabilities must be in [0, 1]")


def _validate_threshold_grid(thresholds: Sequence[float]) -> tuple[float, ...]:
    grid = tuple(dict.fromkeys(float(value) for value in thresholds))
    if not grid:
        raise ValueError("threshold_grid must be non-empty")
    if any(value < 0.0 or value > 1.0 for value in grid):
        raise ValueError("threshold_grid values must be in [0, 1]")
    return tuple(sorted(grid))


def _validate_quote_rate_bounds(min_quote_rate: float, max_quote_rate: float) -> None:
    if min_quote_rate < 0.0 or max_quote_rate > 1.0 or min_quote_rate > max_quote_rate:
        raise ValueError("quote-rate bounds must satisfy 0 <= min <= max <= 1")
