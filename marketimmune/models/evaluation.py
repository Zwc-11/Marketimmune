"""Out-of-fold accounting for the markout classifier: fold metrics and the quoting policy.

The policy is "skip the fill when ``p(toxic) >= threshold``"; a skipped fill contributes
zero markout, so policy markout is per opportunity. For a sorted probability vector the
kept set of any threshold is a prefix, which makes a threshold sweep one sort, one
cumulative sum and one ``searchsorted`` over the grid. NaN predictions mark rows that no
fold model scored; they are left out without moving fold boundaries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.metrics import average_precision_score  # type: ignore[import-untyped]

from marketimmune.models.cross_validation import FoldArrays

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IndexArray = npt.NDArray[np.intp]
CALIBRATION_BINS = 10
FORWARD_HOLDOUT = "forward_holdout"
ROLLING_DAILY = "rolling_daily"


@dataclass(frozen=True, slots=True)
class MarkoutFoldReport:
    """Metrics for one test fold (markouts in bps)."""

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


@dataclass(frozen=True, slots=True)
class MarkoutEvaluationReport:
    """Fold reports plus their test-size-weighted means (NaN folds left out)."""

    model_name: str
    folds: tuple[MarkoutFoldReport, ...]
    n_rows: int
    purge_ms: float
    decision_threshold: float | None
    leakage_safe: bool
    cv_scheme: str

    @property
    def n_evaluated(self) -> int:
        return sum(fold.n_test for fold in self.folds)

    @property
    def pr_auc(self) -> float:
        return self._mean("pr_auc")

    @property
    def brier(self) -> float:
        return self._mean("brier")

    @property
    def ece(self) -> float:
        return self._mean("ece")

    @property
    def markout_lift_bps(self) -> float:
        return self._mean("markout_lift_bps")

    @property
    def quote_rate(self) -> float:
        return self._mean("quote_rate")

    def to_dict(self) -> dict[str, Any]:
        # NOTE: n_splits / embargo_ms are kept for readers of older reports; a daily
        # walk-forward has one fold per tested day and no embargo.
        return {
            "model_name": self.model_name,
            "cv_scheme": self.cv_scheme,
            "n_rows": self.n_rows,
            "n_evaluated": self.n_evaluated,
            "n_splits": len(self.folds),
            "purge_ms": self.purge_ms,
            "embargo_ms": 0.0,
            "decision_threshold": self.decision_threshold,
            "leakage_safe": self.leakage_safe,
            "pr_auc": self.pr_auc,
            "brier": self.brier,
            "ece": self.ece,
            "markout_lift_bps": self.markout_lift_bps,
            "quote_rate": self.quote_rate,
            "folds": [asdict(fold) for fold in self.folds],
        }

    def _mean(self, name: str) -> float:
        pairs: list[tuple[float, int]] = [(getattr(fold, name), fold.n_test) for fold in self.folds if not np.isnan(getattr(fold, name))]
        if not pairs:
            return float("nan")
        return sum(value * weight for value, weight in pairs) / sum(weight for _value, weight in pairs)


# A skip threshold above every probability: quote every fill (the quote-all baseline).
QUOTE_ALL = 1.0 + 1e-9


@dataclass(frozen=True, slots=True)
class ThresholdSelection:
    """One skip threshold scored on realised markout (bps)."""

    threshold: float
    baseline_markout_bps: float
    policy_markout_bps: float
    markout_lift_bps: float
    quote_rate: float
    eligible: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_markout_predictions(
    y_true: npt.ArrayLike,
    probabilities: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    *,
    model_name: str,
    folds: Sequence[FoldArrays],
    thresholds: npt.ArrayLike,
    purge_ms: float,
    leakage_safe: bool,
) -> MarkoutEvaluationReport:
    """Score out-of-fold ``probabilities`` on the training ``folds`` with per-row ``thresholds``."""
    labels, probs, markouts = _arrays(y_true, probabilities, markout_bps)
    row_thresholds = np.asarray(thresholds, dtype=np.float64)
    assert row_thresholds.shape == probs.shape, f"{row_thresholds.shape=} {probs.shape=}"
    reports = tuple(
        _evaluate_fold(idx, int(fold.train.size), test, fold.test_start_ms, fold.test_end_ms, labels, probs, markouts, row_thresholds)
        for idx, fold in enumerate(folds, start=1)
        for test in (fold.test[np.isfinite(probs[fold.test])],)
        if test.size
    )
    return MarkoutEvaluationReport(model_name, reports, int(probs.size), purge_ms, None, leakage_safe, ROLLING_DAILY)


def evaluate_holdout_predictions(
    timestamps_ms: npt.ArrayLike,
    y_true: npt.ArrayLike,
    probabilities: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    *,
    model_name: str,
    train_rows: int,
    decision_threshold: float,
) -> MarkoutEvaluationReport:
    """Score one fully held-out panel as a single fold at a fixed threshold."""
    labels, probs, markouts = _arrays(y_true, probabilities, markout_bps)
    ts = np.asarray(timestamps_ms, dtype=np.float64)
    test = np.arange(ts.size, dtype=np.intp)
    fold = _evaluate_fold(
        1, train_rows, test, float(ts.min()), float(ts.max()), labels, probs, markouts, np.full(ts.size, decision_threshold)
    )
    return MarkoutEvaluationReport(model_name, (fold,), int(ts.size), 0.0, decision_threshold, False, FORWARD_HOLDOUT)


def threshold_sweep(
    probabilities: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    thresholds: Sequence[float],
    *,
    min_quote_rate: float,
    max_quote_rate: float,
) -> tuple[ThresholdSelection, ...]:
    """Every threshold of the (deduplicated, sorted) grid in one pass of sorted prefix sums."""
    probs = np.asarray(probabilities, dtype=np.float64)
    markouts = np.asarray(markout_bps, dtype=np.float64)
    grid = sorted(dict.fromkeys(float(value) for value in thresholds))
    assert grid and grid[0] >= 0.0 and grid[-1] <= 1.0, f"{grid=}"
    assert 0.0 <= min_quote_rate <= max_quote_rate <= 1.0, f"{min_quote_rate=} {max_quote_rate=}"
    assert probs.size and probs.shape == markouts.shape, f"{probs.shape=} {markouts.shape=}"
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
    probabilities: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    thresholds: Sequence[float],
    *,
    min_quote_rate: float,
    max_quote_rate: float,
) -> ThresholdSelection | None:
    """Best markout lift inside the quote-rate budget; ties go to the quote rate nearest the
    budget's middle, then the lower threshold. None when no threshold is inside the budget: the
    caller says what that means (no deployable policy; quote everything on a fold), rather than
    this function quietly returning a policy that breaks the budget."""
    selections = threshold_sweep(probabilities, markout_bps, thresholds, min_quote_rate=min_quote_rate, max_quote_rate=max_quote_rate)
    pool = tuple(selection for selection in selections if selection.eligible)
    if not pool:
        return None
    target = (min_quote_rate + max_quote_rate) / 2.0
    return max(pool, key=lambda s: (s.markout_lift_bps, -abs(s.quote_rate - target), -s.threshold))


def fold_local_markout_thresholds(
    probabilities: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    *,
    folds: Sequence[FoldArrays],
    threshold_grid: Sequence[float],
    min_quote_rate: float,
    max_quote_rate: float,
) -> tuple[FloatArray, tuple[dict[str, Any], ...]]:
    """Per-row thresholds, each fold's chosen on the OOF predictions inside its own training
    window. A fold with none there (the first tested day) gets the grid's middle value; a fold
    where no threshold keeps the quote rate inside the budget quotes everything (threshold
    ``QUOTE_ALL``), and its summary says so."""
    probs = np.asarray(probabilities, dtype=np.float64)
    markouts = np.asarray(markout_bps, dtype=np.float64)
    assert probs.shape == markouts.shape, f"{probs.shape=} {markouts.shape=}"
    grid = sorted(dict.fromkeys(float(value) for value in threshold_grid))
    middle = grid[len(grid) // 2]
    thresholds = np.full(probs.size, middle, dtype=np.float64)
    summaries: list[dict[str, Any]] = []
    for fold_id, fold in enumerate(folds, start=1):
        if not np.any(np.isfinite(probs[fold.test])):
            continue
        train = fold.train[np.isfinite(probs[fold.train])]
        sizes = {"fold_id": fold_id, "n_train": int(fold.train.size), "n_threshold_train": int(train.size), "n_test": int(fold.test.size)}
        if train.size == 0:
            summaries.append({**sizes, "threshold": middle, "fallback": "no training-side OOF predictions"})
            continue
        selection = select_markout_threshold(
            probs[train], markouts[train], grid, min_quote_rate=min_quote_rate, max_quote_rate=max_quote_rate
        )
        if selection is None:
            thresholds[fold.test] = QUOTE_ALL
            summaries.append({**sizes, "threshold": None, "fallback": "no threshold inside the quote-rate budget: quote all"})
            continue
        thresholds[fold.test] = selection.threshold
        summaries.append({**sizes, **selection.to_dict()})
    return thresholds, tuple(summaries)


def brier_score(labels: npt.ArrayLike, probabilities: npt.ArrayLike) -> float:
    return float(np.mean((np.asarray(labels, dtype=np.float64) - np.asarray(probabilities, dtype=np.float64)) ** 2))


def expected_calibration_error(labels: npt.ArrayLike, probabilities: npt.ArrayLike, *, bins: int = CALIBRATION_BINS) -> float:
    """Count-weighted mean |observed rate - mean prediction| over equal-width bins of [0, 1],
    computed as ``sum_b |sum(y_b) - sum(p_b)| / n``."""
    y = np.asarray(labels, dtype=np.float64)
    p = np.asarray(probabilities, dtype=np.float64)
    index = np.minimum((p * bins).astype(np.int64), bins - 1)
    prob_sums = np.bincount(index, weights=p, minlength=bins)
    label_sums = np.bincount(index, weights=y, minlength=bins)
    return float(np.abs(label_sums - prob_sums).sum() / y.size)


def _evaluate_fold(
    fold_id: int,
    n_train: int,
    test: IndexArray,
    test_start_ms: float,
    test_end_ms: float,
    labels: BoolArray,
    probabilities: FloatArray,
    markout_bps: FloatArray,
    thresholds: FloatArray,
) -> MarkoutFoldReport:
    fold_labels, fold_probs, fold_markouts, fold_thresholds = labels[test], probabilities[test], markout_bps[test], thresholds[test]
    kept = fold_probs < fold_thresholds
    n = float(test.size)
    baseline = float(fold_markouts.mean())
    policy = float(np.where(kept, fold_markouts, 0.0).sum()) / n
    positives = int(np.count_nonzero(fold_labels))
    return MarkoutFoldReport(
        fold_id=fold_id,
        n_train=n_train,
        n_test=int(test.size),
        test_start_ms=test_start_ms,
        test_end_ms=test_end_ms,
        decision_threshold=float(fold_thresholds.mean()),
        pr_auc=float(average_precision_score(fold_labels, fold_probs)) if 0 < positives < fold_labels.size else float("nan"),
        brier=brier_score(fold_labels, fold_probs),
        ece=expected_calibration_error(fold_labels, fold_probs),
        baseline_markout_bps=baseline,
        policy_markout_bps=policy,
        markout_lift_bps=policy - baseline,
        quote_rate=float(np.count_nonzero(kept)) / n,
    )


def _arrays(y_true: npt.ArrayLike, probabilities: npt.ArrayLike, markout_bps: npt.ArrayLike) -> tuple[BoolArray, FloatArray, FloatArray]:
    labels = np.asarray(y_true, dtype=np.bool_)
    probs = np.asarray(probabilities, dtype=np.float64)
    markouts = np.asarray(markout_bps, dtype=np.float64)
    assert probs.size and labels.shape == probs.shape == markouts.shape, f"{labels.shape=} {probs.shape=} {markouts.shape=}"
    assert not np.any((probs < 0.0) | (probs > 1.0)), "probabilities must be in [0, 1]"
    return labels, probs, markouts
