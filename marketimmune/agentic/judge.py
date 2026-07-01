"""BenchmarkJudgeAgent — votes on whether a candidate model should be promoted.

Voting rules
============

When real v2 promotion metrics are present, the Judge delegates to
``PromotionPolicy`` so leakage safety, markout lift, calibration, latency, and PR-AUC
are evaluated in one place. If either side lacks those metrics, the Judge falls back to
the legacy five-criterion benchmark vote below.

Each criterion contributes one vote. Three or more "promote" votes →
``promote``; one or two "promote" votes → ``needs_more_data``; zero →
``reject``.

* **PR-AUC (in-distribution)**: candidate must match incumbent within
  -0.005 (a strict regression guard).
* **Held-out PR-AUC**: candidate must beat incumbent by at least
  ``min_holdout_improvement`` (default 0.01). This is the single most
  important criterion because it measures real generalisation.
* **F1**: candidate within -0.01 of incumbent.
* **Latency p99**: candidate within +30% of incumbent. We refuse to
  promote a model that is dramatically slower at inference.
* **Overfit gap**: ``in_dist_pr_auc - holdout_pr_auc`` must not have
  gotten worse by more than ``max_overfit_regression`` (default 0.05).

The Judge never modifies any artifact — it just emits a decision.
Promotion (copying the candidate joblib over the incumbent path) is
handled by the orchestrator if and only if the verdict is ``promote``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.agentic.trainer import TrainingJob
from marketimmune.models.promotion import (
    ModelMetrics,
    PromotionPolicy,
    PromotionVerdict,
)


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """The Judge's structured decision."""

    decision_id: str
    verdict: str  # promote | reject | needs_more_data
    candidate_model: str
    incumbent_model: str
    promote_votes: int
    reject_votes: int
    rationale: str
    metrics: Mapping[str, Any]
    criteria: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "verdict": self.verdict,
            "candidate_model": self.candidate_model,
            "incumbent_model": self.incumbent_model,
            "promote_votes": self.promote_votes,
            "reject_votes": self.reject_votes,
            "rationale": self.rationale,
            "metrics": dict(self.metrics),
            "criteria": dict(self.criteria),
        }


