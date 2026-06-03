"""Tests for InvestigatorAgent and its helpers."""

from __future__ import annotations

import pytest

from marketimmune.agentic.investigator import (
    InvestigationCase,
    InvestigatorAgent,
    _classify_behavior,
    _next_step,
)

from .conftest import _make_alert, _make_plan, _make_tick


# ---------------------------------------------------------------------------
# _classify_behavior
# ---------------------------------------------------------------------------


def test_classify_spoofing() -> None:
    rules = ["one_sided_sell_pressure", "cancel_rate_spike"]
    assert _classify_behavior(rules, {}) == "Spoofing / layering"


def test_classify_quote_stuffing() -> None:
    rules = ["rapid_order_interarrival", "cancel_rate_spike"]
    assert _classify_behavior(rules, {}) == "Quote stuffing"


def test_classify_momentum_ignition() -> None:
    rules = ["sharp_buy_price_drift", "stop_run_or_feedback_sweep"]
    result = _classify_behavior(rules, {})
    assert result == "Momentum ignition"


def test_classify_bursty_unclassified() -> None:
    result = _classify_behavior([], {"w1000_agentic_burst_rate_per_second": 15.0})
    assert "Bursty" in result


def test_classify_high_cancel() -> None:
    result = _classify_behavior([], {"w1000_order_cancel_rate": 0.8})
    assert "cancel" in result.lower()


def test_classify_generic() -> None:
    result = _classify_behavior([], {})
    assert "anomalous" in result.lower() or "generic" in result.lower()


# ---------------------------------------------------------------------------
# _next_step
# ---------------------------------------------------------------------------


def test_next_step_critical() -> None:
    assert "Halt" in _next_step("critical")


def test_next_step_high() -> None:
    assert "alert" in _next_step("high").lower()


def test_next_step_medium() -> None:
    assert "Monitor" in _next_step("medium")


def test_next_step_low() -> None:
    assert "log" in _next_step("low").lower()


# ---------------------------------------------------------------------------
# InvestigatorAgent
# ---------------------------------------------------------------------------


def test_investigator_raises_without_plan() -> None:
    agent = InvestigatorAgent()
    run = agent.run(goal="test")
    assert run.success is False


def test_investigator_raises_without_alerts() -> None:
    plan = _make_plan()
    agent = InvestigatorAgent()
    run = agent.run(goal="test", plan=plan)
    assert run.success is False


def test_investigator_builds_case_for_matching_alert() -> None:
    tick = _make_tick(0, policy_decision="block", risk_score=0.9)
    plan = _make_plan([tick])
    alert = _make_alert("alert_run_test_0")
    agent = InvestigatorAgent()
    run = agent.run(goal="investigate", plan=plan, alerts=[alert])
    assert run.success is True
    cases = run.linked_artifacts["cases"]
    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, InvestigationCase)
    assert case.severity == "critical"


def test_investigator_skips_unmatched_alert() -> None:
    """An alert whose tick ID is not in the plan is skipped with a trace."""
    tick = _make_tick(0)
    plan = _make_plan([tick])
    bad_alert = _make_alert("alert_run_test_999")
    agent = InvestigatorAgent()
    run = agent.run(goal="investigate", plan=plan, alerts=[bad_alert])
    assert run.success is True
    assert len(run.linked_artifacts["cases"]) == 0
    assert any("skip" in t.decision for t in run.traces)


def test_investigator_case_to_dict() -> None:
    tick = _make_tick(0)
    plan = _make_plan([tick])
    alert = _make_alert("alert_run_test_0")
    agent = InvestigatorAgent()
    run = agent.run(goal="investigate", plan=plan, alerts=[alert])
    case = run.linked_artifacts["cases"][0]
    d = case.to_dict()
    assert d["case_id"] == case.case_id
    assert "timeline" in d
    assert "feature_evidence" in d


def test_investigator_window_is_clipped_to_plan_bounds() -> None:
    """Window > plan length should not crash."""
    tick = _make_tick(0)
    plan = _make_plan([tick])
    alert = _make_alert("alert_run_test_0")
    agent = InvestigatorAgent()
    run = agent.run(goal="investigate", plan=plan, alerts=[alert], window=50)
    assert run.success is True
    assert len(run.linked_artifacts["cases"]) == 1
