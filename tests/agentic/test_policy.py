"""Tests for PolicyAgent and its helpers."""

from __future__ import annotations

import pytest

from marketimmune.agentic.policy import (
    PolicyAgent,
    PolicyDecision,
    _action_for,
)

from .conftest import _make_case


# ---------------------------------------------------------------------------
# _action_for
# ---------------------------------------------------------------------------


def test_action_critical() -> None:
    case = _make_case(severity="critical", confidence=0.9)
    action, rationale = _action_for(case)
    assert action == "block_simulated_agent"
    assert rationale


def test_action_high() -> None:
    case = _make_case(severity="high", confidence=0.8)
    action, _ = _action_for(case)
    assert action == "critical_alert"


def test_action_medium() -> None:
    case = _make_case(severity="medium", confidence=0.6)
    action, _ = _action_for(case)
    assert action == "warning_alert"


def test_action_low_confidence() -> None:
    case = _make_case(severity="low", confidence=0.1)
    action, _ = _action_for(case)
    assert action == "monitor"


def test_action_no_action() -> None:
    case = _make_case(severity="low", confidence=0.5)
    action, _ = _action_for(case)
    assert action == "no_action"


# ---------------------------------------------------------------------------
# PolicyAgent._execute
# ---------------------------------------------------------------------------


def test_policy_raises_without_cases() -> None:
    agent = PolicyAgent()
    run = agent.run(goal="decide")
    assert run.success is False


def test_policy_single_critical_case() -> None:
    case = _make_case(severity="critical", confidence=0.95)
    agent = PolicyAgent()
    run = agent.run(goal="decide", cases=[case])
    assert run.success is True
    decisions = run.linked_artifacts["decisions"]
    assert len(decisions) == 1
    d = decisions[0]
    assert isinstance(d, PolicyDecision)
    assert d.recommended_action == "block_simulated_agent"
    assert run.output["aggregate_posture"] == "block_simulated_agent"


def test_policy_empty_cases_list() -> None:
    agent = PolicyAgent()
    run = agent.run(goal="decide", cases=[])
    assert run.success is True
    assert run.output["aggregate_posture"] == "no_action"


def test_policy_aggregate_posture_worst_wins() -> None:
    cases = [
        _make_case("c1", severity="medium", confidence=0.6),
        _make_case("c2", severity="critical", confidence=0.95),
        _make_case("c3", severity="high", confidence=0.8),
    ]
    agent = PolicyAgent()
    run = agent.run(goal="decide", cases=cases)
    assert run.output["aggregate_posture"] == "block_simulated_agent"


def test_policy_decision_to_dict() -> None:
    case = _make_case(severity="high")
    agent = PolicyAgent()
    run = agent.run(goal="decide", cases=[case])
    d = run.linked_artifacts["decisions"][0].to_dict()
    assert "decision_id" in d
    assert "recommended_action" in d
    assert "case_id" in d


def test_policy_all_severity_levels() -> None:
    """Exercises all four severity → action paths."""
    cases = [
        _make_case("c1", severity="critical", confidence=0.9),
        _make_case("c2", severity="high", confidence=0.8),
        _make_case("c3", severity="medium", confidence=0.6),
        _make_case("c4", severity="low", confidence=0.15),
        _make_case("c5", severity="low", confidence=0.5),
    ]
    agent = PolicyAgent()
    run = agent.run(goal="decide", cases=cases)
    assert run.success is True
    actions = {d.case_id: d.recommended_action for d in run.linked_artifacts["decisions"]}
    assert actions["c1"] == "block_simulated_agent"
    assert actions["c2"] == "critical_alert"
    assert actions["c3"] == "warning_alert"
    assert actions["c4"] == "monitor"
    assert actions["c5"] == "no_action"
