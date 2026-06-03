"""Tests for ImmuneMemoryAgent and its helpers."""

from __future__ import annotations

from marketimmune.agentic.memory import (
    ImmuneMemory,
    ImmuneMemoryAgent,
    _novelty,
    _signature,
)

from .conftest import _make_case, _make_memory

# ---------------------------------------------------------------------------
# _signature
# ---------------------------------------------------------------------------


def test_signature_extracts_rules_and_behavior() -> None:
    case = _make_case(matched_rules=["rule_a", "rule_b"])
    rules, behavior = _signature(case)
    assert rules == frozenset({"rule_a", "rule_b"})
    assert behavior == case.suspected_behavior


# ---------------------------------------------------------------------------
# _novelty
# ---------------------------------------------------------------------------


def test_novelty_no_memories_is_one() -> None:
    case = _make_case()
    sig = _signature(case)
    assert _novelty(sig, []) == 1.0


def test_novelty_exact_match_is_low() -> None:
    case = _make_case(matched_rules=["one_sided_sell_pressure", "cancel_rate_spike"])
    mem = _make_memory(
        threat_name=case.suspected_behavior,
        key_signals=("one_sided_sell_pressure", "cancel_rate_spike"),
    )
    sig = _signature(case)
    nov = _novelty(sig, [mem])
    assert nov < ImmuneMemoryAgent.NOVELTY_THRESHOLD


def test_novelty_different_behavior_is_high() -> None:
    case = _make_case(
        matched_rules=["completely_new_rule"],
        case_id="brand_new",
    )
    # Manually set a different suspected behavior
    from dataclasses import replace
    new_case = replace(case, suspected_behavior="Unknown new behavior")
    mem = _make_memory(
        threat_name="Spoofing / layering",
        key_signals=("one_sided_sell_pressure",),
    )
    sig = _signature(new_case)
    nov = _novelty(sig, [mem])
    assert nov > 0.0


# ---------------------------------------------------------------------------
# ImmuneMemoryAgent._execute
# ---------------------------------------------------------------------------


def test_memory_raises_without_cases() -> None:
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember")
    assert run.success is False


def test_memory_empty_cases() -> None:
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[])
    assert run.success is True
    assert run.output["new_memories"] == []
    assert run.output["recurrences"] == []


def test_memory_novel_case_is_persisted() -> None:
    case = _make_case()
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case], existing_memories=[])
    assert run.success is True
    mems = run.linked_artifacts["new_memories"]
    assert len(mems) == 1
    assert isinstance(mems[0], ImmuneMemory)


def test_memory_recurrence_not_persisted() -> None:
    case = _make_case(matched_rules=["one_sided_sell_pressure", "cancel_rate_spike"])
    mem = _make_memory(
        threat_name=case.suspected_behavior,
        key_signals=("one_sided_sell_pressure", "cancel_rate_spike"),
    )
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case], existing_memories=[mem])
    assert run.success is True
    assert len(run.linked_artifacts["new_memories"]) == 0
    assert case.case_id in run.output["recurrences"]


def test_memory_to_dict() -> None:
    case = _make_case()
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case])
    mem = run.linked_artifacts["new_memories"][0]
    d = mem.to_dict()
    assert "memory_id" in d
    assert "novelty_score" in d
    assert "key_signals" in d


def test_memory_with_policy_decisions() -> None:
    from marketimmune.agentic.policy import PolicyDecision
    case = _make_case()
    decision = PolicyDecision(
        decision_id="dec_case",
        case_id=case.case_id,
        recommended_action="block_simulated_agent",
        severity="critical",
        rationale="test",
        confidence=0.95,
    )
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case], decisions=[decision])
    assert run.success is True
    assert len(run.linked_artifacts["new_memories"]) == 1


def test_memory_total_after() -> None:
    case = _make_case()
    existing = [_make_memory("other_mem", threat_name="Other threat", key_signals=("other",))]
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case], existing_memories=existing)
    assert run.output["memory_total_after"] >= 1


def test_memory_no_matched_rules_uses_feature_fallback() -> None:
    """When matched_rules is empty, key_signals fall back to feature entries."""
    case = _make_case(matched_rules=[])
    agent = ImmuneMemoryAgent()
    run = agent.run(goal="remember", cases=[case])
    assert run.success is True
    mems = run.linked_artifacts["new_memories"]
    # Should still produce a memory (novel pattern)
    assert len(mems) >= 1
