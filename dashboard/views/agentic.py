"""Agentic immune-loop views: React shell, classic template, and JSON state."""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Max
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.models import (
    ImmuneLoopRun,
    ImmuneMemoryEntry,
    ModelMetric,
    ModelPrediction,
    ModelPromotionDecision,
    ReplayEvent,
    ReplaySession,
    RiskAlert,
)
from dashboard.services import AgenticService

# These external connectors aren't implemented locally; we surface a static
# row per provider so the dashboard reflects honest "not_implemented" status.
_UNIMPLEMENTED_CONNECTORS = [
    ("OKX", "Public market data"),
    ("Bybit", "Public market data"),
    ("Coinbase Exchange", "Public market data"),
    ("Kraken", "Public market data"),
]


class AgenticReactView(View):
    """Serve the prebuilt React + TypeScript bundle.

    The bundle is produced by ``npm run build`` (see ``frontend/``)
    into ``dashboard/static/agentic/index.html``. The HTML already
    points at ``/static/agentic/assets/index-<hash>.js|css`` because
    Vite is configured with ``base: '/static/agentic/'``, so Django's
    staticfiles app serves the assets without any extra plumbing.
    """

    BUNDLE_PATH = "dashboard/static/agentic/index.html"

    def get(self, request):
        bundle = Path(settings.BASE_DIR) / self.BUNDLE_PATH
        if not bundle.exists():
            return HttpResponse(
                "<h1>React bundle missing</h1>"
                "<p>Build the frontend first:</p>"
                "<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>",
                status=503,
                content_type="text/html",
            )
        return HttpResponse(bundle.read_text(encoding="utf-8"), content_type="text/html")


class AgenticLoopView(View):
    """Single page showing the latest agentic immune-loop run and memory shelf."""

    def get(self, request):
        loop = ImmuneLoopRun.objects.first()
        agent_runs = list(loop.agent_runs.all()) if loop else []
        cases = list(loop.cases.all()) if loop else []
        decisions = list(loop.policy_decisions.all()) if loop else []
        proposal = loop.proposals.first() if loop else None
        memories = list(ImmuneMemoryEntry.objects.all()[:20])
        recent_loops = list(ImmuneLoopRun.objects.all()[:8])
        promotion = ModelPromotionDecision.objects.first()
        recent_promotions = list(ModelPromotionDecision.objects.all()[:5])
        return render(
            request,
            "dashboard/agentic_loop.html",
            {
                "loop": loop,
                "agent_runs": agent_runs,
                "cases": cases,
                "decisions": decisions,
                "proposal": proposal,
                "memories": memories,
                "recent_loops": recent_loops,
                "promotion": promotion,
                "recent_promotions": recent_promotions,
            },
        )


def _serialize_memory(memory: ImmuneMemoryEntry) -> dict:
    return {
        "memory_id": memory.memory_id,
        "threat_name": memory.threat_name,
        "description": memory.description,
        "scenario_source": memory.scenario_source,
        "key_signals": memory.key_signals,
        "best_detector": memory.best_detector,
        "failed_detector": memory.failed_detector,
        "recommended_detector": memory.recommended_detector,
        "example_case_id": memory.example_case_id,
        "novelty_score": memory.novelty_score,
        "times_seen": memory.times_seen,
        "created_at": memory.created_at.isoformat(),
        "last_seen_at": memory.last_seen_at.isoformat(),
    }


def _serialize_promotion(promotion: ModelPromotionDecision | None) -> dict | None:
    if not promotion:
        return None
    return {
        "decision_id": promotion.decision_id,
        "verdict": promotion.verdict,
        "candidate_model": promotion.candidate_model,
        "incumbent_model": promotion.incumbent_model,
        "rationale": promotion.rationale,
        "metrics": promotion.metrics,
        "created_at": promotion.created_at.isoformat(),
    }


def _serialize_recent_loop(loop: ImmuneLoopRun) -> dict:
    return {
        "loop_id": loop.loop_id,
        "started_at": loop.started_at.isoformat(),
        "duration_ms": loop.duration_ms,
        "aggregate_posture": loop.aggregate_posture,
        "alert_count": loop.alert_count,
        "case_count": loop.case_count,
        "new_memory_count": loop.new_memory_count,
        "proposal_name": loop.proposal_name,
    }


