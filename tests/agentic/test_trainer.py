"""Tests for ModelTrainerAgent."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from marketimmune.agentic.trainer import ModelTrainerAgent, TrainingJob

from .conftest import _make_memory

# ---------------------------------------------------------------------------
# Skip path (not enough memories)
# ---------------------------------------------------------------------------


def test_trainer_skips_when_no_trigger() -> None:
    agent = ModelTrainerAgent(min_new_memories=3)
    run = agent.run(goal="maybe retrain", new_memories=[], retrain_pending=False, force=False)
    assert run.success is True
    assert run.output["ran_training"] is False
    assert run.output["triggered_by"] == "no_trigger"
    assert run.linked_artifacts["job"] is None


def test_trainer_triggers_on_force(tmp_path: Path) -> None:
    """force=True triggers training even with no new memories."""
    # We mock subprocess.run so no actual script runs.
    report = {"pr_auc": 0.85, "f1": 0.82, "holdout_split": {"pr_auc": 0.80}}
    with patch("marketimmune.agentic.trainer.subprocess.run") as mock_run, \
         patch("marketimmune.agentic.trainer.tempfile.TemporaryDirectory") as mock_td:

        # Set up a real temp dir so _parse_report can find the file
        td_path = tmp_path / "tmpdir"
        td_path.mkdir()
        candidate_report = td_path / "candidate_benchmark.json"
        candidate_report.write_text(json.dumps(report), encoding="utf-8")

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=str(td_path))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_td.return_value = mock_ctx

        mock_proc = MagicMock(spec=subprocess.CompletedProcess)
        mock_proc.returncode = 0
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        agent = ModelTrainerAgent(
            script=Path("scripts/train_risk_head.py"),
        )
        run = agent.run(goal="force retrain", new_memories=[], force=True)

    assert run.success is True
    assert run.output["ran_training"] is True
    job = run.linked_artifacts["job"]
    assert isinstance(job, TrainingJob)
    assert job.success is True
    assert job.triggered_by == "force_flag"


def test_trainer_triggers_on_enough_memories() -> None:
    mem = _make_memory()
    with patch("marketimmune.agentic.trainer.subprocess.run") as mock_run, \
         patch("marketimmune.agentic.trainer.tempfile.TemporaryDirectory") as mock_td:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value="/tmp/fake")
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_td.return_value = mock_ctx

        mock_proc = MagicMock(spec=subprocess.CompletedProcess)
        mock_proc.returncode = 1
        mock_proc.stderr = "training failed"
        mock_run.return_value = mock_proc

        agent = ModelTrainerAgent(min_new_memories=1)
        run = agent.run(goal="retrain", new_memories=[mem])

    assert run.success is True
    job = run.linked_artifacts["job"]
    # job is not None even on subprocess failure
    assert job is not None
    assert job.success is False
    assert "training failed" in job.error


def test_trainer_triggers_on_retrain_pending() -> None:
    with patch("marketimmune.agentic.trainer.subprocess.run") as mock_run, \
         patch("marketimmune.agentic.trainer.tempfile.TemporaryDirectory") as mock_td:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value="/tmp/fake")
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_td.return_value = mock_ctx

        mock_proc = MagicMock(spec=subprocess.CompletedProcess)
        mock_proc.returncode = 1
        mock_proc.stderr = "error"
        mock_run.return_value = mock_proc

        agent = ModelTrainerAgent()
        run = agent.run(goal="retrain", new_memories=[], retrain_pending=True)

    assert run.success is True
    assert run.output["triggered_by"] == "judge_requested_more_data"


def test_trainer_handles_timeout() -> None:
    with patch("marketimmune.agentic.trainer.subprocess.run") as mock_run, \
         patch("marketimmune.agentic.trainer.tempfile.TemporaryDirectory") as mock_td:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value="/tmp/fake")
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_td.return_value = mock_ctx

        exc = subprocess.TimeoutExpired(cmd=["python"], timeout=300)
        mock_run.side_effect = exc

        agent = ModelTrainerAgent()
        run = agent.run(goal="retrain", force=True)

    assert run.success is True  # Agent catches the exception
    job = run.linked_artifacts["job"]
    assert job is not None
    assert job.success is False
    assert "timeout" in job.error.lower()


# ---------------------------------------------------------------------------
# _load_incumbent_name
# ---------------------------------------------------------------------------


def test_load_incumbent_name_no_file(tmp_path: Path) -> None:
    agent = ModelTrainerAgent(report_path=tmp_path / "nonexistent.json")
    assert agent._load_incumbent_name() == "(none)"


def test_load_incumbent_name_with_file(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"model_name": "TestModel-v2"}), encoding="utf-8")
    agent = ModelTrainerAgent(report_path=report_path)
    assert agent._load_incumbent_name() == "TestModel-v2"


def test_load_incumbent_name_corrupt_file(tmp_path: Path) -> None:
    report_path = tmp_path / "bad.json"
    report_path.write_text("BAD JSON", encoding="utf-8")
    agent = ModelTrainerAgent(report_path=report_path)
    assert agent._load_incumbent_name() == "(unreadable)"


# ---------------------------------------------------------------------------
# _parse_report
# ---------------------------------------------------------------------------


def test_parse_report_nonexistent(tmp_path: Path) -> None:
    metrics, holdout = ModelTrainerAgent._parse_report(tmp_path / "missing.json")
    assert metrics == {}
    assert holdout is None


def test_parse_report_valid(tmp_path: Path) -> None:
    data = {"pr_auc": 0.85, "f1": 0.82, "holdout_split": {"pr_auc": 0.80}}
    p = tmp_path / "report.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    metrics, holdout = ModelTrainerAgent._parse_report(p)
    assert metrics["pr_auc"] == 0.85
    assert holdout is not None
    assert holdout["pr_auc"] == 0.80


def test_parse_report_no_holdout(tmp_path: Path) -> None:
    data = {"pr_auc": 0.85, "f1": 0.82}
    p = tmp_path / "report.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    metrics, holdout = ModelTrainerAgent._parse_report(p)
    assert holdout is None


def test_parse_report_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("INVALID JSON", encoding="utf-8")
    metrics, holdout = ModelTrainerAgent._parse_report(p)
    assert metrics == {}
    assert holdout is None


# ---------------------------------------------------------------------------
# TrainingJob.to_dict
# ---------------------------------------------------------------------------


def test_training_job_to_dict() -> None:
    from .conftest import _make_training_job
    job = _make_training_job()
    d = job.to_dict()
    assert d["success"] is True
    assert "holdout_metrics" in d
    assert d["holdout_metrics"]["pr_auc"] == 0.80


def test_training_job_to_dict_no_holdout() -> None:
    from dataclasses import replace

    from .conftest import _make_training_job
    job = replace(_make_training_job(), holdout_metrics=None)
    d = job.to_dict()
    assert d["holdout_metrics"] is None
