"""PolicyAgent — converts investigation cases into recommended actions.

The policy agent owns the *vocabulary* of actions the system can
recommend. Even though the simulator never executes anything for
real, every action label is one a production exchange surveillance
team would actually use:

  * ``no_action``                     — flow is normal
  * ``monitor``                       — keep watching; collect more data
  * ``warning_alert``                 — notify compliance with low priority
  * ``critical_alert``                — page on-call; immediate review
  * ``block_simulated_agent``         — disconnect the offending agent
  * ``request_human_review``          — escalate to a senior analyst
  * ``add_to_benchmark``              — promote pattern into training data
  * ``request_retraining``            — model failed; retrain candidate

When multiple cases are presented, the policy agent emits one
decision per case AND a single aggregate decision describing the
overall posture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from marketimmune.agentic.base import Agent
from marketimmune.agentic.investigator import InvestigationCase


VALID_ACTIONS: tuple[str, ...] = (
    "no_action",
    "monitor",
    "warning_alert",
    "critical_alert",
    "block_simulated_agent",
    "request_human_review",
    "add_to_benchmark",
    "request_retraining",
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """One policy decision attached to a case."""

    decision_id: str
    case_id: str
    recommended_action: str
    severity: str
    rationale: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "case_id": self.case_id,
            "recommended_action": self.recommended_action,
            "severity": self.severity,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


def _action_for(case: InvestigationCase) -> tuple[str, str]:
    """Map a case to (action, rationale)."""
    sev = case.severity
    if sev == "critical":
        return (
            "block_simulated_agent",
            "Critical severity + high model confidence; halt agent and request review.",
        )
    if sev == "high":
        return (
            "critical_alert",
            "High severity with matched rules; raise priority and review.",
        )
    if sev == "medium":
        return (
            "warning_alert",
            "Medium severity; emit warning and continue monitoring.",
        )
    if case.confidence < 0.3:
        return (
            "monitor",
            "Low model confidence; collect more evidence before acting.",
        )
    return ("no_action", "Within normal envelope; log only.")


class PolicyAgent(Agent):
    """Recommends control actions for each investigation case."""

    name = "PolicyAgent"
    description = "Maps investigation case files into control-action recommendations."

    def _execute(
        self,
        *,
        goal: str,
        cases: Sequence[InvestigationCase] | None = None,
        **_: Any,
    ) -> Mapping[str, Any]:
        if cases is None:
            raise ValueError("PolicyAgent requires `cases`.")
        decisions: list[PolicyDecision] = []
        for case in cases:
            action, rationale = _action_for(case)
            assert action in VALID_ACTIONS, action
            decision = PolicyDecision(
                decision_id=f"dec_{case.case_id}",
                case_id=case.case_id,
                recommended_action=action,
                severity=case.severity,
                rationale=rationale,
                confidence=case.confidence,
            )
            decisions.append(decision)
            self.record_trace(
                goal=goal,
                observation=(
                    f"Case {case.case_id} -> {action} "
                    f"(severity {case.severity}, conf {case.confidence:.2f})."
                ),
                decision=action,
                confidence=case.confidence,
                evidence={"rationale": rationale},
            )

        # Aggregate posture across the batch (the worst case wins).
        if not decisions:
            posture = "no_action"
            posture_reason = "No investigation cases were presented."
        else:
            priorities = {
                "block_simulated_agent": 5,
                "critical_alert": 4,
                "request_human_review": 4,
                "warning_alert": 3,
                "monitor": 2,
                "add_to_benchmark": 2,
                "request_retraining": 2,
                "no_action": 1,
            }
            worst = max(decisions, key=lambda d: priorities.get(d.recommended_action, 0))
            posture = worst.recommended_action
            posture_reason = (
                f"Driven by case {worst.case_id} with action {worst.recommended_action} "
                f"(severity {worst.severity})."
            )

        self.record_trace(
            goal=goal,
            observation=f"Aggregate posture across {len(decisions)} decision(s).",
            decision=posture,
            confidence=max((d.confidence for d in decisions), default=0.0),
            evidence={"posture_reason": posture_reason},
        )
        return {
            "output": {
                "decisions": [d.to_dict() for d in decisions],
                "aggregate_posture": posture,
                "posture_reason": posture_reason,
            },
            "artifacts": {"decisions": decisions},  # type: ignore[dict-item]
        }