def _serialize_agent_run(agent_run) -> dict:
    return {
        "run_id": agent_run.run_id,
        "agent_name": agent_run.agent_name,
        "goal": agent_run.goal,
        "started_at": agent_run.started_at.isoformat(),
        "finished_at": agent_run.finished_at.isoformat(),
        "duration_ms": agent_run.duration_ms,
        "success": agent_run.success,
        "error": agent_run.error,
        "output": agent_run.output,
        "linked_artifacts": agent_run.linked_artifacts,
        "tool_call_count": agent_run.tool_calls.count(),
        "trace_count": agent_run.decision_traces.count(),
        "tool_calls": [
            {
                "tool": tc.tool,
                "arguments": tc.arguments,
                "duration_ms": tc.duration_ms,
                "result_summary": tc.result_summary,
                "occurred_at": tc.occurred_at.isoformat(),
            }
            for tc in agent_run.tool_calls.all()
        ],
        "decision_traces": [
            {
                "goal": tr.goal,
                "observation": tr.observation,
                "decision": tr.decision,
                "confidence": tr.confidence,
                "evidence": tr.evidence,
                "occurred_at": tr.occurred_at.isoformat(),
            }
            for tr in agent_run.decision_traces.all()
        ],
    }


def _serialize_proposal(proposal) -> dict | None:
    if not proposal:
        return None
    return {
        "name": proposal.name,
        "base_scenario": proposal.base_scenario,
        "cover_scenario": proposal.cover_scenario,
        "expected_attack": proposal.expected_attack,
        "evasion_strategy": proposal.evasion_strategy,
        "difficulty": proposal.difficulty,
        "rationale": proposal.rationale,
        "rationale_source": proposal.features.get("rationale_source"),
    }


def _serialize_case(case) -> dict:
    return {
        "case_id": case.case_id,
        "alert_id": case.alert_id,
        "suspected_behavior": case.suspected_behavior,
        "severity": case.severity,
        "confidence": case.confidence,
        "observation": case.observation,
        "timeline": case.timeline,
        "matched_rules": case.matched_rules,
        "explanation": case.explanation,
        "narrative": case.model_evidence.get("narrative", ""),
        "narrative_source": case.model_evidence.get("narrative_source", "deterministic"),
        "feature_evidence": case.feature_evidence,
        "model_evidence": {
            k: v
            for k, v in case.model_evidence.items()
            if k not in {"narrative", "narrative_source"}
        },
        "recommended_next_step": case.recommended_next_step,
        "created_at": case.created_at.isoformat(),
    }


def _serialize_decision(decision) -> dict:
    return {
        "decision_id": decision.decision_id,
        "case_id": decision.case_id,
        "recommended_action": decision.recommended_action,
        "severity": decision.severity,
        "rationale": decision.rationale,
        "confidence": decision.confidence,
        "created_at": decision.created_at.isoformat(),
    }


def _serialize_loop(loop: ImmuneLoopRun) -> dict:
    proposal = loop.proposals.first()
    return {
        "loop_id": loop.loop_id,
        "started_at": loop.started_at.isoformat(),
        "duration_ms": loop.duration_ms,
        "aggregate_posture": loop.aggregate_posture,
        "proposal_name": loop.proposal_name,
        "alert_count": loop.alert_count,
        "case_count": loop.case_count,
        "new_memory_count": loop.new_memory_count,
        "agent_runs": [_serialize_agent_run(ar) for ar in loop.agent_runs.all()],
        "proposal": _serialize_proposal(proposal),
        "cases": [_serialize_case(c) for c in loop.cases.all()],
        "decisions": [_serialize_decision(d) for d in loop.policy_decisions.all()],
    }


@api_view(["GET"])
def agentic_loop_state(request):
    """Return the latest loop + memory shelf as one JSON document.

    This is the single endpoint the React frontend consumes. Keeping
    it shaped as one document means the front-end has zero waterfall
    requests on first paint.
    """
    loop = ImmuneLoopRun.objects.first()
    memories = list(ImmuneMemoryEntry.objects.all()[:30])
    promotion = ModelPromotionDecision.objects.first()
    recent_loops = list(ImmuneLoopRun.objects.all()[:10])

    payload: dict = {
        "loop": _serialize_loop(loop) if loop else None,
        "memories": [_serialize_memory(m) for m in memories],
        "promotion": _serialize_promotion(promotion),
        "recent_loops": [_serialize_recent_loop(lr) for lr in recent_loops],
    }
    return Response(payload)


@api_view(["GET"])
def agentic_llm_status(request):
    """Report whether the agentic loop is configured to call an LLM.

    Never returns the API key itself. Just the provider name, model
    id, and the on/off flag — enough for the UI to show a badge.
    """
    from marketimmune.agentic import build_default_llm

    flag = (os.environ.get("MARKETIMMUNE_USE_LLM") or "").strip().lower()
    requested = flag in {"1", "true", "yes", "on"}
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    client = build_default_llm(load_env=False)  # already loaded by manage.py
    enabled = client.name != "null"
    return Response(
        {
            "enabled": enabled,
            "requested": requested,
            "has_key": has_key,
            "provider": client.name,
            "model": getattr(client, "model", ""),
        }
    )


