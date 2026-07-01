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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from marketimmune.agentic.base import Agent
from marketimmune.agentic.memory import ImmuneMemory

TrainingMode = Literal["synthetic_risk_head", "hyperliquid_markout"]


@dataclass(frozen=True, slots=True)
class HyperliquidTrainingSpec:
    """Configuration for one real-data Hyperliquid markout training run."""

    coin: str = "SOL"
    date: str = "20260601"
    coins: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    holdout_coins: tuple[str, ...] = ()
    holdout_dates: tuple[str, ...] = ()
    horizon: str = "10s"
    lake_root: Path = Path("data/hyperliquid")
    n_splits: int = 5
    purge_ms: float = 60_000.0
    embargo_ms: float = 60_000.0
    iterations: int = 150
    learning_rate: float = 0.08
    depth: int = 6
    calibration_fraction: float = 0.2
    max_rows: int = 0

    @property
    def dataset_version(self) -> str:
        return f"hyperliquid:{self.coin_label}:{self.date_label}:{self.horizon}"

    @property
    def model_name(self) -> str:
        return f"CatBoostMarkout-{self.coin_label}-{self.horizon}-candidate"

    @property
    def coin_label(self) -> str:
        return "-".join(coin.upper() for coin in self.coins) if self.coins else self.coin.upper()

    @property
    def date_label(self) -> str:
        return "-".join(self.dates) if self.dates else self.date


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
    artifact_paths: Mapping[str, str] = field(default_factory=dict)

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
            "artifact_paths": dict(self.artifact_paths),
        }


