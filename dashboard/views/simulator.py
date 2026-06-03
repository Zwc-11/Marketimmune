"""Replay-cockpit views and the simulator state / control endpoints."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.shortcuts import render
from django.views import View
from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.models import (
    DecisionAuditTrace,
    ModelPrediction,
    ReplayEvent,
    ReplaySession,
    RiskAlert,
    SimulatedAgentOrder,
    SimulatedAgentTrade,
)
from dashboard.services import SimulatorService
from marketimmune.simulator import ReplayConfig, ScenarioRegistry

from ._common import load_benchmark_report


class SimulatorCockpitView(View):
    """Serve the main exchange replay cockpit."""

    def get(self, request):
        # Surface the scenario catalogue to the template so the dropdown
        # is built from the registry rather than hard-coded HTML options.
        return render(
            request,
            "dashboard/simulator_cockpit.html",
            {"scenarios": ScenarioRegistry.catalog()},
        )


class SimulatorReplayView(View):
    """Serve the historical BTC replay page."""

    def get(self, request):
        sessions = ReplaySession.objects.all()[:12]
        return render(request, "dashboard/simulator_replay.html", {"sessions": sessions})


class SimulatorAgentsView(View):
    """Serve the agent scenario selection and simulated order behavior page."""

    def get(self, request):
        return render(request, "dashboard/simulator_agents.html")


class SimulatorRiskView(View):
    """Serve the risk model predictions and alerts page."""

    def get(self, request):
        alerts = RiskAlert.objects.all()[:50]
        report = load_benchmark_report()
        importances = report.get("feature_importances", {}) if report else {}
        ranked_importances = sorted(importances.items(), key=lambda kv: -kv[1])[:10]
        return render(
            request,
            "dashboard/simulator_risk.html",
            {
                "alerts": alerts,
                "report": report,
                "ranked_importances": ranked_importances,
            },
        )


class SimulatorDataView(View):
    """Serve the data provenance and stored rows page."""

    def get(self, request):
        counts = {
            "sessions": ReplaySession.objects.count(),
            "events": ReplayEvent.objects.count(),
            "orders": SimulatedAgentOrder.objects.count(),
            "trades": SimulatedAgentTrade.objects.count(),
            "predictions": ModelPrediction.objects.count(),
            "alerts": RiskAlert.objects.count(),
        }
        return render(request, "dashboard/simulator_data.html", {"counts": counts})


class SimulatorAuditView(View):
    """Serve the decision audit traces page."""

    def get(self, request):
        traces = DecisionAuditTrace.objects.all()[:50]
        return render(request, "dashboard/simulator_audit.html", {"traces": traces})


@api_view(["GET"])
def get_simulator_state(request):
    """Return the most recent replay session as a fully-formed cockpit DTO.

    All market-data fields originate from the parquet lake; only the
    overlays under ``agent_orders`` / ``agent_trades`` are simulated.
    """
    try:
        return Response(SimulatorService().snapshot())
    except Exception as exc:  # noqa: BLE001 — surface to UI for diagnosis.
        return Response(
            {"error": f"Failed to assemble simulator state: {exc}"},
            status=500,
        )


@api_view(["GET"])
def risk_head_health(request):
    """Live-measure the ML risk head's inference latency.

    Returns p50 / p95 / p99 in milliseconds plus the persisted offline
    benchmark report. When no trained model exists on disk the response
    reports ``available: false`` so the UI can show a "train me" banner.
    """
    import time

    import numpy as np

    from marketimmune.models import FEATURE_ORDER, RiskScorer

    model_path = Path(settings.BASE_DIR) / "data" / "models" / "risk_head.joblib"
    if not model_path.exists():
        return Response(
            {
                "available": False,
                "message": "No trained model. Run `python scripts/train_risk_head.py`.",
                "report": load_benchmark_report(),
            }
        )

    samples = int(request.GET.get("samples", 500))
    scorer = RiskScorer.load(model_path)
    rng = np.random.default_rng(0)
    sample = {name: float(rng.random() * 5) for name in FEATURE_ORDER}
    times: list[float] = []
    for _ in range(samples):
        start = time.perf_counter()
        scorer.predict(sample)
        times.append((time.perf_counter() - start) * 1000.0)
    arr = np.asarray(times)
    return Response(
        {
            "available": True,
            "model_name": scorer.MODEL_NAME,
            "samples": samples,
            "p50_ms": float(np.percentile(arr, 50)),
            "p95_ms": float(np.percentile(arr, 95)),
            "p99_ms": float(np.percentile(arr, 99)),
            "mean_ms": float(arr.mean()),
            "report": load_benchmark_report(),
            "feature_importances": scorer.feature_importances,
        }
    )


@api_view(["POST", "GET"])
def control_replay(request):
    """Start a new replay session for a chosen scenario."""
    payload = request.data if hasattr(request, "data") else {}
    scenario = payload.get("scenario") or request.GET.get("scenario", "spoofing_layering")
    limit = int(payload.get("limit") or request.GET.get("limit", 1440))
    symbol = payload.get("symbol") or request.GET.get("symbol", "BTCUSDT")
    speed = int(payload.get("speed") or request.GET.get("speed", 10))
    replay_date = payload.get("date") or request.GET.get("date")
    if scenario not in ScenarioRegistry.names():
        return Response(
            {"status": "error", "message": f"Unknown scenario {scenario!r}."},
            status=400,
        )
    try:
        SimulatorService().start(
            ReplayConfig(
                symbol=symbol,
                scenario_name=scenario,
                speed=speed,
                limit=limit,
                replay_date=replay_date,
            )
        )
        return Response({"status": "success", "message": f"Started scenario {scenario}."})
    except Exception as exc:  # noqa: BLE001
        return Response({"status": "error", "message": str(exc)}, status=500)
