"""Tests for the out-of-fold markout evaluation and the quoting-policy threshold search."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketimmune.models.cross_validation import FoldArrays
from marketimmune.models.evaluation import (
    MarkoutEvaluationReport,
    brier_score,
    evaluate_holdout_predictions,
    evaluate_markout_predictions,
    expected_calibration_error,
    fold_local_markout_thresholds,
    select_markout_threshold,
)

LABELS = [False, True, False, True]
PROBS = [0.1, 0.9, 0.2, 0.8]
MARKOUTS = [1.0, -5.0, 2.0, -4.0]


def _fold(train: list[int], test: list[int]) -> FoldArrays:
    return FoldArrays(
        np.asarray(train, dtype=np.intp), np.asarray(test, dtype=np.intp), float(test[0]), float(test[-1]), 0.0, float(test[-1])
    )


FOLDS = (_fold([2, 3], [0, 1]), _fold([0, 1], [2, 3]))


def _evaluate(
    probabilities: list[float] = PROBS, thresholds: list[float] | None = None, labels: list[bool] = LABELS
) -> MarkoutEvaluationReport:
    return evaluate_markout_predictions(
        labels,
        probabilities,
        MARKOUTS[: len(labels)],
        model_name="candidate",
        folds=FOLDS,
        thresholds=[0.5] * len(labels) if thresholds is None else thresholds,
        purge_ms=60_000.0,
        leakage_safe=True,
    )


def test_markout_report_weights_fold_metrics_by_test_size() -> None:
    report = _evaluate()
    assert report.pr_auc == pytest.approx(1.0)
    assert report.brier == pytest.approx(0.025)
    assert report.ece == pytest.approx(0.15)
    assert report.markout_lift_bps == pytest.approx(2.25)
    assert report.quote_rate == pytest.approx(0.5)
    first = report.folds[0]
    assert (first.fold_id, first.n_train, first.n_test, first.test_start_ms, first.test_end_ms) == (1, 2, 2, 0.0, 1.0)
    assert first.brier == pytest.approx(0.01)
    assert first.ece == pytest.approx(0.1)
    assert first.baseline_markout_bps == pytest.approx(-2.0)
    assert first.policy_markout_bps == pytest.approx(0.5)
    assert first.markout_lift_bps == pytest.approx(2.5)


def test_markout_report_uses_row_level_thresholds_and_serializes() -> None:
    report = _evaluate(thresholds=[0.5, 0.5, 0.1, 0.9])
    second = report.folds[1]
    assert second.decision_threshold == pytest.approx(0.5)
    assert second.quote_rate == pytest.approx(0.5)
    assert second.policy_markout_bps == pytest.approx(-2.0)
    payload = report.to_dict()
    assert payload["cv_scheme"] == "rolling_daily"
    assert (payload["n_splits"], payload["purge_ms"], payload["embargo_ms"]) == (2, 60_000.0, 0.0)
    assert payload["decision_threshold"] is None and payload["leakage_safe"] is True
    assert payload["n_rows"] == payload["n_evaluated"] == 4
    assert list(payload["folds"][0]) == [
        "fold_id",
        "n_train",
        "n_test",
        "test_start_ms",
        "test_end_ms",
        "decision_threshold",
        "pr_auc",
        "brier",
        "ece",
        "baseline_markout_bps",
        "policy_markout_bps",
        "markout_lift_bps",
        "quote_rate",
    ]


def test_unscored_rows_are_left_out_without_moving_folds() -> None:
    report = _evaluate(probabilities=[float("nan"), float("nan"), 0.2, 0.8])
    assert [fold.fold_id for fold in report.folds] == [2]
    assert report.n_evaluated == 2 and report.n_rows == 4


def test_one_class_folds_keep_pr_auc_nan_without_breaking_other_metrics() -> None:
    report = _evaluate(labels=[True, True, True, True])
    assert math.isnan(report.pr_auc)
    assert report.brier == pytest.approx(np.mean((1.0 - np.asarray(PROBS)) ** 2))


def test_rejects_misaligned_inputs_and_bad_probabilities() -> None:
    with pytest.raises(AssertionError):
        evaluate_markout_predictions(
            [True], [0.9, 0.1], [1.0, 2.0], model_name="bad", folds=FOLDS, thresholds=[0.5, 0.5], purge_ms=0.0, leakage_safe=False
        )
    with pytest.raises(AssertionError, match=r"\[0, 1\]"):
        _evaluate(probabilities=[1.2, 0.9, 0.2, 0.8])


def test_holdout_report_is_one_fold_at_a_fixed_threshold() -> None:
    report = evaluate_holdout_predictions(
        [10, 11, 12, 13], LABELS, PROBS, MARKOUTS, model_name="holdout", train_rows=100, decision_threshold=0.5
    )
    payload = report.to_dict()
    assert (payload["n_splits"], payload["n_rows"], payload["cv_scheme"], payload["decision_threshold"]) == (1, 4, "forward_holdout", 0.5)
    assert report.markout_lift_bps == pytest.approx(2.25)
    assert (report.folds[0].n_train, report.folds[0].test_start_ms, report.folds[0].test_end_ms) == (100, 10.0, 13.0)


def test_brier_and_expected_calibration_error() -> None:
    labels, probs = [False, True, True], [0.1, 0.8, 1.0]
    assert brier_score(labels, probs) == pytest.approx((0.01 + 0.04 + 0.0) / 3)
    # bins of width 0.5: |0 - 0.1| + |2 - 1.8|, over 3 rows (p = 1.0 lands in the top bin)
    assert expected_calibration_error(labels, probs, bins=2) == pytest.approx(0.1)


def test_select_markout_threshold_respects_quote_rate_budget() -> None:
    selection = select_markout_threshold(
        [0.1, 0.2, 0.7, 0.8], [2.0, 1.0, -5.0, -4.0], [0.15, 0.5, 0.9], min_quote_rate=0.2, max_quote_rate=0.6
    )
    assert (selection.threshold, selection.quote_rate, selection.eligible) == (0.5, 0.5, True)
    assert selection.markout_lift_bps == pytest.approx(2.25)


def test_select_markout_threshold_falls_back_when_quote_budget_is_unreachable() -> None:
    selection = select_markout_threshold([0.1, 0.2], [1.0, -2.0], [0.0], min_quote_rate=0.5, max_quote_rate=0.8)
    assert (selection.threshold, selection.quote_rate, selection.eligible) == (0.0, 0.0, False)


def test_threshold_selection_rejects_invalid_inputs() -> None:
    for probs, markouts, grid, low, high in (([], [], [0.5], 0.0, 1.0), ([0.1], [1.0], [1.2], 0.0, 1.0), ([0.1], [1.0], [0.5], 0.8, 0.2)):
        with pytest.raises(AssertionError):
            select_markout_threshold(probs, markouts, grid, min_quote_rate=low, max_quote_rate=high)


def test_threshold_sweep_matches_bruteforce_policy() -> None:
    probabilities = [0.05, 0.4, 0.4, 0.61, 0.9, 0.2, 0.75]
    markouts = [1.0, -2.0, 0.5, -1.5, -6.0, 2.5, 0.25]
    for threshold in (0.0, 0.2, 0.4, 0.6, 0.9, 1.0):
        selection = select_markout_threshold(probabilities, markouts, [threshold], min_quote_rate=0.0, max_quote_rate=1.0)
        kept = [m if p < threshold else 0.0 for p, m in zip(probabilities, markouts, strict=True)]
        assert selection.policy_markout_bps == pytest.approx(sum(kept) / len(kept))
        assert selection.quote_rate == pytest.approx(sum(p < threshold for p in probabilities) / len(probabilities))


def test_fold_local_thresholds_come_from_each_folds_training_window() -> None:
    probs = [np.nan, np.nan, 0.1, 0.9, 0.2, 0.8]
    markouts = [0.0, 0.0, 1.0, -5.0, 2.0, -4.0]
    folds = (_fold([0, 1], [2, 3]), _fold([2, 3], [4, 5]))
    thresholds, summaries = fold_local_markout_thresholds(
        probs, markouts, folds=folds, threshold_grid=[0.85, 0.25, 0.5], min_quote_rate=0.2, max_quote_rate=0.8
    )
    # fold 1's window has no out-of-fold predictions yet: the grid's middle value
    assert summaries[0]["fallback"] and summaries[0]["threshold"] == 0.5
    assert summaries[1]["n_threshold_train"] == 2 and summaries[1]["threshold"] == 0.25
    assert thresholds.tolist() == [0.5, 0.5, 0.5, 0.5, 0.25, 0.25]
