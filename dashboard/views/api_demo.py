"""JSON endpoints used by the legacy demo dashboard and live-tick poller."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.demo_data import create_demo_tick, ensure_demo_seed
from dashboard.models import (
    BenchmarkMetrics,
    DemoAgentEvent,
    DemoAgentTrace,
    DemoAlert,
    DemoFeatureRow,
    DemoMarketEvent,
    DemoPrediction,
    DemoTrainingRun,
    ModelMetric,
    ProjectStats,
    TaskMetric,
)
from dashboard.serializers import (
    BenchmarkMetricsSerializer,
    ModelMetricSerializer,
    ProjectStatsSerializer,
    TaskMetricSerializer,
)

_SCENARIO_LABELS = {
    "latency-burst-sweeper": "latency burst",
    "inventory-balancer": "inventory rebalancer",
}


def _market_regime(spread_bps: float, risk_score: float) -> str:
    if spread_bps >= 4:
        return "thin liquidity"
    if risk_score >= 0.75:
        return "volatile"
    return "calm"


@api_view(["GET"])
def project_stats(request):
    """Get overall project statistics."""
    try:
        stats = ProjectStats.objects.latest("last_updated")
        return Response(ProjectStatsSerializer(stats).data)
    except ProjectStats.DoesNotExist:
        return Response(
            {"error": "Project stats not available"}, status=status.HTTP_404_NOT_FOUND
        )


@api_view(["GET"])
def dashboard_summary(request):
    """Get comprehensive dashboard summary."""
    try:
        stats = ProjectStats.objects.latest("last_updated")
        task_metrics = TaskMetric.objects.all()
        model_metrics = ModelMetric.objects.all().order_by("rank")

        return Response(
            {
                "stats": ProjectStatsSerializer(stats).data,
                "task_metrics": TaskMetricSerializer(task_metrics, many=True).data,
                "model_metrics": ModelMetricSerializer(model_metrics, many=True).data,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            {"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
def leaderboard(request):
    """Get model leaderboard."""
    models = ModelMetric.objects.all().order_by("rank")
    return Response(ModelMetricSerializer(models, many=True).data)


@api_view(["GET"])
def phase_details(request, phase_id):
    """Get details for a specific phase."""
    try:
        benchmark = BenchmarkMetrics.objects.get(phase=phase_id)
        task_metrics = TaskMetric.objects.filter(phase=phase_id)
        return Response(
            {
                "benchmark": BenchmarkMetricsSerializer(benchmark).data,
                "tasks": TaskMetricSerializer(task_metrics, many=True).data,
            }
        )
    except BenchmarkMetrics.DoesNotExist:
        return Response({"error": "Phase not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET", "POST"])
def live_demo_tick(request):
    """Create and return one live demo tick for browser polling."""
    tick = create_demo_tick()
    previous_feature = DemoFeatureRow.objects.exclude(id=tick.feature_row.id).first()
    previous_prediction = DemoPrediction.objects.exclude(id=tick.prediction.id).first()
    current_cancel = tick.feature_row.features.get("cancel_rate_1s", 0)
    previous_cancel = previous_feature.features.get("cancel_rate_1s", 0) if previous_feature else 0
    previous_score = previous_prediction.risk_score if previous_prediction else 0
    risk_direction = "increased" if tick.prediction.risk_score >= previous_score else "decreased"
    scenario_name = _SCENARIO_LABELS.get(
        tick.agent_event.strategy, tick.agent_event.strategy.replace("-", " ")
    )
    imbalance = tick.feature_row.features.get("side_imbalance", 0)
    why_risk_changed = (
        f"Risk {risk_direction} because cancel-to-fill proxy moved from "
        f"{previous_cancel:.2f} to {current_cancel:.2f} and order-book imbalance "
        f"shifted to {imbalance:.2f}."
    )
    latest_alert = tick.alert.message if tick.alert else "No alert; monitoring normal flow"
    return Response(
        {
            "event_id": tick.market_event.id,
            "prediction_id": tick.prediction.id,
            "timestamp": tick.market_event.timestamp.isoformat(),
            "symbol": tick.market_event.symbol,
            "mid_price": tick.market_event.mid_price,
            "scenario_name": scenario_name,
            "market_regime": _market_regime(
                tick.market_event.spread_bps, tick.prediction.risk_score
            ),
            "simulated_order": tick.agent_event.simulated_order,
            "simulated_trade": tick.agent_event.simulated_trade,
            "current_risk_score": tick.prediction.risk_score,
            "predicted_risk_label": tick.prediction.risk_label,
            "latest_alert": latest_alert,
            "why_risk_changed": why_risk_changed,
            "features": tick.feature_row.features,
            "agent_reasoning": {
                "observation": tick.agent_trace.observation,
                "risk_evidence": tick.agent_trace.risk_evidence,
                "model_interpretation": tick.prediction.explanation,
                "policy_decision": tick.agent_trace.decision,
                "recommended_control": tick.agent_trace.action,
                "confidence": tick.agent_trace.confidence,
            },
        }
    )


@api_view(["GET"])
def demo_counts(request):
    ensure_demo_seed()
    return Response(
        {
            "market_events": DemoMarketEvent.objects.count(),
            "synthetic_agent_events": DemoAgentEvent.objects.count(),
            "features": DemoFeatureRow.objects.count(),
            "predictions": DemoPrediction.objects.count(),
            "alerts": DemoAlert.objects.count(),
            "agent_traces": DemoAgentTrace.objects.count(),
            "training_runs": DemoTrainingRun.objects.count(),
        }
    )
