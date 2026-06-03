"""Shared fixtures for agentic test suite."""

from __future__ import annotations

from datetime import datetime

import pytest

from marketimmune.agentic.investigator import InvestigationCase
from marketimmune.agentic.memory import ImmuneMemory
from marketimmune.agentic.sentinel import SentinelAlert
from marketimmune.agentic.trainer import TrainingJob
from marketimmune.simulator.data_loader import KlineRecord
from marketimmune.simulator.pricing import DerivedQuote
from marketimmune.simulator.replay_builder import ReplayConfig, ReplayPlan, ReplayTick


def _make_kline(idx: int = 0) -> KlineRecord:
    return KlineRecord(
        event_id=f"ev-{idx}",
        timestamp=datetime(2026, 1, 1, 0, idx, 0),
        symbol="BTCUSDT",
        open=100.0,
        high=105.0,
        low=99.0,
        close=101.0,
        volume=1000.0,
        trade_count=10,
        raw={},
    )


def _make_tick(
    idx: int = 0,
    policy_decision: str = "block",
    risk_score: float = 0.9,
    matched_rules: tuple[str, ...] = ("one_sided_sell_pressure", "cancel_rate_spike"),
) -> ReplayTick:
    return ReplayTick(
        idx=idx,
        timestamp=datetime(2026, 1, 1, 0, idx, 0),
        kline=_make_kline(idx),
        depth=None,
        quote=DerivedQuote(bid=100.0, ask=102.0, spread=2.0, band_percent=1.0),
        agent_side="SELL",
        agent_order_price=102.0,
        agent_order_quantity=5.0,
        agent_trade_price=0.0,
        agent_trade_quantity=0.0,
        features={
            "w1000_agentic_burst_rate_per_second": 18.0,
            "w5000_order_quantity_sum": 4.2,
            "w5000_order_sell_ratio": 0.95,
            "w1000_agentic_min_interarrival_ms": 4.0,
            "w60000_market_price_drift": 12.0,
            "w1000_order_cancel_rate": 0.65,
            "w5000_agentic_self_cross_proxy_count": 0.0,
            "w1000_agentic_unique_agents": 1.0,
            "w5000_order_price_range": 5.0,
            "w5000_order_quantity_max": 5.0,
        },
        risk_score=risk_score,
        risk_label="BLOCK",
        risk_explanation="Test explanation",
        risk_model_name="RuleEngine",
        matched_rules=matched_rules,
        policy_decision=policy_decision,
        recommended_control="Halt connection.",
        observation="Observed burst activity",
    )


def _make_plan(ticks: list[ReplayTick] | None = None) -> ReplayPlan:
    t = ticks if ticks is not None else [_make_tick(0)]
    return ReplayPlan(
        run_id="run_test",
        config=ReplayConfig(scenario_name="spoofing_layering"),
        ticks=tuple(t),
        depth_snapshot_count=0,
    )


def _make_alert(alert_id: str = "alert_run_test_0", severity: str = "critical") -> SentinelAlert:
    return SentinelAlert(
        alert_id=alert_id,
        timestamp="2026-01-01T00:00:00",
        risk_score=0.9,
        risk_label="BLOCK",
        severity=severity,
        model_name="RuleEngine",
        matched_rules=("one_sided_sell_pressure", "cancel_rate_spike"),
        top_features=("w1000_agentic_burst_rate_per_second",),
        linked_event_id="ev-0",
        explanation="Test",
    )


def _make_case(
    case_id: str = "case_run_test_0",
    severity: str = "critical",
    confidence: float = 0.95,
    matched_rules: list[str] | None = None,
) -> InvestigationCase:
    return InvestigationCase(
        case_id=case_id,
        alert_id="alert_run_test_0",
        suspected_behavior="Spoofing / layering",
        severity=severity,
        confidence=confidence,
        observation="Observed burst activity",
        feature_evidence={"w1000_agentic_burst_rate_per_second": 18.0},
        model_evidence={"model_name": "RuleEngine", "risk_score": 0.9},
        timeline=[],
        matched_rules=matched_rules if matched_rules is not None else ["one_sided_sell_pressure"],
        recommended_next_step="Halt agent",
        explanation="Test explanation",
    )


def _make_memory(
    memory_id: str = "mem_case_run_test_0",
    threat_name: str = "Spoofing / layering",
    key_signals: tuple[str, ...] = ("one_sided_sell_pressure", "cancel_rate_spike"),
) -> ImmuneMemory:
    return ImmuneMemory(
        memory_id=memory_id,
        threat_name=threat_name,
        description="Test memory",
        scenario_source="test",
        key_signals=key_signals,
        best_detector="RuleEngine",
        failed_detector="none",
        recommended_detector="RuleEngine",
        example_case_id="case_run_test_0",
        created_at="2026-01-01T00:00:00+00:00",
        novelty_score=0.9,
    )


def _make_training_job(success: bool = True, error: str = "") -> TrainingJob:
    return TrainingJob(
        job_id="train_abc123",
        triggered_by="force_flag",
        candidate_model="GradientBoostingRiskHead-candidate",
        incumbent_model="(none)",
        dataset_version="synthetic-1234",
        command=("python", "scripts/train_risk_head.py"),
        metrics={"pr_auc": 0.85, "roc_auc": 0.88, "f1": 0.82, "accuracy": 0.90},
        holdout_metrics={"pr_auc": 0.80, "roc_auc": 0.83, "f1": 0.78, "accuracy": 0.86},
        success=success,
        error=error,
        started_at=1700000000.0,
        finished_at=1700000010.0,
    )


@pytest.fixture
def plan() -> ReplayPlan:
    return _make_plan()


@pytest.fixture
def alert() -> SentinelAlert:
    return _make_alert()


@pytest.fixture
def case_() -> InvestigationCase:
    return _make_case()


@pytest.fixture
def memory_obj() -> ImmuneMemory:
    return _make_memory()


@pytest.fixture
def training_job() -> TrainingJob:
    return _make_training_job()
