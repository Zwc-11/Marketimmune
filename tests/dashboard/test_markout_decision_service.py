"""Tests for persisted promoted-model fill decisions."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from dashboard.services import markout_decision_service as service
from marketimmune.agentic import LoopResult
from marketimmune.agentic.investigator import InvestigationCase
from marketimmune.agentic.policy import PolicyDecision


def _case(case_id: str, alert_id: str) -> InvestigationCase:
    return InvestigationCase(
        case_id=case_id,
        alert_id=alert_id,
        suspected_behavior="Adverse-selection markout risk",
        severity="high",
        confidence=0.8,
        observation="Promoted model flagged toxic maker fill.",
        feature_evidence={"asset_open_interest": 10_000.0},
        model_evidence={"calibrated_score": 0.82},
        timeline=[],
        matched_rules=["promoted_markout_threshold"],
        recommended_next_step="Raise alert severity and route to active compliance review.",
        explanation="Promoted CatBoost markout model exceeded threshold.",
    )


def test_link_markout_decisions_to_loop_copies_case_and_policy_action(
    monkeypatch: Any,
) -> None:
    linked: list[dict[str, Any]] = []

    def fake_link_fill_decision(**kwargs: Any) -> int:
        linked.append(kwargs)
        return 1

    monkeypatch.setattr(service, "_link_fill_decision", fake_link_fill_decision)
    loop = object()
    case = _case(
        "case_alert_hl_SOL_1000-77-oid123",
        "alert_hl_SOL_1000-77-oid123",
    )
    ignored_case = _case("case_replay_1", "alert_replay_1")
    decision = PolicyDecision(
        decision_id="dec_case_alert_hl_SOL_1000-77-oid123",
        case_id=case.case_id,
        recommended_action="critical_alert",
        severity="high",
        rationale="High severity with matched rules; raise priority and review.",
        confidence=0.8,
    )
    result = LoopResult(
        proposal=None,
        alerts=(),
        cases=(case, ignored_case),
        decisions=(decision,),
        new_memories=(),
        aggregate_posture="critical_alert",
        agent_runs=(),
    )

    assert service.link_markout_decisions_to_loop(loop=loop, result=result) == 1
    assert linked == [
        {
            "fill_id": "hl_SOL_1000-77-oid123",
            "loop": loop,
            "case": case,
            "policy_decision": decision,
        }
    ]


def test_link_fill_decision_updates_latest_row_and_history(monkeypatch: Any) -> None:
    saved: dict[str, Any] = {}
    history: list[dict[str, Any]] = []

    class MissingDecision(Exception):
        pass

    class FakeDecision:
        loop = None
        case_id = ""
        policy_decision_id = ""
        recommended_action = ""

        def save(self, *, update_fields: list[str]) -> None:
            saved["update_fields"] = update_fields
            saved["decision"] = self

    decision = FakeDecision()

    class FakeDecisionManager:
        def get(self, *, decision_id: str) -> FakeDecision:
            saved["decision_id"] = decision_id
            return decision

    class FakeDecisionModel:
        DoesNotExist = MissingDecision
        objects = FakeDecisionManager()

    class FakeLinkManager:
        def update_or_create(self, **kwargs: Any) -> None:
            history.append(kwargs)

    class FakeLinkModel:
        objects = FakeLinkManager()

    monkeypatch.setattr(service, "ScoredFillDecision", FakeDecisionModel)
    monkeypatch.setattr(service, "ScoredFillDecisionLink", FakeLinkModel)
    loop = object()
    case = _case(
        "case_alert_hl_SOL_1000-77-oid123",
        "alert_hl_SOL_1000-77-oid123",
    )
    policy = PolicyDecision(
        decision_id="dec_case_alert_hl_SOL_1000-77-oid123",
        case_id=case.case_id,
        recommended_action="critical_alert",
        severity="high",
        rationale="High severity with matched rules; raise priority and review.",
        confidence=0.8,
    )

    assert (
        service._link_fill_decision(
            fill_id="hl_SOL_1000-77-oid123",
            loop=loop,
            case=case,
            policy_decision=policy,
        )
        == 1
    )

    assert saved["decision_id"] == "hl_SOL_1000-77-oid123"
    assert decision.loop is loop
    assert decision.case_id == case.case_id
    assert decision.policy_decision_id == policy.decision_id
    assert decision.recommended_action == "critical_alert"
    assert saved["update_fields"] == [
        "loop",
        "case_id",
        "policy_decision_id",
        "recommended_action",
        "scored_at",
    ]
    assert history == [
        {
            "decision": decision,
            "loop": loop,
            "case_id": case.case_id,
            "defaults": {
                "policy_decision_id": policy.decision_id,
                "recommended_action": "critical_alert",
            },
        }
    ]


def test_latest_gold_partition_uses_partition_date(tmp_path: Path) -> None:
    older = tmp_path / "SOL-training-20260531.parquet"
    newer = tmp_path / "SOL-training-20260601.parquet"
    nested = tmp_path / "archive" / "SOL-training-20260530.parquet"
    nested.parent.mkdir()
    for path in (older, newer, nested):
        path.write_bytes(b"")

    assert service._latest_gold_partition(tmp_path) == newer


def test_should_refresh_when_resolved_gold_source_changes(monkeypatch: Any) -> None:
    class FakeLatest:
        source_path = "data/hyperliquid/old.parquet"
        scored_at = service._now() - timedelta(milliseconds=1)

    class FakeDecisionManager:
        def order_by(self, *_fields: str) -> FakeDecisionManager:
            return self

        def first(self) -> FakeLatest:
            return FakeLatest()

    class FakeDecisionModel:
        objects = FakeDecisionManager()

    monkeypatch.setattr(service, "ScoredFillDecision", FakeDecisionModel)
    monkeypatch.setattr(service, "_display_path", lambda _path: "data/hyperliquid/new.parquet")

    assert service._should_refresh(None, gold_path=Path("new.parquet")) is True