class ModelTrainerAgent(Agent):
    """Decides whether to retrain and runs the training script if so."""

    name = "ModelTrainerAgent"
    description = "Triggers and supervises retraining of the risk head."

    DEFAULT_MIN_NEW_MEMORIES = 1
    DEFAULT_MODEL_PATH = Path("data/models/risk_head.joblib")
    DEFAULT_REPORT_PATH = Path("reports/risk_head_benchmark.json")
    DEFAULT_SCRIPT = Path("scripts/train_risk_head.py")
    DEFAULT_HYPERLIQUID_SCRIPT = Path("scripts/train_hyperliquid_markout.py")
    DEFAULT_CANDIDATE_MODEL_DIR = Path("data/models/candidates")
    DEFAULT_CANDIDATE_REPORT_DIR = Path("reports/candidates")

    def __init__(
        self,
        *,
        min_new_memories: int = DEFAULT_MIN_NEW_MEMORIES,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        report_path: Path | str = DEFAULT_REPORT_PATH,
        script: Path | str = DEFAULT_SCRIPT,
        training_mode: TrainingMode = "synthetic_risk_head",
        hyperliquid_script: Path | str = DEFAULT_HYPERLIQUID_SCRIPT,
        hyperliquid_spec: HyperliquidTrainingSpec | None = None,
        candidate_model_dir: Path | str = DEFAULT_CANDIDATE_MODEL_DIR,
        candidate_report_dir: Path | str = DEFAULT_CANDIDATE_REPORT_DIR,
        python_executable: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.min_new_memories = min_new_memories
        self.model_path = Path(model_path)
        self.report_path = Path(report_path)
        self.script = Path(script)
        self.training_mode = training_mode
        self.hyperliquid_script = Path(hyperliquid_script)
        self.hyperliquid_spec = hyperliquid_spec or HyperliquidTrainingSpec()
        self.candidate_model_dir = Path(candidate_model_dir)
        self.candidate_report_dir = Path(candidate_report_dir)
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
                    f"Found {len(new_memories)} new "
                    f"{'memory' if len(new_memories) == 1 else 'memories'}; "
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
                "artifacts": {"job": None},
            }

        job = self._run_training(triggered_by=triggered_by, goal=goal)
        return {
            "output": {
                "ran_training": True,
                "triggered_by": triggered_by,
                "job": job.to_dict(),
            },
            "artifacts": {"job": job},
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
            return f"{len(new_memories)}_new_memories", True
        return "no_trigger", False

    # ---- training execution ---------------------------------------

    def _run_training(self, *, triggered_by: str, goal: str) -> TrainingJob:
        if self.training_mode == "hyperliquid_markout":
            return self._run_hyperliquid_training(triggered_by=triggered_by, goal=goal)
        return self._run_synthetic_training(triggered_by=triggered_by, goal=goal)

    def _run_synthetic_training(self, *, triggered_by: str, goal: str) -> TrainingJob:
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

    def _run_hyperliquid_training(self, *, triggered_by: str, goal: str) -> TrainingJob:
        job_id = f"train_{uuid.uuid4().hex[:10]}"
        spec = self.hyperliquid_spec
        incumbent_model = self._load_incumbent_name()
        self.candidate_model_dir.mkdir(parents=True, exist_ok=True)
        self.candidate_report_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = (
            self.candidate_model_dir
            / f"{job_id}-{spec.coin_label}-{spec.horizon}.cbm"
        )
        candidate_report = (
            self.candidate_report_dir
            / f"{job_id}-{spec.coin_label}-{spec.date_label}-{spec.horizon}.json"
        )
        candidate_calibrator = candidate_path.with_suffix(".isotonic.json")
        command = self._hyperliquid_command(
            spec=spec,
            candidate_path=candidate_path,
            candidate_report=candidate_report,
            candidate_calibrator=candidate_calibrator,
        )
        self.record_tool_call(
            "subprocess.run",
            arguments={
                "command": list(command),
                "trigger": triggered_by,
                "training_mode": self.training_mode,
            },
            result_summary="launching Hyperliquid CatBoost candidate training",
        )
        started_at = time.time()
        try:
            proc = subprocess.run(
                command,
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
            )
        except subprocess.TimeoutExpired as exc:
            self.record_trace(
                goal=goal,
                observation=f"Hyperliquid training timed out after {exc.timeout}s.",
                decision="abort_retraining",
                confidence=0.1,
            )
            return TrainingJob(
                job_id=job_id,
                triggered_by=triggered_by,
                candidate_model=spec.model_name,
                incumbent_model=incumbent_model,
                dataset_version=spec.dataset_version,
                command=command,
                metrics={},
                holdout_metrics=None,
                success=False,
                error=f"timeout after {exc.timeout}s",
                started_at=started_at,
                finished_at=time.time(),
                artifact_paths=_artifact_paths(
                    candidate_path,
                    candidate_report,
                    candidate_calibrator,
                ),
            )
        finished_at = time.time()
        if proc.returncode != 0:
            self.record_trace(
                goal=goal,
                observation=(
                    f"Hyperliquid training subprocess exited {proc.returncode}: "
                    f"{proc.stderr.strip()[:400]}"
                ),
                decision="abort_retraining",
                confidence=0.1,
            )
            return TrainingJob(
                job_id=job_id,
                triggered_by=triggered_by,
                candidate_model=spec.model_name,
                incumbent_model=incumbent_model,
                dataset_version=spec.dataset_version,
                command=command,
                metrics={},
                holdout_metrics=None,
                success=False,
                error=proc.stderr.strip()[:1000],
                started_at=started_at,
                finished_at=finished_at,
                artifact_paths=_artifact_paths(
                    candidate_path,
                    candidate_report,
                    candidate_calibrator,
                ),
            )

        metrics, holdout = self._parse_report(candidate_report)
        baseline_delta_bps = _baseline_delta_bps(metrics)
        baseline_fragment = (
            f", baseline delta {baseline_delta_bps:+.3f} bps"
            if baseline_delta_bps is not None
            else ""
        )
        self.record_trace(
            goal=goal,
            observation=(
                f"Hyperliquid candidate trained on {spec.dataset_version}: "
                f"PR-AUC {_metric(metrics, 'pr_auc'):.3f}, "
                f"markout lift {_metric(metrics, 'markout_lift_bps'):.3f} bps"
                f"{baseline_fragment}."
            ),
            decision="emit_training_job",
            confidence=0.88,
            evidence={
                "trigger": triggered_by,
                "training_mode": self.training_mode,
                "report": str(candidate_report),
                "model": str(candidate_path),
                "calibrator": str(candidate_calibrator),
            },
        )
        return TrainingJob(
            job_id=job_id,
            triggered_by=triggered_by,
            candidate_model=spec.model_name,
            incumbent_model=incumbent_model,
            dataset_version=spec.dataset_version,
            command=command,
            metrics=metrics,
            holdout_metrics=holdout,
            success=True,
            started_at=started_at,
            finished_at=finished_at,
            artifact_paths=_artifact_paths(
                candidate_path,
                candidate_report,
                candidate_calibrator,
            ),
        )

    def _hyperliquid_command(
        self,
        *,
        spec: HyperliquidTrainingSpec,
        candidate_path: Path,
        candidate_report: Path,
        candidate_calibrator: Path,
    ) -> tuple[str, ...]:
        command = [
            self.python_executable,
            str(self.hyperliquid_script),
            "--horizon",
            spec.horizon,
            "--lake-root",
            str(spec.lake_root),
            "--n-splits",
            str(spec.n_splits),
            "--purge-ms",
            str(spec.purge_ms),
            "--embargo-ms",
            str(spec.embargo_ms),
            "--iterations",
            str(spec.iterations),
            "--learning-rate",
            str(spec.learning_rate),
            "--depth",
            str(spec.depth),
            "--calibration-fraction",
            str(spec.calibration_fraction),
            "--report",
            str(candidate_report),
            "--model-out",
            str(candidate_path),
            "--calibrator-out",
            str(candidate_calibrator),
        ]
        if spec.coins:
            command.extend(["--coins", ",".join(spec.coins)])
        else:
            command.extend(["--coin", spec.coin])
        if spec.dates:
            command.extend(["--dates", ",".join(spec.dates)])
        else:
            command.extend(["--date", spec.date])
        if spec.holdout_coins:
            command.extend(["--holdout-coins", ",".join(spec.holdout_coins)])
        if spec.holdout_dates:
            command.extend(["--holdout-dates", ",".join(spec.holdout_dates)])
        if spec.max_rows > 0:
            command.extend(["--max-rows", str(spec.max_rows)])
        return tuple(command)

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
    def _parse_report(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
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


def _metric(metrics: Mapping[str, Any], key: str) -> float:
    try:
        return float(metrics[key])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def _artifact_paths(
    candidate_path: Path,
    candidate_report: Path,
    candidate_calibrator: Path | None = None,
) -> dict[str, str]:
    paths = {
        "model": str(candidate_path),
        "report": str(candidate_report),
    }
    if candidate_calibrator is not None:
        paths["calibrator"] = str(candidate_calibrator)
    return paths


def _baseline_delta_bps(metrics: Mapping[str, Any]) -> float | None:
    comparison = metrics.get("baseline_comparison")
    if not isinstance(comparison, Mapping):
        return None
    for value in comparison.values():
        if isinstance(value, Mapping) and "markout_lift_bps" in value:
            return _metric(value, "markout_lift_bps")
    return None
