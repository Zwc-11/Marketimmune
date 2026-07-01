"""Tests for markout model-evaluation reports."""

from __future__ import annotations

import math

import pytest

from marketimmune.models import evaluate_markout_predictions
from marketimmune.models.markout_evaluation import (
    MarkoutEvaluationReport,
    _fold_thresholds,
    evaluate_holdout_predictions,
    fold_local_markout_thresholds,
    select_markout_threshold,
)
from marketimmune.models.promotion import ModelMetrics


def test_markout_report_aggregates_temporal_fold_metrics() -> None:
    report = evaluate_markout_predictions(
        timestamps_ms=[0, 1, 2, 3],
        y_true=[False, True, False, True],
        probabilities=[0.1, 0.9, 0.2, 0.8],
        markout_bps=[1.0, -5.0, 2.0, -4.0],
        model_name="out-of-fold-catboost-candidate",
        n_splits=2,
        decision_threshold=0.5,
        calibration_bin_count=2,
    )

    assert isinstance(report, MarkoutEvaluationReport)
    assert report.pr_auc == pytest.approx(1.0)
    assert report.brier == pytest.approx(0.025)
    assert report.ece == pytest.approx(0.15)
    assert report.markout_lift_bps == pytest.approx(2.25)
    assert report.quote_rate == pytest.approx(0.5)
    first = report.folds[0]
    assert first.fold_id == 1
    assert first.n_train == 2
    assert first.n_test == 2
    assert first.test_start_ms == pytest.approx(0.0)
    assert first.test_end_ms == pytest.approx(1.0)
    assert first.pr_auc == pytest.approx(1.0)
    assert first.brier == pytest.approx(0.01)
    assert first.ece == pytest.approx(0.1)
    assert first.baseline_markout_bps == pytest.approx(-2.0)
    assert first.policy_markout_bps == pytest.approx(0.5)
    assert first.markout_lift_bps == pytest.approx(2.5)
    assert first.quote_rate == pytest.approx(0.5)
    assert first.decision_threshold == pytest.approx(0.5)


def test_markout_report_accepts_row_level_thresholds() -> None:
    report = evaluate_markout_predictions(
        timestamps_ms=[0, 1, 2, 3],
        y_true=[False, True, False, True],
        probabilities=[0.1, 0.9, 0.2, 0.8],
        markout_bps=[1.0, -5.0, 2.0, -4.0],
        model_name="fold-local-policy",
        n_splits=2,
        decision_threshold=None,
        decision_thresholds=[0.5, 0.5, 0.1, 0.9],
        calibration_bin_count=2,
    )

    assert report.decision_threshold is None
    assert report.folds[0].decision_threshold == pytest.approx(0.5)
    assert report.folds[1].decision_threshold == pytest.approx(0.5)
    assert report.folds[1].quote_rate == pytest.approx(0.5)
    assert report.folds[1].policy_markout_bps == pytest.approx(-2.0)


def test_markout_report_serializes_and_feeds_promotion_policy() -> None:
    report = evaluate_markout_predictions(
        timestamps_ms=[0, 1, 2, 3],
        y_true=[False, True, False, True],
        probabilities=[0.1, 0.9, 0.2, 0.8],
        markout_bps=[1.0, -5.0, 2.0, -4.0],
        model_name="candidate",
        n_splits=2,
    )

    payload = report.to_dict()
    assert payload["model_name"] == "candidate"
    assert payload["leakage_safe"] is True
    assert len(payload["folds"]) == 2
    metrics = report.promotion_metrics(latency_p95_ms=0.7)
    assert metrics == ModelMetrics(
        pr_auc=report.pr_auc,
        markout_lift_bps=report.markout_lift_bps,
        brier=report.brier,
        latency_p95_ms=0.7,
        leakage_safe=True,
    )


def test_holdout_report_uses_one_unsplit_fold() -> None:
    report = evaluate_holdout_predictions(
        timestamps_ms=[10, 11, 12, 13],
        y_true=[False, True, False, True],
        probabilities=[0.1, 0.9, 0.2, 0.8],
        markout_bps=[1.0, -5.0, 2.0, -4.0],
        model_name="candidate-holdout",
        train_rows=100,
        decision_threshold=0.5,
        calibration_bin_count=2,
    )

    assert report.n_splits == 1
    assert report.n_rows == 4
    assert report.decision_threshold == pytest.approx(0.5)
    assert report.pr_auc == pytest.approx(1.0)
    assert report.markout_lift_bps == pytest.approx(2.25)
    assert report.folds[0].n_train == 100
    assert report.folds[0].test_start_ms == pytest.approx(10.0)
    assert report.folds[0].test_end_ms == pytest.approx(13.0)


