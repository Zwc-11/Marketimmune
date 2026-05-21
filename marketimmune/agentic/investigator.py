"""InvestigatorAgent — builds an evidence case file from a sentinel alert.

The Investigator is the most "agentic" of the deterministic agents:
given one alert it reaches back into the simulated tick stream to
collect a small evidence window, summarises the feature evidence,
attaches the model explanation, and emits a structured case file the
:class:`PolicyAgent` can act on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.agentic.sentinel import SentinelAlert
from marketimmune.simulator.replay_builder import ReplayPlan, ReplayTick


@dataclass(frozen=True, slots=True)
class InvestigationCase:
    """A fully-formed evidence package for one suspicious event."""

    case_id: str
    alert_id: str
    suspected_behavior: str
    severity: str
    confidence: float
    observation: str
    feature_evidence: Mapping[str, float]
    model_evidence: Mapping[str, Any]
    timeline: Sequence[Mapping[str, Any]]
    matched_rules: Sequence[str]
    recommended_next_step: str
    explanation: str
    narrative: str = ""
    narrative_source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "alert_id": self.alert_id,
            "suspected_behavior": self.suspected_behavior,
            "severity": self.severity,
            "confidence": self.confidence,
            "observation": self.observation,
            "feature_evidence": dict(self.feature_evidence),
            "model_evidence": dict(self.model_evidence),
            "timeline": [dict(e) for e in self.timeline],
            "matched_rules": list(self.matched_rules),
            "recommended_next_step": self.recommended_next_step,
            "explanation": self.explanation,
            "narrative": self.narrative,
            "narrative_source": self.narrative_source,
        }


_BEHAVIOR_LABELS = {
    "spoofing_layering": "Spoofing / layering",
    "quote_stuffing": "Quote stuffing",
    "momentum_ignition": "Momentum ignition",
}


def _classify_behavior(matched_rules: Sequence[str], features: Mapping[str, float]) -> str:
    rules = set(matched_rules)
    if {"one_sided_sell_pressure", "cancel_rate_spike"} <= rules:
        return _BEHAVIOR_LABELS["spoofing_layering"]
    if {"rapid_order_interarrival", "cancel_rate_spike"} <= rules:
        return _BEHAVIOR_LABELS["quote_stuffing"]
    if {"sharp_buy_price_drift", "stop_run_or_feedback_sweep"} & rules:
        return _BEHAVIOR_LABELS["momentum_ignition"]
    if features.get("w1000_agentic_burst_rate_per_second", 0.0) > 12:
        return "Bursty unsafe agent behavior (unclassified)"
    if features.get("w1000_order_cancel_rate", 0.0) > 0.5:
        return "High cancel-rate behavior"
    return "Generic anomalous flow"


def _next_step(severity: str) -> str:
    if severity == "critical":
        return (
            "Halt simulated agent connection; cancel resting orders; "
            "open formal investigation in the compliance queue."
        )
    if severity == "high":
        return "Raise alert severity and route to active compliance review."
    if severity == "medium":
        return "Monitor for sustained behavior; collect 5-minute evidence window."
    return "No action; log observation only."


class InvestigatorAgent(Agent):
    """Assembles structured case files from sentinel alerts."""

    name = "InvestigatorAgent"
    description = "Builds an evidence case file for each sentinel alert."

    def _execute(
        self,
        *,
        goal: str,
        plan: ReplayPlan | None = None,
        alerts: Sequence[SentinelAlert] | None = None,
        window: int = 3,
        **_: Any,
    ) -> Mapping[str, Any]:
        if plan is None or alerts is None:
            raise ValueError("InvestigatorAgent requires both `plan` and `alerts`.")

        cases: list[InvestigationCase] = []
        ticks_by_id = {f"alert_{plan.run_id}_{t.idx}": t for t in plan.ticks}
        for alert in alerts:
            tick = ticks_by_id.get(alert.alert_id)
            if tick is None:
                self.record_trace(
                    goal=goal,
                    observation=f"Alert {alert.alert_id} has no matching tick; skipping.",
                    decision="skip",
                    confidence=0.2,
                )
                continue

            window_ticks = self._collect_window(plan, tick.idx, window)
            self.record_tool_call(
                "ReplayPlan.window",
                arguments={"idx": tick.idx, "size": window * 2 + 1},
                result_summary=f"collected {len(window_ticks)} ticks",
            )
            behavior = _classify_behavior(tick.matched_rules, tick.features)
            severity = alert.severity
            confidence = min(0.99, 0.4 + tick.risk_score * 0.6)

            narrative, narrative_source = self._build_narrative(
                behavior=behavior,
                severity=severity,
                confidence=confidence,
                tick_obs=tick.observation,
                features=tick.features,
                matched_rules=tick.matched_rules,
                risk_score=tick.risk_score,
                goal=goal,
            )
            case = InvestigationCase(
                case_id=f"case_{plan.run_id}_{tick.idx}",
                alert_id=alert.alert_id,
                suspected_behavior=behavior,
                severity=severity,
                confidence=confidence,
                observation=tick.observation,
                feature_evidence=dict(tick.features),
                model_evidence={
                    "model_name": tick.risk_model_name,
                    "risk_score": tick.risk_score,
                    "risk_label": tick.risk_label,
                    "policy_decision": tick.policy_decision,
                },
                timeline=[self._timeline_entry(t) for t in window_ticks],
                matched_rules=list(tick.matched_rules),
                recommended_next_step=_next_step(severity),
                explanation=tick.risk_explanation,
                narrative=narrative,
                narrative_source=narrative_source,
            )
            cases.append(case)
            self.record_trace(
                goal=goal,
                observation=(
                    f"Case {case.case_id} built for {behavior} "
                    f"(severity {severity}, conf {confidence:.2f})."
                ),
                decision="emit InvestigationCase",
                confidence=confidence,
                evidence={"behavior": behavior, "severity": severity},
            )
        return {
            "output": {"cases": [c.to_dict() for c in cases]},
            "artifacts": {"cases": cases},
        }

    # ---- LLM augmentation ----------------------------------------

    def _build_narrative(
        self,
        *,
        behavior: str,
        severity: str,
        confidence: float,
        tick_obs: str,
        features: Mapping[str, float],
        matched_rules: Sequence[str],
        risk_score: float,
        goal: str,
    ) -> tuple[str, str]:
        """Return ``(narrative, source)`` for the case file.

        Deterministic fallback is a one-liner that summarises the same
        evidence in a fixed format. The LLM version is structured as
        an analyst memo so it reads well in a screen-recording demo.
        """
        deterministic = (
            f"Surveillance observed {behavior.lower()} flow with risk score "
            f"{risk_score:.2f} (model confidence {confidence:.2f}). "
            f"{tick_obs} Matched rules: "
            f"{', '.join(matched_rules) if matched_rules else 'none'}."
        )
        if self.llm.name == "null":
            return deterministic, "deterministic"
        top = sorted(features.items(), key=lambda kv: -float(kv[1]))[:5]
        feature_lines = "\n".join(
            f"  - {k}: {float(v):.3f}" for k, v in top
        )
        system = (
            "You are a compliance analyst at a simulated exchange market-safety "
            "lab. Write a concise (<=120 words) investigation note that: "
            "(1) names the suspected behavior in plain English, "
            "(2) cites the strongest 2-3 feature signals, "
            "(3) explicitly distinguishes evidence from the rule engine vs the "
            "ML head, and (4) says what additional evidence would raise "
            "confidence. Do not invent numbers; only use what's in the prompt."
        )
        user = (
            f"Suspected behavior: {behavior}.\n"
            f"Severity: {severity}.\n"
            f"ML risk score: {risk_score:.3f} (confidence {confidence:.2f}).\n"
            f"Tick observation: {tick_obs}\n"
            f"Top features:\n{feature_lines}\n"
            f"Matched rules: {', '.join(matched_rules) if matched_rules else 'none'}\n"
        )
        self.record_tool_call(
            "llm.complete",
            arguments={"behavior": behavior, "provider": self.llm.name},
        )
        text = self.llm.complete(system=system, user=user, max_tokens=300, temperature=0.3)
        if not text:
            self.record_trace(
                goal=goal,
                observation="LLM returned empty narrative; using deterministic fallback.",
                decision="fallback",
                confidence=0.4,
            )
            return deterministic, "deterministic"
        self.record_trace(
            goal=goal,
            observation=f"LLM-augmented analyst narrative ({len(text)} chars).",
            decision="accept_llm_narrative",
            confidence=0.75,
        )
        return text, "llm"

    @staticmethod
    def _collect_window(plan: ReplayPlan, idx: int, window: int) -> list[ReplayTick]:
        lo = max(0, idx - window)
        hi = min(len(plan.ticks), idx + window + 1)
        return list(plan.ticks[lo:hi])

    @staticmethod
    def _timeline_entry(tick: ReplayTick) -> dict[str, Any]:
        return {
            "timestamp": tick.timestamp.isoformat(),
            "risk_score": tick.risk_score,
            "policy_decision": tick.policy_decision,
            "close_price": tick.kline.close,
            "volume": tick.kline.volume,
        }
