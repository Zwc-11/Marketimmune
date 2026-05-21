"""RiskSentinelAgent — turns a ReplayPlan into ranked alerts.

Consumes the ticks emitted by :class:`MarketSimulatorAgent` and
returns the high-risk events as structured alerts that downstream
agents (Investigator → Policy → Memory) can act on.

Two scoring paths cooperate:

* the **RuleEngine** is already invoked inside the replay builder
  (each tick already carries ``policy_decision``); the sentinel
  uses that as the discrete severity signal,
* the **ML head** score (``tick.risk_score``) is used to rank the
  alerts so the Investigator looks at the strongest signal first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.simulator.replay_builder import ReplayPlan, ReplayTick


@dataclass(frozen=True, slots=True)
class SentinelAlert:
    """One high-risk event flagged by the sentinel."""

    alert_id: str
    timestamp: str
    risk_score: float
    risk_label: str
    severity: str
    model_name: str
    matched_rules: tuple[str, ...]
    top_features: tuple[str, ...]
    linked_event_id: str
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "timestamp": self.timestamp,
            "risk_score": self.risk_score,
            "risk_label": self.risk_label,
            "severity": self.severity,
            "model_name": self.model_name,
            "matched_rules": list(self.matched_rules),
            "top_features": list(self.top_features),
            "linked_event_id": self.linked_event_id,
            "explanation": self.explanation,
        }


def _severity_for(tick: ReplayTick) -> str:
    if tick.policy_decision == "block":
        return "critical"
    if tick.policy_decision == "alert":
        return "high"
    if tick.risk_score >= 0.45:
        return "medium"
    return "low"


def _top_features_for(tick: ReplayTick) -> tuple[str, ...]:
    """Return the 3 features most likely to have driven this score.

    We use the static importances from the trained model when
    available (encoded by the replay builder into the explanation
    text); otherwise pick the largest raw values from the tick.
    """
    items = sorted(tick.features.items(), key=lambda kv: -float(kv[1]))
    return tuple(k for k, _ in items[:3])


class RiskSentinelAgent(Agent):
    """Surfaces the highest-risk ticks from a ReplayPlan."""

    name = "RiskSentinelAgent"
    description = "Filters and ranks ticks into actionable alerts."

    def _execute(
        self,
        *,
        goal: str,
        plan: ReplayPlan | None = None,
        alert_threshold: float = 0.45,
        top_k: int = 5,
        **_: Any,
    ) -> Mapping[str, Any]:
        if plan is None:
            raise ValueError("RiskSentinelAgent requires a `plan` input.")
        self.record_tool_call(
            "ReplayPlan.scan",
            arguments={"tick_count": len(plan.ticks), "threshold": alert_threshold},
        )

        candidate_alerts = []
        for tick in plan.ticks:
            # The RuleEngine + ML head already cooperated to produce
            # `policy_decision` and `risk_score`. We use both:
            # threshold-or-policy means we never miss a block.
            if tick.risk_score < alert_threshold and tick.policy_decision == "allow":
                continue
            candidate_alerts.append(SentinelAlert(
                alert_id=f"alert_{plan.run_id}_{tick.idx}",
                timestamp=tick.timestamp.isoformat(),
                risk_score=tick.risk_score,
                risk_label=tick.risk_label,
                severity=_severity_for(tick),
                model_name=tick.risk_model_name,
                matched_rules=tick.matched_rules,
                top_features=_top_features_for(tick),
                linked_event_id=tick.kline.event_id or f"ev-{plan.run_id}-{tick.idx}",
                explanation=tick.risk_explanation,
            ))

        # Sort by raw score so the investigator focuses on the worst.
        candidate_alerts.sort(key=lambda a: -a.risk_score)
        top = candidate_alerts[:top_k]

        self.record_trace(
            goal=goal,
            observation=(
                f"Scanned {len(plan.ticks)} ticks; "
                f"{len(candidate_alerts)} crossed threshold; surfacing top {len(top)}."
            ),
            decision=(
                "promote to Investigator" if top else "no escalation; flow looks benign"
            ),
            confidence=0.8 if top else 0.6,
            evidence={
                "total_scanned": len(plan.ticks),
                "above_threshold": len(candidate_alerts),
            },
        )
        return {
            "output": {
                "alerts": [a.to_dict() for a in top],
                "total_above_threshold": len(candidate_alerts),
                "scanned": len(plan.ticks),
            },
            "artifacts": {"alerts": top},  # type: ignore[dict-item]
        }
