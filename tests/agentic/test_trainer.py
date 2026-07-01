"""Tests for ModelTrainerAgent."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from marketimmune.agentic.trainer import (
    HyperliquidTrainingSpec,
    ModelTrainerAgent,
    TrainingJob,
    _artifact_paths,
    _baseline_delta_bps,
    _metric,
)

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


def test_trainer_runs_hyperliquid_markout_candidate(tmp_path: Path) -> None:
    report = {
        "model_name": "catboost_markout_SOL_10s",
        "pr_auc": 0.54,
        "markout_lift_bps": 0.51,
        "brier": 0.23,
        "latency_p95_ms": 0.42,
        "leakage_safe": True,
        "baseline_comparison": {
            "event_ofi": {"markout_lift_bps": 0.25}
        },
    }

    def fake_run(command: tuple[str, ...], **_: object) -> MagicMock:
        report_path = Path(command[command.index("--report") + 1])
        model_path = Path(command[command.index("--model-out") + 1])
        calibrator_path = Path(command[command.index("--calibrator-out") + 1])
        report_path.parent.mkdir(parents=True, exist_ok=True)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        calibrator_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report), encoding="utf-8")
        model_path.write_bytes(b"model")
        calibrator_path.write_text(json.dumps({"method": "isotonic"}), encoding="utf-8")
        proc = MagicMock(spec=subprocess.CompletedProcess)
        proc.returncode = 0
        proc.stderr = ""
        return proc

    with patch("marketimmune.agentic.trainer.subprocess.run", side_effect=fake_run) as mock_run:
        agent = ModelTrainerAgent(
            training_mode="hyperliquid_markout",
            hyperliquid_spec=HyperliquidTrainingSpec(
                coin="SOL",
                date="20260601",
                horizon="10s",
                lake_root=tmp_path / "lake",
                iterations=7,
                max_rows=100,
            ),
            candidate_model_dir=tmp_path / "models",
            candidate_report_dir=tmp_path / "reports",
        )
        run = agent.run(goal="train real-data candidate", new_memories=[], force=True)

    assert run.success is True
    job = run.linked_artifacts["job"]
    assert isinstance(job, TrainingJob)
    assert job.success is True
    assert job.candidate_model == "CatBoostMarkout-SOL-10s-candidate"
    assert job.dataset_version == "hyperliquid:SOL:20260601:10s"
    assert job.metrics["markout_lift_bps"] == 0.51
    assert "baseline delta +0.250 bps" in run.traces[-1].observation
    assert Path(job.artifact_paths["report"]).exists()
    assert Path(job.artifact_paths["model"]).exists()
    assert Path(job.artifact_paths["calibrator"]).exists()
    command = mock_run.call_args.args[0]
    assert "scripts\\train_hyperliquid_markout.py" in command[1] or (
        "scripts/train_hyperliquid_markout.py" in command[1]
    )
    assert "--calibration-fraction" in command
    assert "--calibrator-out" in command
    assert "--max-rows" in command


def test_trainer_hyperliquid_command_accepts_panel_spec(tmp_path: Path) -> None:
    spec = HyperliquidTrainingSpec(
        coin="SOL",
        date="20260601",
        coins=("SOL", "BTC"),
        dates=("20260601", "20260602"),
        holdout_coins=("SOL",),
        holdout_dates=("20260603",),
        lake_root=tmp_path / "lake",
    )
    agent = ModelTrainerAgent(training_mode="hyperliquid_markout")

    command = agent._hyperliquid_command(
        spec=spec,
        candidate_path=tmp_path / "candidate.cbm",
        candidate_report=tmp_path / "candidate.json",
        candidate_calibrator=tmp_path / "candidate.isotonic.json",
    )

    assert spec.dataset_version == "hyperliquid:SOL-BTC:20260601-20260602:10s"
    assert spec.model_name == "CatBoostMarkout-SOL-BTC-10s-candidate"
    assert command[command.index("--coins") + 1] == "SOL,BTC"
    assert command[command.index("--dates") + 1] == "20260601,20260602"
    assert command[command.index("--holdout-coins") + 1] == "SOL"
    assert command[command.index("--holdout-dates") + 1] == "20260603"
    assert "--coin" not in command
    assert "--date" not in command


def test_trainer_hyperliquid_timeout_returns_failed_job(tmp_path: Path) -> None:
    with patch("marketimmune.agentic.trainer.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["python"], timeout=900)
        agent = ModelTrainerAgent(
            training_mode="hyperliquid_markout",
            candidate_model_dir=tmp_path / "models",
            candidate_report_dir=tmp_path / "reports",
        )
        run = agent.run(goal="train real-data candidate", force=True)

    job = run.linked_artifacts["job"]
    assert job is not None
    assert job.success is False
    assert "timeout" in job.error.lower()
    assert "report" in job.artifact_paths
    assert "calibrator" in job.artifact_paths


def test_trainer_hyperliquid_subprocess_failure_returns_failed_job(tmp_path: Path) -> None:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 2
    proc.stderr = "catboost failed"
    with patch("marketimmune.agentic.trainer.subprocess.run", return_value=proc):
        agent = ModelTrainerAgent(
            training_mode="hyperliquid_markout",
            candidate_model_dir=tmp_path / "models",
            candidate_report_dir=tmp_path / "reports",
        )
        run = agent.run(goal="train real-data candidate", force=True)

    job = run.linked_artifacts["job"]
    assert job is not None
    assert job.success is False
    assert "catboost failed" in job.error


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


def test_metric_returns_nan_for_missing_or_bad_value() -> None:
    assert math.isnan(_metric({}, "pr_auc"))
    assert math.isnan(_metric({"pr_auc": object()}, "pr_auc"))
    assert _metric({"pr_auc": "0.5"}, "pr_auc") == 0.5


def test_baseline_delta_bps_reads_first_reported_baseline() -> None:
    assert _baseline_delta_bps({}) is None
    assert _baseline_delta_bps({"baseline_comparison": {"x": {"other": 1.0}}}) is None
    assert _baseline_delta_bps({
        "baseline_comparison": {
            "event_ofi": {"markout_lift_bps": "0.25"}
        }
    }) == 0.25


def test_artifact_paths_without_optional_calibrator() -> None:
    assert _artifact_paths(Path("model.cbm"), Path("report.json")) == {
        "model": "model.cbm",
        "report": "report.json",
    }


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
    assert d["artifact_paths"] == {}


def test_training_job_to_dict_no_holdout() -> None:
    from dataclasses import replace

    from .conftest import _make_training_job
    job = replace(_make_training_job(), holdout_metrics=None)
    d = job.to_dict()
    assert d["holdout_metrics"] is None
