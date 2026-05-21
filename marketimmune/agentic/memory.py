"""ImmuneMemoryAgent — long-term store of threat patterns the system has seen.

The memory agent answers two questions:

1. **"Have we seen this kind of attack before?"** — given an
   investigation case it returns the closest memory entry (by
   matched-rule overlap and feature similarity).
2. **"Should we remember this one?"** — given a case + policy
   decision, it decides whether the pattern is novel enough to
   persist. Novelty is computed against the existing memory shelf.

Memory entries are returned as value objects; persistence is the
orchestrator's job (Django models in ``dashboard.models``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from marketimmune.agentic.base import Agent
from marketimmune.agentic.investigator import InvestigationCase
from marketimmune.agentic.policy import PolicyDecision


@dataclass(frozen=True, slots=True)
class ImmuneMemory:
    """One persisted threat pattern."""

    memory_id: str
    threat_name: str
    description: str
    scenario_source: str
    key_signals: tuple[str, ...]
    best_detector: str
    failed_detector: str
    recommended_detector: str
    example_case_id: str
    created_at: str
    novelty_score: float = 0.0
    times_seen: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "threat_name": self.threat_name,
            "description": self.description,
            "scenario_source": self.scenario_source,
            "key_signals": list(self.key_signals),
            "best_detector": self.best_detector,
            "failed_detector": self.failed_detector,
            "recommended_detector": self.recommended_detector,
            "example_case_id": self.example_case_id,
            "created_at": self.created_at,
            "novelty_score": self.novelty_score,
            "times_seen": self.times_seen,
        }


def _signature(case: InvestigationCase) -> tuple[frozenset[str], str]:
    """Stable signature used to detect "have we seen this before?"."""
    rules = frozenset(case.matched_rules)
    return rules, case.suspected_behavior


def _novelty(
    new_signature: tuple[frozenset[str], str], existing: Sequence[ImmuneMemory]
) -> float:
    """1.0 = brand new; 0.0 = exact match seen before."""
    if not existing:
        return 1.0
    new_rules, new_behavior = new_signature
    best_overlap = 0.0
    for mem in existing:
        if mem.threat_name == new_behavior:
            best_overlap = max(best_overlap, 0.6)
        mem_signals = set(mem.key_signals)
        if new_rules and mem_signals:
            jaccard = len(new_rules & mem_signals) / len(new_rules | mem_signals)
            best_overlap = max(best_overlap, jaccard)
    return max(0.0, 1.0 - best_overlap)


class ImmuneMemoryAgent(Agent):
    """Decides whether each case is novel enough to remember."""

    name = "ImmuneMemoryAgent"
    description = "Pattern-matches cases against prior memory; persists novel ones."

    NOVELTY_THRESHOLD = 0.35

    def _execute(
        self,
        *,
        goal: str,
        cases: Sequence[InvestigationCase] | None = None,
        decisions: Sequence[PolicyDecision] | None = None,
        existing_memories: Sequence[ImmuneMemory] | None = None,
        scenario_source: str = "unknown",
        **_: Any,
    ) -> Mapping[str, Any]:
        if cases is None:
            raise ValueError("ImmuneMemoryAgent requires `cases`.")
        decisions = decisions or []
        existing = list(existing_memories or [])
        decision_by_case = {d.case_id: d for d in decisions}

        new_memories: list[ImmuneMemory] = []
        recurrences: list[str] = []
        for case in cases:
            sig = _signature(case)
            novelty = _novelty(sig, existing + new_memories)
            policy = decision_by_case.get(case.case_id)
            self.record_tool_call(
                "ImmuneMemory.lookup",
                arguments={"behavior": case.suspected_behavior},
                result_summary=f"novelty={novelty:.2f}",
            )

            if novelty < self.NOVELTY_THRESHOLD:
                recurrences.append(case.case_id)
                self.record_trace(
                    goal=goal,
                    observation=(
                        f"Case {case.case_id} matches an existing memory "
                        f"(novelty {novelty:.2f}); incrementing seen count."
                    ),
                    decision="skip_persist",
                    confidence=0.7,
                )
                continue

            best_detector = case.model_evidence.get("model_name", "unknown")
            failed_detector = "RuleEngine" if not case.matched_rules else "none"
            new_memories.append(ImmuneMemory(
                memory_id=f"mem_{case.case_id}",
                threat_name=case.suspected_behavior,
                description=(
                    f"Observed {case.suspected_behavior} at {case.observation!s}"
                ),
                scenario_source=scenario_source,
                key_signals=tuple(case.matched_rules) or tuple(
                    [f"{k}={v:.2f}" for k, v in list(case.feature_evidence.items())[:3]]
                ),
                best_detector=best_detector,
                failed_detector=failed_detector,
                recommended_detector=best_detector,
                example_case_id=case.case_id,
                created_at=datetime.now(timezone.utc).isoformat(),
                novelty_score=novelty,
                times_seen=1,
            ))
            self.record_trace(
                goal=goal,
                observation=(
                    f"Case {case.case_id} is novel (novelty {novelty:.2f}); "
                    f"persisting to memory."
                ),
                decision="persist_memory",
                confidence=novelty,
                evidence={"threat": case.suspected_behavior},
            )

        return {
            "output": {
                "new_memories": [m.to_dict() for m in new_memories],
                "recurrences": recurrences,
                "memory_total_after": len(existing) + len(new_memories),
            },
            "artifacts": {"new_memories": new_memories},  # type: ignore[dict-item]
        }