class BenchmarkJudgeAgent(Agent):
    """Compares a candidate against the incumbent and votes."""

    name = "BenchmarkJudgeAgent"
    description = "Casts five-criterion vote on whether to promote a candidate."

    DEFAULT_REPORT_PATH = Path("reports/risk_head_benchmark.json")

    def __init__(
        self,
        *,
        incumbent_report: Path | str = DEFAULT_REPORT_PATH,
        min_pr_auc_regression: float = 0.005,
        min_f1_regression: float = 0.01,
        min_holdout_improvement: float = 0.01,
        max_latency_inflation: float = 0.30,
        max_overfit_regression: float = 0.05,
        promotion_policy: PromotionPolicy | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.incumbent_report = Path(incumbent_report)
        self.min_pr_auc_regression = min_pr_auc_regression
        self.min_f1_regression = min_f1_regression
        self.min_holdout_improvement = min_holdout_improvement
        self.max_latency_inflation = max_latency_inflation
        self.max_overfit_regression = max_overfit_regression
        self.promotion_policy = promotion_policy or PromotionPolicy()

    # ---- subclass contract ----------------------------------------

    def _execute(
        self,
        *,
        goal: str,
        job: TrainingJob | None = None,
        **_: Any,
    ) -> Mapping[str, Any]:
        if job is None:
            self.record_trace(
                goal=goal,
                observation="No candidate training job was supplied; nothing to judge.",
                decision="skip",
                confidence=0.5,
            )
            return {
                "output": {"verdict": None, "skipped": True},
                "artifacts": {"verdict": None},
            }
        if not job.success:
            verdict = JudgeVerdict(
                decision_id=f"judge_{job.job_id}",
                verdict="reject",
                candidate_model=job.candidate_model,
                incumbent_model=job.incumbent_model,
                promote_votes=0,
                reject_votes=5,
                rationale=f"Training job failed: {job.error or 'unknown error'}.",
                metrics={},
                criteria={"training_succeeded": False},
            )
            self.record_trace(
                goal=goal,
                observation="Training failed; auto-rejecting candidate.",
                decision="reject",
                confidence=0.95,
            )
            return {
                "output": {"verdict": verdict.to_dict()},
                "artifacts": {"verdict": verdict},
            }

        incumbent = self._load_incumbent()
        policy_verdict = self._evaluate_promotion_policy(job, incumbent)
        if policy_verdict is not None:
            return self._emit_policy_verdict(
                goal=goal,
                job=job,
                incumbent=incumbent,
                policy_verdict=policy_verdict,
            )

        criteria = self._evaluate_criteria(job, incumbent)
        promote_votes = sum(1 for c in criteria.values() if c["passed"])

        if promote_votes >= 3:
            verdict_label = "promote"
        elif promote_votes >= 1:
            verdict_label = "needs_more_data"
        else:
            verdict_label = "reject"
        criteria, verdict_label = _apply_baseline_gate(
            criteria,
            default_verdict=verdict_label,
            candidate_metrics=job.metrics,
        )
        promote_votes = sum(1 for c in criteria.values() if c["passed"])
        reject_votes = len(criteria) - promote_votes

        rationale_bits = [
            f"{name}: {('PASS' if c['passed'] else 'FAIL')} ({c['detail']})"
            for name, c in criteria.items()
        ]
        rationale = (
            f"Verdict {verdict_label} ({promote_votes}/{len(criteria)} criteria passed). "
            + "; ".join(rationale_bits)
        )

        verdict = JudgeVerdict(
            decision_id=f"judge_{job.job_id}",
            verdict=verdict_label,
            candidate_model=job.candidate_model,
            incumbent_model=job.incumbent_model,
            promote_votes=promote_votes,
            reject_votes=reject_votes,
            rationale=rationale,
            metrics={
                "candidate": dict(job.metrics),
                "candidate_holdout": dict(job.holdout_metrics or {}),
                "incumbent": incumbent,
            },
            criteria=criteria,
        )
        self.record_trace(
            goal=goal,
            observation=rationale[:280],
            decision=verdict_label,
            confidence=min(0.95, 0.5 + 0.1 * promote_votes),
            evidence={"votes": f"{promote_votes}/{len(criteria)}"},
        )
        return {
            "output": {"verdict": verdict.to_dict()},
            "artifacts": {"verdict": verdict},
        }

    # ---- helpers --------------------------------------------------

    def _load_incumbent(self) -> dict[str, Any]:
        if not self.incumbent_report.exists():
            return {}
        try:
            return dict(json.loads(self.incumbent_report.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            return {}

    def _evaluate_criteria(
        self, job: TrainingJob, incumbent: Mapping[str, Any]
    ) -> dict[str, dict[str, Any]]:
        cand = job.metrics
        cand_holdout = job.holdout_metrics or {}
        inc_holdout = incumbent.get("holdout_split") or {}

        in_dist_passed, in_dist_detail = self._compare(
            cand.get("pr_auc"), incumbent.get("pr_auc"),
            tolerance=self.min_pr_auc_regression, prefer="higher",
            label="in-dist PR-AUC",
        )
        f1_passed, f1_detail = self._compare(
            cand.get("f1"), incumbent.get("f1"),
            tolerance=self.min_f1_regression, prefer="higher",
            label="F1",
        )
        holdout_passed, holdout_detail = self._compare(
            cand_holdout.get("pr_auc"), inc_holdout.get("pr_auc"),
            tolerance=-self.min_holdout_improvement, prefer="higher",
            label="held-out PR-AUC",
        )
        latency_passed, latency_detail = self._latency_check(
            cand_p99=(cand.get("latency") or {}).get("p99_ms"),
            inc_p99=(incumbent.get("latency") or {}).get("p99_ms"),
        )
        overfit_passed, overfit_detail = self._overfit_check(
            cand_in=cand.get("pr_auc"),
            cand_hold=cand_holdout.get("pr_auc"),
            inc_in=incumbent.get("pr_auc"),
            inc_hold=inc_holdout.get("pr_auc"),
        )
        return {
            "in_dist_pr_auc": {"passed": in_dist_passed, "detail": in_dist_detail},
            "f1": {"passed": f1_passed, "detail": f1_detail},
            "holdout_pr_auc": {"passed": holdout_passed, "detail": holdout_detail},
            "latency_p99": {"passed": latency_passed, "detail": latency_detail},
            "overfit_gap": {"passed": overfit_passed, "detail": overfit_detail},
        }

    def _evaluate_promotion_policy(
        self, job: TrainingJob, incumbent: Mapping[str, Any]
    ) -> PromotionVerdict | None:
        champion = _promotion_metrics_from_mapping(incumbent)
        if champion is None:
            return None
        challenger = _promotion_metrics_from_mapping(job.metrics)
        if challenger is None:
            return None
        return self.promotion_policy.evaluate(champion, challenger)

    def _emit_policy_verdict(
        self,
        *,
        goal: str,
        job: TrainingJob,
        incumbent: Mapping[str, Any],
        policy_verdict: PromotionVerdict,
    ) -> Mapping[str, Any]:
        criteria = {
            name: {"passed": criterion.passed, "detail": criterion.detail}
            for name, criterion in policy_verdict.criteria.items()
        }
        criteria, verdict_label = _apply_baseline_gate(
            criteria,
            default_verdict=policy_verdict.verdict,
            candidate_metrics=job.metrics,
        )
        passed = sum(1 for item in criteria.values() if item["passed"])
        total = len(criteria)
        rationale = (
            f"PromotionPolicy verdict {verdict_label} "
            f"({passed}/{total} criteria passed). "
            + "; ".join(
                f"{name}: {('PASS' if item['passed'] else 'FAIL')} ({item['detail']})"
                for name, item in criteria.items()
            )
        )
        verdict = JudgeVerdict(
            decision_id=f"judge_{job.job_id}",
            verdict=verdict_label,
            candidate_model=job.candidate_model,
            incumbent_model=job.incumbent_model,
            promote_votes=passed,
            reject_votes=total - passed,
            rationale=rationale,
            metrics={
                "candidate": dict(job.metrics),
                "candidate_holdout": dict(job.holdout_metrics or {}),
                "incumbent": dict(incumbent),
                "policy": "PromotionPolicy",
            },
            criteria=criteria,
        )
        self.record_trace(
            goal=goal,
            observation=rationale[:280],
            decision=verdict_label,
            confidence=min(0.95, 0.55 + 0.08 * passed),
            evidence={"votes": f"{passed}/{total}"},
        )
        return {
            "output": {"verdict": verdict.to_dict()},
            "artifacts": {"verdict": verdict},
        }

    @staticmethod
    def _compare(
        candidate: float | None, incumbent: float | None, *,
        tolerance: float, prefer: str, label: str,
    ) -> tuple[bool, str]:
        """Returns (passed, human-readable detail)."""
        if candidate is None or incumbent is None:
            return False, f"{label}: missing data"
        try:
            if any(_is_nan(x) for x in (candidate, incumbent)):
                return True, f"{label}: NaN treated as no-regression"
        except TypeError:
            pass
        delta = candidate - incumbent if prefer == "higher" else incumbent - candidate
        passed = delta >= -tolerance
        return passed, (
            f"{label}: candidate={candidate:.3f} vs incumbent={incumbent:.3f} "
            f"(Δ={delta:+.3f}, tolerance={-tolerance:+.3f})"
        )

    def _latency_check(
        self, cand_p99: float | None, inc_p99: float | None
    ) -> tuple[bool, str]:
        if cand_p99 is None or inc_p99 is None or inc_p99 <= 0:
            return True, "latency: no incumbent baseline; passing by default"
        ratio = cand_p99 / inc_p99
        passed = ratio <= 1.0 + self.max_latency_inflation
        return passed, (
            f"latency p99: candidate={cand_p99:.2f}ms incumbent={inc_p99:.2f}ms "
            f"({ratio:.2f}× incumbent, cap={1.0 + self.max_latency_inflation:.2f}×)"
        )

    def _overfit_check(
        self,
        cand_in: float | None,
        cand_hold: float | None,
        inc_in: float | None,
        inc_hold: float | None,
    ) -> tuple[bool, str]:
        if cand_in is None or cand_hold is None or _is_nan(cand_in) or _is_nan(cand_hold):
            return True, "overfit: missing held-out data; passing"
        cand_gap = cand_in - cand_hold
        if inc_in is None or inc_hold is None or _is_nan(inc_in) or _is_nan(inc_hold):
            return True, f"overfit: incumbent gap unknown; candidate gap={cand_gap:.3f}"
        inc_gap = inc_in - inc_hold
        passed = cand_gap <= inc_gap + self.max_overfit_regression
        return passed, (
            f"overfit gap: candidate={cand_gap:.3f} vs incumbent={inc_gap:.3f} "
            f"(regression cap={self.max_overfit_regression:.3f})"
        )


def _is_nan(value: Any) -> bool:
    try:
        return bool(value != value)  # NaN is the only float with this property
    except TypeError:
        return False


def _promotion_metrics_from_mapping(metrics: Mapping[str, Any]) -> ModelMetrics | None:
    try:
        return ModelMetrics(
            pr_auc=float(metrics["pr_auc"]),
            markout_lift_bps=float(metrics["markout_lift_bps"]),
            brier=float(metrics["brier"]),
            latency_p95_ms=float(metrics["latency_p95_ms"]),
            leakage_safe=metrics["leakage_safe"] is True,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _apply_baseline_gate(
    criteria: dict[str, dict[str, Any]],
    *,
    default_verdict: str,
    candidate_metrics: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Require candidate markout lift to beat any reported simple baseline."""
    out = dict(criteria)
    verdict = default_verdict
    delta = _first_baseline_markout_delta(candidate_metrics)
    if delta is not None:
        passed = delta >= 0.0
        out["baseline_markout_lift"] = {
            "passed": passed,
            "detail": f"candidate minus baseline = {delta:+.3f} bps",
        }
        if not passed:
            verdict = "reject"
    holdout_delta = _first_holdout_baseline_markout_delta(candidate_metrics)
    if holdout_delta is not None:
        passed = holdout_delta >= 0.0
        out["holdout_baseline_markout_lift"] = {
            "passed": passed,
            "detail": f"holdout candidate minus baseline = {holdout_delta:+.3f} bps",
        }
        if not passed:
            verdict = "reject"
    if verdict == "reject":
        return out, "reject"
    has_baseline_gate = delta is not None or holdout_delta is not None
    if has_baseline_gate and default_verdict == "promote":
        return out, "promote"
    return out, default_verdict


def _first_baseline_markout_delta(metrics: Mapping[str, Any]) -> float | None:
    comparison = metrics.get("baseline_comparison")
    return _first_markout_delta(comparison)


def _first_holdout_baseline_markout_delta(metrics: Mapping[str, Any]) -> float | None:
    holdout = metrics.get("holdout_split")
    if not isinstance(holdout, Mapping):
        return None
    return _first_markout_delta(holdout.get("baseline_comparison"))


def _first_markout_delta(comparison: Any) -> float | None:
    if not isinstance(comparison, Mapping):
        return None
    for value in comparison.values():
        if isinstance(value, Mapping) and "markout_lift_bps" in value:
            try:
                return float(value["markout_lift_bps"])
            except (TypeError, ValueError):
                return None
    return None
