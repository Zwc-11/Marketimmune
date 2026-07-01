"""Champion/challenger promotion policy (v2 plan §6.5).

A pure metric-comparison rule the ``BenchmarkJudge`` agent can delegate to: a challenger
is promoted only if it clears acceptance criteria against the incumbent champion — and a
model that is not leakage-safe is **never** promoted, however good its headline metrics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelMetrics:
    """The metrics a promotion decision compares (``brier`` lower = better-calibrated)."""

    pr_auc: float
    markout_lift_bps: float
    brier: float
    latency_p95_ms: float
    leakage_safe: bool


@dataclass(frozen=True, slots=True)
class Criterion:
    """One acceptance check: whether it passed, plus a human-readable detail."""

    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PromotionVerdict:
    """The outcome: ``promote`` / ``needs_more_data`` / ``reject`` with the breakdown."""

    verdict: str
    passed: int
    total: int
    criteria: dict[str, Criterion]


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Thresholds for promoting a challenger over the champion."""

    min_markout_lift_bps: float = 0.0
    pr_auc_tolerance: float = 0.0
    latency_budget_ms: float = 1.0
    min_criteria: int = 4

    def evaluate(self, champion: ModelMetrics, challenger: ModelMetrics) -> PromotionVerdict:
        """Compare ``challenger`` to ``champion`` and return a promotion verdict."""
        criteria = {
            "markout_lift": Criterion(
                challenger.markout_lift_bps - champion.markout_lift_bps
                >= self.min_markout_lift_bps,
                f"{challenger.markout_lift_bps:.2f} vs {champion.markout_lift_bps:.2f} bps",
            ),
            "pr_auc": Criterion(
                challenger.pr_auc >= champion.pr_auc - self.pr_auc_tolerance,
                f"{challenger.pr_auc:.3f} vs {champion.pr_auc:.3f}",
            ),
            "calibration": Criterion(
                challenger.brier <= champion.brier,
                f"Brier {challenger.brier:.3f} vs {champion.brier:.3f}",
            ),
            "latency": Criterion(
                challenger.latency_p95_ms <= self.latency_budget_ms,
                f"p95 {challenger.latency_p95_ms:.2f} ms <= {self.latency_budget_ms:.2f}",
            ),
            "no_leakage": Criterion(
                challenger.leakage_safe,
                "purged/embargoed CV" if challenger.leakage_safe else "leakage not verified",
            ),
        }
        passed = sum(1 for criterion in criteria.values() if criterion.passed)
        if not challenger.leakage_safe:
            verdict = "reject"
        elif passed >= self.min_criteria:
            verdict = "promote"
        elif passed >= self.min_criteria - 1:
            verdict = "needs_more_data"
        else:
            verdict = "reject"
        return PromotionVerdict(verdict, passed, len(criteria), criteria)
