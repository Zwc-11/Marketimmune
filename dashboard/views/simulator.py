"""Replay-cockpit views and the simulator state / control endpoints.

The React SPA uses the bundled ``simEngine`` for live simulation; these JSON
endpoints remain for the legacy Django replay cockpit template.
"""
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
            {
                "error": f"Failed to assemble simulator state: {exc}",
                "code": "snapshot_failed",
            },
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


def _simulator_control_payload(request) -> dict:
    """Merge JSON body and query params for ``control_replay``."""
    body = request.data if hasattr(request, "data") and request.data else {}
    payload = dict(body) if isinstance(body, dict) else {}
    for key in ("scenario", "limit", "symbol", "speed", "date"):
        if key not in payload and request.GET.get(key) is not None:
            payload[key] = request.GET.get(key)
    return payload


@api_view(["POST", "GET"])
def control_replay(request):
    """Start a new replay session for a chosen scenario."""
    from dashboard.api_validators import parse_simulator_control_request

    parsed, error = parse_simulator_control_request(_simulator_control_payload(request))
    if error:
        return Response(
            {
                "status": "error",
                "message": error["error"],
                "error": error["error"],
                "code": error["code"],
            },
            status=400,
        )
    try:
        SimulatorService().start(
            ReplayConfig(
                symbol=parsed["symbol"],
                scenario_name=parsed["scenario"],
                speed=parsed["speed"],
                limit=parsed["limit"],
                replay_date=parsed["replay_date"],
            )
        )
        scenario = parsed["scenario"]
        return Response({"status": "success", "message": f"Started scenario {scenario}."})
    except ValueError as exc:
        return Response(
            {
                "status": "error",
                "message": str(exc),
                "error": str(exc),
                "code": "validation_error",
            },
            status=400,
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            {
                "status": "error",
                "message": str(exc),
                "error": str(exc),
                "code": "replay_failed",
            },
            status=500,
        )