def test_one_class_folds_keep_pr_auc_nan_without_breaking_other_metrics() -> None:
    report = evaluate_markout_predictions(
        timestamps_ms=[0, 1],
        y_true=[True, True],
        probabilities=[0.8, 0.7],
        markout_bps=[-4.0, -2.0],
        model_name="one-class",
        n_splits=2,
    )

    assert all(math.isnan(fold.pr_auc) for fold in report.folds)
    assert math.isnan(report.pr_auc)
    assert report.brier == pytest.approx(((1.0 - 0.8) ** 2 + (1.0 - 0.7) ** 2) / 2)


def test_rejects_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="align"):
        evaluate_markout_predictions(
            timestamps_ms=[0, 1],
            y_true=[True],
            probabilities=[0.9, 0.1],
            markout_bps=[-1.0, 2.0],
            model_name="bad",
            n_splits=2,
        )


def test_rejects_bad_threshold_bins_and_probability() -> None:
    with pytest.raises(ValueError, match="decision_threshold is required"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [0.9, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
            decision_threshold=None,
        )
    with pytest.raises(ValueError, match="decision_threshold"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [0.9, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
            decision_threshold=1.1,
        )
    with pytest.raises(ValueError, match="calibration_bin_count"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [0.9, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
            calibration_bin_count=0,
        )
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [1.2, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
        )
    with pytest.raises(ValueError, match="decision_thresholds"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [0.9, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
            decision_threshold=None,
            decision_thresholds=[0.5],
        )
    with pytest.raises(ValueError, match="decision_thresholds"):
        evaluate_markout_predictions(
            [0, 1],
            [True, False],
            [0.9, 0.1],
            [-1.0, 2.0],
            model_name="bad",
            n_splits=2,
            decision_threshold=None,
            decision_thresholds=[0.5, 1.2],
        )


def test_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_markout_predictions([], [], [], [], model_name="bad", n_splits=2)


def test_select_markout_threshold_respects_quote_rate_budget() -> None:
    selection = select_markout_threshold(
        probabilities=[0.1, 0.2, 0.7, 0.8],
        markout_bps=[2.0, 1.0, -5.0, -4.0],
        thresholds=[0.15, 0.5, 0.9],
        min_quote_rate=0.2,
        max_quote_rate=0.6,
    )

    assert selection.threshold == pytest.approx(0.5)
    assert selection.quote_rate == pytest.approx(0.5)
    assert selection.markout_lift_bps == pytest.approx(2.25)
    assert selection.eligible is True


def test_threshold_selection_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty and aligned"):
        select_markout_threshold([], [], [0.5])
    with pytest.raises(ValueError, match="non-empty"):
        select_markout_threshold([0.1], [1.0], [])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        select_markout_threshold([0.1], [1.0], [1.2])
    with pytest.raises(ValueError, match="quote-rate bounds"):
        select_markout_threshold([0.1], [1.0], [0.5], min_quote_rate=0.8, max_quote_rate=0.2)


def test_select_markout_threshold_falls_back_when_quote_budget_is_unreachable() -> None:
    selection = select_markout_threshold(
        probabilities=[0.1, 0.2],
        markout_bps=[1.0, -2.0],
        thresholds=[0.0],
        min_quote_rate=0.5,
        max_quote_rate=0.8,
    )

    assert selection.threshold == pytest.approx(0.0)
    assert selection.quote_rate == pytest.approx(0.0)
    assert selection.eligible is False


def test_fold_local_markout_thresholds_use_train_rows_for_each_fold() -> None:
    thresholds, summaries = fold_local_markout_thresholds(
        timestamps_ms=[0, 1, 2, 3, 4, 5],
        probabilities=[0.1, 0.2, 0.3, 0.7, 0.8, 0.9],
        markout_bps=[2.0, 1.0, 0.5, -0.5, -3.0, -4.0],
        n_splits=3,
        threshold_grid=[0.25, 0.5, 0.85],
        min_quote_rate=0.2,
        max_quote_rate=0.8,
    )

    assert len(thresholds) == 6
    assert len(summaries) == 3
    assert {summary["threshold"] for summary in summaries}.issubset({0.25, 0.5, 0.85})


def test_fold_local_markout_thresholds_reject_misaligned_inputs() -> None:
    with pytest.raises(ValueError, match="must align"):
        fold_local_markout_thresholds(
            timestamps_ms=[0, 1],
            probabilities=[0.1],
            markout_bps=[1.0, 2.0],
            n_splits=2,
            threshold_grid=[0.5],
        )


def test_fold_thresholds_requires_a_fixed_threshold_or_row_thresholds() -> None:
    with pytest.raises(ValueError, match="decision_threshold is required"):
        _fold_thresholds(
            decision_threshold=None,
            decision_thresholds=None,
            test_indices=[0],
        )
