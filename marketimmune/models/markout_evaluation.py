"""Evaluation reports for markout-based toxicity models.

The trainer should own fitting. This module owns the honest accounting: given
out-of-fold probabilities, timestamps, labels, and realized markout, it reports
purged-walk-forward fold metrics plus the quoting-policy markout lift.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sklearn.metrics import average_precision_score  # type: ignore[import-untyped]

from marketimmune.models.calibration import brier_score, expected_calibration_error
from marketimmune.models.promotion import ModelMetrics
from marketimmune.models.walk_forward import purged_walk_forward_splits


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
    leakage_safe: bool = True

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
            "n_rows": self.n_rows,
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
    timestamps_ms: Sequence[float],
    y_true: Sequence[bool],
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    *,
    model_name: str,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    decision_threshold: float | None = 0.5,
    decision_thresholds: Sequence[float] | None = None,
    calibration_bin_count: int = 10,
) -> MarkoutEvaluationReport:
    """Evaluate already-produced probabilities under purged walk-forward folds.

    ``probabilities`` should be out-of-fold predictions from the same fold protocol.
    A probability at or above ``decision_threshold`` means "skip this maker quote".
    Skipped fills contribute zero markout to opportunity-level policy PnL.
    """
    ts = tuple(float(value) for value in timestamps_ms)
    labels = tuple(bool(value) for value in y_true)
    probs = tuple(float(value) for value in probabilities)
    markouts = tuple(float(value) for value in markout_bps)
    _validate_inputs(
        ts,
        labels,
        probs,
        markouts,
        decision_threshold,
        decision_thresholds,
        calibration_bin_count,
    )
    thresholds = (
        tuple(float(value) for value in decision_thresholds)
        if decision_thresholds is not None
        else None
    )

    folds = purged_walk_forward_splits(
        ts,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
    )
    fold_reports = tuple(
        _evaluate_fold(
            fold_id=idx,
            train_count=len(fold.train_indices),
            test_indices=fold.test_indices,
            test_start_ms=fold.test_start_ms,
            test_end_ms=fold.test_end_ms,
            labels=labels,
            probabilities=probs,
            markout_bps=markouts,
            decision_threshold=decision_threshold,
            decision_thresholds=thresholds,
            calibration_bin_count=calibration_bin_count,
        )
        for idx, fold in enumerate(folds, start=1)
    )
    return MarkoutEvaluationReport(
        model_name=model_name,
        folds=fold_reports,
        n_rows=len(ts),
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        decision_threshold=decision_threshold if thresholds is None else None,
    )


def evaluate_holdout_predictions(
    timestamps_ms: Sequence[float],
    y_true: Sequence[bool],
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    *,
    model_name: str,
    train_rows: int,
    decision_threshold: float,
    calibration_bin_count: int = 10,
) -> MarkoutEvaluationReport:
    """Evaluate one fully held-out partition with no internal re-splitting."""
    ts = tuple(float(value) for value in timestamps_ms)
    labels = tuple(bool(value) for value in y_true)
    probs = tuple(float(value) for value in probabilities)
    markouts = tuple(float(value) for value in markout_bps)
    _validate_inputs(
        ts,
        labels,
        probs,
        markouts,
        decision_threshold,
        None,
        calibration_bin_count,
    )
    fold = _evaluate_fold(
        fold_id=1,
        train_count=train_rows,
        test_indices=tuple(range(len(ts))),
        test_start_ms=min(ts),
        test_end_ms=max(ts),
        labels=labels,
        probabilities=probs,
        markout_bps=markouts,
        decision_threshold=decision_threshold,
        decision_thresholds=None,
        calibration_bin_count=calibration_bin_count,
    )
    return MarkoutEvaluationReport(
        model_name=model_name,
        folds=(fold,),
        n_rows=len(ts),
        n_splits=1,
        purge_ms=0.0,
        embargo_ms=0.0,
        decision_threshold=decision_threshold,
    )


def select_markout_threshold(
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    thresholds: Sequence[float],
    *,
    min_quote_rate: float = 0.0,
    max_quote_rate: float = 1.0,
) -> ThresholdSelection:
    """Select the skip threshold with the best markout lift inside a quote budget."""
    probs = tuple(float(value) for value in probabilities)
    markouts = tuple(float(value) for value in markout_bps)
    grid = _validate_threshold_grid(thresholds)
    _validate_quote_rate_bounds(min_quote_rate, max_quote_rate)
    if not probs or len(probs) != len(markouts):
        raise ValueError("probabilities and markout_bps must be non-empty and aligned")

    baseline = _mean(markouts)
    selections = tuple(
        _threshold_selection(
            probs,
            markouts,
            threshold=threshold,
            baseline_markout_bps=baseline,
            min_quote_rate=min_quote_rate,
            max_quote_rate=max_quote_rate,
        )
        for threshold in grid
    )
    eligible = tuple(selection for selection in selections if selection.eligible)
    pool = eligible or selections
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
    timestamps_ms: Sequence[float],
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    threshold_grid: Sequence[float],
    min_quote_rate: float = 0.0,
    max_quote_rate: float = 1.0,
) -> tuple[tuple[float, ...], tuple[dict[str, Any], ...]]:
    """Choose one policy threshold per test fold from that fold's train rows."""
    ts = tuple(float(value) for value in timestamps_ms)
    probs = tuple(float(value) for value in probabilities)
    markouts = tuple(float(value) for value in markout_bps)
    lengths = {len(ts), len(probs), len(markouts)}
    if len(lengths) != 1:
        raise ValueError("timestamps, probabilities, and markout_bps must align")
    grid = _validate_threshold_grid(threshold_grid)
    _validate_quote_rate_bounds(min_quote_rate, max_quote_rate)
    thresholds = [grid[len(grid) // 2]] * len(ts)
    summaries: list[dict[str, Any]] = []
    folds = purged_walk_forward_splits(
        ts,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
    )
    for fold_id, fold in enumerate(folds, start=1):
        selection = select_markout_threshold(
            _take(probs, fold.train_indices),
            _take(markouts, fold.train_indices),
            grid,
            min_quote_rate=min_quote_rate,
            max_quote_rate=max_quote_rate,
        )
        for idx in fold.test_indices:
            thresholds[idx] = selection.threshold
        summaries.append({
            "fold_id": fold_id,
            "n_train": len(fold.train_indices),
            "n_test": len(fold.test_indices),
            **selection.to_dict(),
        })
    return tuple(thresholds), tuple(summaries)


def _evaluate_fold(
    *,
    fold_id: int,
    train_count: int,
    test_indices: Sequence[int],
    test_start_ms: float,
    test_end_ms: float,
    labels: Sequence[bool],
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    decision_threshold: float | None,
    decision_thresholds: Sequence[float] | None,
    calibration_bin_count: int,
) -> MarkoutFoldReport:
    fold_labels = _take(labels, test_indices)
    fold_probs = _take(probabilities, test_indices)
    fold_markouts = _take(markout_bps, test_indices)
    fold_thresholds = _fold_thresholds(
        decision_threshold=decision_threshold,
        decision_thresholds=decision_thresholds,
        test_indices=test_indices,
    )
    baseline = _mean(fold_markouts)
    policy = _policy_markout(fold_probs, fold_markouts, fold_thresholds)
    return MarkoutFoldReport(
        fold_id=fold_id,
        n_train=train_count,
        n_test=len(test_indices),
        test_start_ms=test_start_ms,
        test_end_ms=test_end_ms,
        decision_threshold=_mean(fold_thresholds),
        pr_auc=_pr_auc(fold_labels, fold_probs),
        brier=brier_score(fold_labels, fold_probs),
        ece=expected_calibration_error(
            fold_labels,
            fold_probs,
            bins=calibration_bin_count,
        ),
        baseline_markout_bps=baseline,
        policy_markout_bps=policy,
        markout_lift_bps=policy - baseline,
        quote_rate=sum(
            1 for prob, threshold in zip(fold_probs, fold_thresholds, strict=True)
            if prob < threshold
        )
        / len(fold_probs),
    )


def _policy_markout(
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    decision_thresholds: Sequence[float],
) -> float:
    kept_or_zero = (
        markout if prob < threshold else 0.0
        for prob, markout, threshold in zip(
            probabilities,
            markout_bps,
            decision_thresholds,
            strict=True,
        )
    )
    return sum(kept_or_zero) / len(markout_bps)


def _pr_auc(labels: Sequence[bool], probabilities: Sequence[float]) -> float:
    if len(set(labels)) < 2:
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


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _take[T](values: Sequence[T], indices: Sequence[int]) -> tuple[T, ...]:
    return tuple(values[idx] for idx in indices)


def _validate_inputs(
    timestamps_ms: Sequence[float],
    y_true: Sequence[bool],
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    decision_threshold: float | None,
    decision_thresholds: Sequence[float] | None,
    calibration_bin_count: int,
) -> None:
    if not timestamps_ms:
        raise ValueError("evaluation inputs must be non-empty")
    lengths = {len(timestamps_ms), len(y_true), len(probabilities), len(markout_bps)}
    if len(lengths) != 1:
        raise ValueError("timestamps, labels, probabilities, and markout_bps must align")
    if decision_thresholds is None and decision_threshold is None:
        raise ValueError("decision_threshold is required without decision_thresholds")
    if decision_threshold is not None and (
        decision_threshold < 0.0 or decision_threshold > 1.0
    ):
        raise ValueError("decision_threshold must be in [0, 1]")
    if decision_thresholds is not None:
        if len(decision_thresholds) != len(timestamps_ms):
            raise ValueError("decision_thresholds must align with timestamps")
        if any(threshold < 0.0 or threshold > 1.0 for threshold in decision_thresholds):
            raise ValueError("decision_thresholds must be in [0, 1]")
    if calibration_bin_count < 1:
        raise ValueError("calibration_bin_count must be >= 1")
    if any(prob < 0.0 or prob > 1.0 for prob in probabilities):
        raise ValueError("probabilities must be in [0, 1]")


def _fold_thresholds(
    *,
    decision_threshold: float | None,
    decision_thresholds: Sequence[float] | None,
    test_indices: Sequence[int],
) -> tuple[float, ...]:
    if decision_thresholds is not None:
        return _take(decision_thresholds, test_indices)
    if decision_threshold is None:
        raise ValueError("decision_threshold is required without decision_thresholds")
    return tuple(float(decision_threshold) for _idx in test_indices)


def _threshold_selection(
    probabilities: Sequence[float],
    markout_bps: Sequence[float],
    *,
    threshold: float,
    baseline_markout_bps: float,
    min_quote_rate: float,
    max_quote_rate: float,
) -> ThresholdSelection:
    thresholds = tuple(threshold for _prob in probabilities)
    policy = _policy_markout(probabilities, markout_bps, thresholds)
    quote_rate = sum(
        1 for prob, threshold_value in zip(probabilities, thresholds, strict=True)
        if prob < threshold_value
    ) / len(probabilities)
    return ThresholdSelection(
        threshold=threshold,
        baseline_markout_bps=baseline_markout_bps,
        policy_markout_bps=policy,
        markout_lift_bps=policy - baseline_markout_bps,
        quote_rate=quote_rate,
        eligible=min_quote_rate <= quote_rate <= max_quote_rate,
    )


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
