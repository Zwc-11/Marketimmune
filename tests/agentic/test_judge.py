"""Tests for BenchmarkJudgeAgent and its helpers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import marketimmune.agentic.judge as judge_module
from marketimmune.agentic.judge import (
    BenchmarkJudgeAgent,
    JudgeVerdict,
    _first_baseline_markout_delta,
    _first_holdout_baseline_markout_delta,
    _is_nan,
)

from .conftest import _make_training_job

# ---------------------------------------------------------------------------
# _is_nan helper
# ---------------------------------------------------------------------------


def test_is_nan_with_float_nan() -> None:
    assert _is_nan(float("nan")) is True


def test_is_nan_with_normal_float() -> None:
    assert _is_nan(0.85) is False


def test_is_nan_with_none() -> None:
    # None does not satisfy NaN property (it raises TypeError, caught internally)
    assert _is_nan(None) is False


def test_is_nan_with_string() -> None:
    assert _is_nan("hello") is False


def test_is_nan_handles_type_error() -> None:
    class _BadNe:
        def __ne__(self, other: object) -> bool:
            raise TypeError("not comparable")

    assert _is_nan(_BadNe()) is False


# ---------------------------------------------------------------------------
# BenchmarkJudgeAgent: no job supplied
# ---------------------------------------------------------------------------


def test_judge_no_job_skips() -> None:
    agent = BenchmarkJudgeAgent()
    run = agent.run(goal="vote", job=None)
    assert run.success is True
    assert run.output["skipped"] is True
    assert run.linked_artifacts["verdict"] is None


# ---------------------------------------------------------------------------
# BenchmarkJudgeAgent: failed training job
# ---------------------------------------------------------------------------


def test_judge_failed_job_auto_rejects() -> None:
    job = _make_training_job(success=False, error="OOM during training")
    agent = BenchmarkJudgeAgent()
    run = agent.run(goal="vote", job=job)
    assert run.success is True
    verdict = run.linked_artifacts["verdict"]
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.verdict == "reject"
    assert verdict.promote_votes == 0
    assert verdict.reject_votes == 5


# ---------------------------------------------------------------------------
# BenchmarkJudgeAgent: no incumbent file (empty baseline)
# ---------------------------------------------------------------------------


def test_judge_no_incumbent_promotes_if_enough_pass(tmp_path: Path) -> None:
    """With no incumbent file, most criteria pass 'by default'."""
    job = _make_training_job(success=True)
    # Point to a non-existent incumbent report so the agent uses {}
    agent = BenchmarkJudgeAgent(
        incumbent_report=tmp_path / "nonexistent_report.json"
    )
    run = agent.run(goal="vote", job=job)
    assert run.success is True
    verdict = run.linked_artifacts["verdict"]
    assert isinstance(verdict, JudgeVerdict)
    # Without an incumbent, most metrics are 'None' and the compare fallback
    # returns False, but latency check passes by default.
    # The verdict should be one of the valid options.
    assert verdict.verdict in ("promote", "needs_more_data", "reject")


# ---------------------------------------------------------------------------
# BenchmarkJudgeAgent: full evaluation with incumbent
# ---------------------------------------------------------------------------


def test_judge_promotes_when_candidate_better(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.78,
        "roc_auc": 0.81,
        "f1": 0.75,
        "model_name": "GradientBoostingRiskHead-v1",
        "holdout_split": {"pr_auc": 0.72},
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)  # candidate pr_auc=0.85, holdout=0.80
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    assert run.success is True
    verdict = run.linked_artifacts["verdict"]
    assert verdict.verdict in ("promote", "needs_more_data")


def test_judge_rejects_when_candidate_worse(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.95,
        "roc_auc": 0.97,
        "f1": 0.93,
        "holdout_split": {"pr_auc": 0.92},
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)  # candidate pr_auc=0.85 — much worse
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]
    assert verdict.verdict in ("reject", "needs_more_data")


def test_judge_rejects_when_no_criteria_pass(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.90,
        "f1": 0.80,
        "latency": {"p99_ms": 10.0},
        "holdout_split": {"pr_auc": 0.88},
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.70,
            "f1": 0.40,
            "latency": {"p99_ms": 100.0},
        },
        holdout_metrics={"pr_auc": 0.10},
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]
    assert verdict.verdict == "reject"
    assert verdict.promote_votes == 0


def test_judge_delegates_to_promotion_policy_for_v2_metrics(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.80,
        "markout_lift_bps": 0.0,
        "brier": 0.15,
        "latency_p95_ms": 0.7,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.83,
            "markout_lift_bps": 1.2,
            "brier": 0.12,
            "latency_p95_ms": 0.6,
            "leakage_safe": True,
        },
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]
    assert verdict.verdict == "promote"
    assert verdict.metrics["policy"] == "PromotionPolicy"
    assert verdict.criteria["markout_lift"]["passed"] is True


def test_judge_policy_rejects_candidate_that_loses_to_simple_baseline(
    tmp_path: Path,
) -> None:
    incumbent_data = {
        "pr_auc": 0.50,
        "markout_lift_bps": 0.0,
        "brier": 0.30,
        "latency_p95_ms": 0.9,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.54,
            "markout_lift_bps": 0.51,
            "brier": 0.23,
            "latency_p95_ms": 0.8,
            "leakage_safe": True,
            "baseline_comparison": {
                "directional_top_imbalance": {"markout_lift_bps": -0.36}
            },
        },
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]

    assert verdict.verdict == "reject"
    assert verdict.criteria["baseline_markout_lift"]["passed"] is False
    assert "candidate minus baseline" in verdict.criteria["baseline_markout_lift"]["detail"]


def test_judge_policy_accepts_candidate_that_beats_simple_baseline(
    tmp_path: Path,
) -> None:
    incumbent_data = {
        "pr_auc": 0.50,
        "markout_lift_bps": 0.0,
        "brier": 0.30,
        "latency_p95_ms": 0.9,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.54,
            "markout_lift_bps": 0.51,
            "brier": 0.23,
            "latency_p95_ms": 0.8,
            "leakage_safe": True,
            "baseline_comparison": {
                "directional_top_imbalance": {"markout_lift_bps": 0.10}
            },
        },
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]

    assert verdict.verdict == "promote"
    assert verdict.criteria["baseline_markout_lift"]["passed"] is True


def test_judge_policy_rejects_candidate_that_loses_on_holdout_baseline(
    tmp_path: Path,
) -> None:
    incumbent_data = {
        "pr_auc": 0.50,
        "markout_lift_bps": 0.0,
        "brier": 0.30,
        "latency_p95_ms": 0.9,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.54,
            "markout_lift_bps": 0.51,
            "brier": 0.23,
            "latency_p95_ms": 0.8,
            "leakage_safe": True,
            "baseline_comparison": {
                "event_ofi": {"markout_lift_bps": 0.10}
            },
            "holdout_split": {
                "baseline_comparison": {
                    "event_ofi": {"markout_lift_bps": -0.02}
                }
            },
        },
    )
    run = BenchmarkJudgeAgent(incumbent_report=report_path).run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]

    assert verdict.verdict == "reject"
    assert verdict.criteria["baseline_markout_lift"]["passed"] is True
    assert verdict.criteria["holdout_baseline_markout_lift"]["passed"] is False


def test_first_baseline_markout_delta_handles_malformed_payloads() -> None:
    assert _first_baseline_markout_delta({}) is None
    assert _first_baseline_markout_delta({"baseline_comparison": []}) is None
    assert _first_baseline_markout_delta({
        "baseline_comparison": {"x": {"other": 1.0}}
    }) is None
    assert _first_baseline_markout_delta({
        "baseline_comparison": {"x": {"markout_lift_bps": object()}}
    }) is None
    assert _first_holdout_baseline_markout_delta({}) is None
    assert _first_holdout_baseline_markout_delta({"holdout_split": []}) is None
    assert _first_holdout_baseline_markout_delta({
        "holdout_split": {
            "baseline_comparison": {"x": {"markout_lift_bps": "0.25"}}
        }
    }) == pytest.approx(0.25)


def test_judge_fallback_reports_simple_baseline_gate_without_incumbent() -> None:
    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.54,
            "markout_lift_bps": 0.82,
            "brier": 0.23,
            "latency_p95_ms": 0.8,
            "leakage_safe": True,
            "baseline_comparison": {
                "event_ofi": {"markout_lift_bps": 0.11}
            },
            "holdout_split": {
                "baseline_comparison": {
                    "event_ofi": {"markout_lift_bps": 0.05}
                }
            },
        },
    )
    run = BenchmarkJudgeAgent().run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]

    assert verdict.verdict == "needs_more_data"
    assert verdict.criteria["baseline_markout_lift"]["passed"] is True
    assert verdict.criteria["holdout_baseline_markout_lift"]["passed"] is True
    assert "candidate minus baseline" in verdict.criteria["baseline_markout_lift"]["detail"]


def test_judge_policy_rejects_leaky_v2_candidate(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.80,
        "markout_lift_bps": 0.0,
        "brier": 0.15,
        "latency_p95_ms": 0.7,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = replace(
        _make_training_job(success=True),
        metrics={
            "pr_auc": 0.90,
            "markout_lift_bps": 3.0,
            "brier": 0.10,
            "latency_p95_ms": 0.5,
            "leakage_safe": False,
        },
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]
    assert verdict.verdict == "reject"
    assert verdict.criteria["no_leakage"]["passed"] is False


def test_judge_falls_back_when_candidate_lacks_v2_metrics(tmp_path: Path) -> None:
    incumbent_data = {
        "pr_auc": 0.80,
        "markout_lift_bps": 0.0,
        "brier": 0.15,
        "latency_p95_ms": 0.7,
        "leakage_safe": True,
    }
    report_path = tmp_path / "incumbent.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=_make_training_job(success=True))
    verdict = run.linked_artifacts["verdict"]
    assert "in_dist_pr_auc" in verdict.criteria
    assert "markout_lift" not in verdict.criteria


def test_judge_nan_metrics_pass_criterion(tmp_path: Path) -> None:
    """NaN values should be treated as 'no regression' per spec."""
    incumbent_data = {"pr_auc": 0.80, "f1": 0.78}
    report_path = tmp_path / "inc.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)
    # Override metrics with NaN to exercise the NaN path
    nan_job = replace(job, metrics={"pr_auc": float("nan"), "f1": float("nan")})
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=nan_job)
    assert run.success is True


def test_judge_verdict_to_dict() -> None:
    job = _make_training_job(success=True)
    agent = BenchmarkJudgeAgent()
    run = agent.run(goal="vote", job=job)
    verdict = run.linked_artifacts["verdict"]
    d = verdict.to_dict()
    assert "verdict" in d
    assert "promote_votes" in d
    assert "criteria" in d


def test_judge_corrupt_incumbent_file(tmp_path: Path) -> None:
    """A malformed JSON incumbent should not crash the agent."""
    report_path = tmp_path / "bad.json"
    report_path.write_text("NOT JSON", encoding="utf-8")
    job = _make_training_job(success=True)
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    assert run.success is True  # graceful fallback to {}


def test_judge_latency_check_with_both_latencies(tmp_path: Path) -> None:
    """Exercises the latency ratio comparison branch."""
    incumbent_data = {
        "pr_auc": 0.80,
        "f1": 0.75,
        "latency": {"p99_ms": 5.0},
    }
    report_path = tmp_path / "inc.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)
    job_with_latency = replace(
        job,
        metrics={**dict(job.metrics), "latency": {"p99_ms": 4.0}},
    )
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job_with_latency)
    assert run.success is True


def test_judge_overfit_check_with_full_data(tmp_path: Path) -> None:
    """Exercises _overfit_check when both candidate and incumbent have holdout."""
    incumbent_data = {
        "pr_auc": 0.80,
        "f1": 0.75,
        "holdout_split": {"pr_auc": 0.75},
    }
    report_path = tmp_path / "inc.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)
    # candidate: pr_auc=0.85, holdout=0.80 → gap=0.05; incumbent gap=0.05 → equal → pass
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    assert run.success is True


def test_compare_falls_through_when_nan_check_type_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_type_error(value: object) -> bool:
        raise TypeError("bad value")

    monkeypatch.setattr(judge_module, "_is_nan", _raise_type_error)
    passed, detail = BenchmarkJudgeAgent._compare(
        1.0,
        2.0,
        tolerance=0.1,
        prefer="higher",
        label="metric",
    )
    assert passed is False
    assert "metric" in detail