@api_view(["POST"])
def trigger_immune_loop(request):
    """Run one immune loop synchronously and return its summary."""
    difficulty = (
        request.data.get("difficulty", "medium") if hasattr(request, "data") else "medium"
    )
    limit = int(request.data.get("limit", 30)) if hasattr(request, "data") else 30
    try:
        loop = AgenticService.run_once(difficulty=difficulty, tick_limit=limit)
    except Exception as exc:  # noqa: BLE001
        return Response({"error": str(exc)}, status=500)
    return Response(
        {
            "loop_id": loop.loop_id,
            "aggregate_posture": loop.aggregate_posture,
            "alert_count": loop.alert_count,
            "case_count": loop.case_count,
            "new_memory_count": loop.new_memory_count,
            "duration_ms": loop.duration_ms,
            "proposal_name": loop.proposal_name,
        }
    )


@api_view(["GET"])
def exchange_training_status(request):
    """Report real exchange ingestion and model-training coverage.

    This endpoint is intentionally conservative: it marks providers as
    connected only when this codebase has an implemented adapter and
    persisted data or a verified connection artifact.
    """
    from dashboard.models import DemoTrainingRun

    source_rows = list(
        ReplayEvent.objects.values("source", "symbol")
        .annotate(events=Count("id"), latest_timestamp=Max("timestamp"))
        .order_by("source", "symbol")
    )
    total_events = ReplayEvent.objects.count()
    total_predictions = ModelPrediction.objects.count()
    total_alerts = RiskAlert.objects.count()
    total_sessions = ReplaySession.objects.count()
    latest_event = ReplayEvent.objects.aggregate(latest=Max("timestamp"))["latest"]
    model_path = Path(settings.BASE_DIR) / "data" / "models" / "risk_head.joblib"
    ws_sample = Path(settings.BASE_DIR) / "data" / "live" / "binance_ws_sample.jsonl"
    binance_events = sum(
        row["events"] for row in source_rows if "binance" in str(row["source"]).lower()
    )

    connectors = [
        {
            "exchange": "Binance",
            "market": "USD-M Futures",
            "adapter": "historical_public_api",
            "implemented": True,
            "connected": binance_events > 0,
            "training_enabled": binance_events > 0 and model_path.exists(),
            "status": "persisted_data" if binance_events > 0 else "no_persisted_data",
            "records": binance_events,
            "latest_timestamp": latest_event.isoformat() if latest_event else None,
            "notes": "Current simulator/training corpus uses persisted Binance replay data.",
        },
        {
            "exchange": "Binance",
            "market": "USD-M Futures",
            "adapter": "websocket_public_stream",
            "implemented": True,
            "connected": ws_sample.exists() and ws_sample.stat().st_size > 0,
            "training_enabled": False,
            "status": "verified_sample"
            if ws_sample.exists() and ws_sample.stat().st_size > 0
            else "not_verified",
            "records": 0,
            "latest_timestamp": None,
            "notes": "Collector exists, but no verified websocket sample is currently persisted.",
        },
        *[
            {
                "exchange": name,
                "market": market,
                "adapter": "not_implemented",
                "implemented": False,
                "connected": False,
                "training_enabled": False,
                "status": "not_connected",
                "records": 0,
                "latest_timestamp": None,
                "notes": "Provider adapter has not been implemented in this repo.",
            }
            for name, market in _UNIMPLEMENTED_CONNECTORS
        ],
    ]
    return Response(
        {
            "generated_at": timezone.now().isoformat(),
            "summary": {
                "implemented_connectors": sum(
                    1 for item in connectors if item["implemented"]
                ),
                "connected_connectors": sum(1 for item in connectors if item["connected"]),
                "training_enabled_connectors": sum(
                    1 for item in connectors if item["training_enabled"]
                ),
                "total_replay_events": total_events,
                "total_predictions": total_predictions,
                "total_alerts": total_alerts,
                "total_sessions": total_sessions,
                "trained_model_available": model_path.exists(),
                "training_runs": DemoTrainingRun.objects.count(),
                "model_metrics": ModelMetric.objects.count(),
            },
            "sources": [
                {
                    "source": row["source"],
                    "symbol": row["symbol"],
                    "records": row["events"],
                    "latest_timestamp": row["latest_timestamp"].isoformat()
                    if row["latest_timestamp"]
                    else None,
                }
                for row in source_rows
            ],
            "connectors": connectors,
        }
    )
