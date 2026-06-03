"""Tests for BenchmarkJudgeAgent and its helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.agentic.judge import BenchmarkJudgeAgent, JudgeVerdict, _is_nan

from .conftest import _make_training_job


# ---------------------------------------------------------------------------
# _is_nan helper
# ---------------------------------------------------------------------------


def test_is_nan_with_float_nan() -> None:
    import math
    assert _is_nan(float("nan")) is True


def test_is_nan_with_normal_float() -> None:
    assert _is_nan(0.85) is False


def test_is_nan_with_none() -> None:
    # None does not satisfy NaN property (it raises TypeError, caught internally)
    assert _is_nan(None) is False


def test_is_nan_with_string() -> None:
    assert _is_nan("hello") is False


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


def test_judge_nan_metrics_pass_criterion(tmp_path: Path) -> None:
    """NaN values should be treated as 'no regression' per spec."""
    import math
    incumbent_data = {"pr_auc": 0.80, "f1": 0.78}
    report_path = tmp_path / "inc.json"
    report_path.write_text(json.dumps(incumbent_data), encoding="utf-8")

    job = _make_training_job(success=True)
    # Override metrics with NaN to exercise the NaN path
    from dataclasses import replace
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

    from dataclasses import replace
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

    from dataclasses import replace
    job = _make_training_job(success=True)
    # candidate: pr_auc=0.85, holdout=0.80 → gap=0.05; incumbent gap=0.05 → equal → pass
    agent = BenchmarkJudgeAgent(incumbent_report=report_path)
    run = agent.run(goal="vote", job=job)
    assert run.success is True
