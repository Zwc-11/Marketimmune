"""Tests for RiskSentinelAgent."""

from __future__ import annotations

from marketimmune.agentic.sentinel import (
    RiskSentinelAgent,
    _severity_for,
    _top_features_for,
)

from .conftest import _make_plan, _make_tick

# ---------------------------------------------------------------------------
# _severity_for helpers
# ---------------------------------------------------------------------------


def test_severity_block() -> None:
    tick = _make_tick(0, policy_decision="block", risk_score=0.9)
    assert _severity_for(tick) == "critical"


def test_severity_alert() -> None:
    tick = _make_tick(0, policy_decision="alert", risk_score=0.6)
    assert _severity_for(tick) == "high"


def test_severity_medium() -> None:
    tick = _make_tick(0, policy_decision="allow", risk_score=0.5)
    assert _severity_for(tick) == "medium"


def test_severity_low() -> None:
    tick = _make_tick(0, policy_decision="allow", risk_score=0.2)
    assert _severity_for(tick) == "low"


# ---------------------------------------------------------------------------
# _top_features_for
# ---------------------------------------------------------------------------


def test_top_features_for_returns_up_to_3() -> None:
    tick = _make_tick(0)
    tf = _top_features_for(tick)
    assert len(tf) <= 3
    assert all(isinstance(f, str) for f in tf)


# ---------------------------------------------------------------------------
# RiskSentinelAgent._execute
# ---------------------------------------------------------------------------


def test_sentinel_raises_without_plan() -> None:
    agent = RiskSentinelAgent()
    run = agent.run(goal="test")
    assert run.success is False
    assert "ValueError" in (run.error or "")


def test_sentinel_produces_alerts_for_hostile_ticks() -> None:
    tick0 = _make_tick(0, policy_decision="block", risk_score=0.9)
    tick1 = _make_tick(1, policy_decision="allow", risk_score=0.1)
    plan = _make_plan([tick0, tick1])
    agent = RiskSentinelAgent()
    run = agent.run(goal="surface alerts", plan=plan)
    assert run.success is True
    alerts = run.linked_artifacts["alerts"]
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


def test_sentinel_empty_plan_produces_no_alerts() -> None:
    plan = _make_plan([])
    agent = RiskSentinelAgent()
    run = agent.run(goal="surface alerts", plan=plan)
    assert run.success is True
    assert run.linked_artifacts["alerts"] == []


def test_sentinel_top_k_limits_alerts() -> None:
    ticks = [_make_tick(i, policy_decision="block", risk_score=0.9 - i * 0.01) for i in range(10)]
    plan = _make_plan(ticks)
    agent = RiskSentinelAgent()
    run = agent.run(goal="surface alerts", plan=plan, top_k=3)
    assert len(run.linked_artifacts["alerts"]) == 3


def test_sentinel_alert_sorted_by_score_desc() -> None:
    t0 = _make_tick(0, policy_decision="alert", risk_score=0.6)
    t1 = _make_tick(1, policy_decision="block", risk_score=0.95)
    plan = _make_plan([t0, t1])
    agent = RiskSentinelAgent()
    run = agent.run(goal="test", plan=plan)
    alerts = run.linked_artifacts["alerts"]
    assert alerts[0].risk_score > alerts[1].risk_score


def test_sentinel_alert_to_dict() -> None:
    tick = _make_tick(0)
    plan = _make_plan([tick])
    agent = RiskSentinelAgent()
    run = agent.run(goal="test", plan=plan)
    alerts = run.linked_artifacts["alerts"]
    d = alerts[0].to_dict()
    assert "alert_id" in d
    assert "severity" in d


def test_sentinel_threshold_filtering() -> None:
    """Ticks below the alert threshold and with allow decision are skipped."""
    tick = _make_tick(0, policy_decision="allow", risk_score=0.3)
    plan = _make_plan([tick])
    agent = RiskSentinelAgent()
    run = agent.run(goal="test", plan=plan, alert_threshold=0.45)
    assert run.linked_artifacts["alerts"] == []
