"""ModelTrainerAgent — prepares and runs a candidate retraining job.

Trigger conditions
==================

The agent retrains when at least one of the following is true:

* A configurable threshold of *new memories* has been added since the
  active model was trained (default ``min_new_memories=1``). Each new
  memory represents a threat pattern the system has decided is worth
  remembering — strong signal that retraining is justified.
* The Judge has previously rejected a candidate but flagged it as
  ``needs_more_data`` (recorded as a ``ModelPromotionDecision``).
* The operator passes ``force=True`` (used for the first run).

Output value object
===================

The agent does **not** persist anything itself — it returns a
:class:`TrainingJob` that the orchestrator hands to the Judge. This
keeps the agent stateless and easy to test without a DB.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.agentic.memory import ImmuneMemory


@dataclass(frozen=True, slots=True)
class TrainingJob:
    """One retraining attempt."""

    job_id: str
    triggered_by: str
    candidate_model: str
    incumbent_model: str
    dataset_version: str
    command: tuple[str, ...]
    metrics: Mapping[str, Any]
    holdout_metrics: Mapping[str, Any] | None
    success: bool
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "triggered_by": self.triggered_by,
            "candidate_model": self.candidate_model,
            "incumbent_model": self.incumbent_model,
            "dataset_version": self.dataset_version,
            "command": list(self.command),
            "metrics": dict(self.metrics),
            "holdout_metrics": (
                dict(self.holdout_metrics) if self.holdout_metrics else None
            ),
            "success": self.success,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class ModelTrainerAgent(Agent):
    """Decides whether to retrain and runs the training script if so."""

    name = "ModelTrainerAgent"
    description = "Triggers and supervises retraining of the risk head."

    DEFAULT_MIN_NEW_MEMORIES = 1
    DEFAULT_MODEL_PATH = Path("data/models/risk_head.joblib")
    DEFAULT_REPORT_PATH = Path("reports/risk_head_benchmark.json")
    DEFAULT_SCRIPT = Path("scripts/train_risk_head.py")

    def __init__(
        self,
        *,
        min_new_memories: int = DEFAULT_MIN_NEW_MEMORIES,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        report_path: Path | str = DEFAULT_REPORT_PATH,
        script: Path | str = DEFAULT_SCRIPT,
        python_executable: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.min_new_memories = min_new_memories
        self.model_path = Path(model_path)
        self.report_path = Path(report_path)
        self.script = Path(script)
        # When a venv is active we want the same interpreter; sys.executable
        # gives us that in a portable way.
        self.python_executable = python_executable or sys.executable

    # ---- subclass contract ----------------------------------------

    def _execute(
        self,
        *,
        goal: str,
        new_memories: Sequence[ImmuneMemory] = (),
        retrain_pending: bool = False,
        force: bool = False,
        **_: Any,
    ) -> Mapping[str, Any]:
        triggered_by, should_train = self._should_train(
            new_memories=new_memories,
            retrain_pending=retrain_pending,
            force=force,
        )
        if not should_train:
            self.record_trace(
                goal=goal,
                observation=(
                    f"Found {len(new_memories)} new memor(y/ies); "
                    f"threshold is {self.min_new_memories}. Not retraining."
                ),
                decision="skip_retraining",
                confidence=0.65,
            )
            return {
                "output": {
                    "ran_training": False,
                    "triggered_by": triggered_by,
                    "job": None,
                },
                "artifacts": {"job": None},  # type: ignore[dict-item]
            }

        job = self._run_training(triggered_by=triggered_by, goal=goal)
        return {
            "output": {
                "ran_training": True,
                "triggered_by": triggered_by,
                "job": job.to_dict(),
            },
            "artifacts": {"job": job},  # type: ignore[dict-item]
        }

    # ---- decision policy ------------------------------------------

    def _should_train(
        self,
        *,
        new_memories: Sequence[ImmuneMemory],
        retrain_pending: bool,
        force: bool,
    ) -> tuple[str, bool]:
        if force:
            return "force_flag", True
        if retrain_pending:
            return "judge_requested_more_data", True
        if len(new_memories) >= self.min_new_memories:
            return f"{len(new_memories)}_new_memor(y/ies)", True
        return "no_trigger", False

    # ---- training execution ---------------------------------------

    def _run_training(self, *, triggered_by: str, goal: str) -> TrainingJob:
        job_id = f"train_{uuid.uuid4().hex[:10]}"
        candidate_model = "GradientBoostingRiskHead-candidate"
        incumbent_model = self._load_incumbent_name()
        dataset_version = f"synthetic-{int(time.time())}"

        # Train into a *separate* artifact path so the incumbent stays
        # the system of record until the Judge promotes the candidate.
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "candidate.joblib"
            candidate_report = Path(tmp) / "candidate_benchmark.json"
            command = (
                self.python_executable,
                str(self.script),
                "--out", str(candidate_path),
                "--report", str(candidate_report),
            )
            self.record_tool_call(
                "subprocess.run",
                arguments={"command": list(command), "trigger": triggered_by},
                result_summary="launching candidate training",
            )
            started_at = time.time()
            try:
                proc = subprocess.run(
                    command,
                    cwd=Path.cwd(),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            except subprocess.TimeoutExpired as exc:
                self.record_trace(
                    goal=goal,
                    observation=f"Training timed out after {exc.timeout}s.",
                    decision="abort_retraining",
                    confidence=0.1,
                )
                return TrainingJob(
                    job_id=job_id,
                    triggered_by=triggered_by,
                    candidate_model=candidate_model,
                    incumbent_model=incumbent_model,
                    dataset_version=dataset_version,
                    command=command,
                    metrics={},
                    holdout_metrics=None,
                    success=False,
                    error=f"timeout after {exc.timeout}s",
                    started_at=started_at,
                    finished_at=time.time(),
                )
            finished_at = time.time()
            if proc.returncode != 0:
                self.record_trace(
                    goal=goal,
                    observation=(
                        f"Training subprocess exited {proc.returncode}: "
                        f"{proc.stderr.strip()[:400]}"
                    ),
                    decision="abort_retraining",
                    confidence=0.1,
                )
                return TrainingJob(
                    job_id=job_id,
                    triggered_by=triggered_by,
                    candidate_model=candidate_model,
                    incumbent_model=incumbent_model,
                    dataset_version=dataset_version,
                    command=command,
                    metrics={},
                    holdout_metrics=None,
                    success=False,
                    error=proc.stderr.strip()[:1000],
                    started_at=started_at,
                    finished_at=finished_at,
                )

            metrics, holdout = self._parse_report(candidate_report)
            self.record_trace(
                goal=goal,
                observation=(
                    f"Candidate trained: in-dist PR-AUC "
                    f"{metrics.get('pr_auc', float('nan')):.3f}, "
                    f"held-out PR-AUC "
                    f"{(holdout or {}).get('pr_auc', float('nan')):.3f}."
                ),
                decision="emit_training_job",
                confidence=0.85,
                evidence={"trigger": triggered_by},
            )
            return TrainingJob(
                job_id=job_id,
                triggered_by=triggered_by,
                candidate_model=candidate_model,
                incumbent_model=incumbent_model,
                dataset_version=dataset_version,
                command=command,
                metrics=metrics,
                holdout_metrics=holdout,
                success=True,
                started_at=started_at,
                finished_at=finished_at,
            )

    # ---- helpers --------------------------------------------------

    def _load_incumbent_name(self) -> str:
        if not self.report_path.exists():
            return "(none)"
        try:
            data = json.loads(self.report_path.read_text(encoding="utf-8"))
            return str(data.get("model_name", "(unknown)"))
        except Exception:  # noqa: BLE001
            return "(unreadable)"

    @staticmethod
    def _parse_report(path: Path) -> tuple[dict, dict | None]:
        if not path.exists():
            return {}, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}, None
        # The training script writes top-level metrics for the
        # in-distribution evaluation and a `holdout_split` block for
        # the honest held-out evaluation.
        return (
            {k: v for k, v in data.items() if k != "holdout_split"},
            data.get("holdout_split"),
        )
