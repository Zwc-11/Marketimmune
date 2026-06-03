"""Server-rendered Django views for the original (pre-React) dashboard pages."""
from __future__ import annotations

from django.db.models import Max
from django.shortcuts import render
from django.views import View

from dashboard.demo_data import ensure_demo_seed
from dashboard.models import (
    DemoAgentEvent,
    DemoAgentTrace,
    DemoAlert,
    DemoFeatureRow,
    DemoMarketEvent,
    DemoPrediction,
    DemoTrainingRun,
)


class DashboardView(View):
    """Serve the main dashboard page."""

    def get(self, request):
        return render(
            request,
            "dashboard/index.html",
            {"title": "MarketImmune Benchmark Dashboard"},
        )


class DemoHomeView(View):
    """Serve the official demo-first homepage."""

    def get(self, request):
        ensure_demo_seed()
        return render(request, "dashboard/demo.html")


class LiveDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        return render(request, "dashboard/live.html")


class DataDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        counts = {
            "market_events": DemoMarketEvent.objects.count(),
            "synthetic_agent_events": DemoAgentEvent.objects.count(),
            "feature_rows": DemoFeatureRow.objects.count(),
            "predictions": DemoPrediction.objects.count(),
            "alerts": DemoAlert.objects.count(),
        }
        count_cards = [
            ("Market events", counts["market_events"]),
            ("Synthetic agent events", counts["synthetic_agent_events"]),
            ("Feature rows", counts["feature_rows"]),
            ("Predictions", counts["predictions"]),
            ("Alerts", counts["alerts"]),
        ]
        latest_timestamp = DemoMarketEvent.objects.aggregate(Max("timestamp"))[
            "timestamp__max"
        ]
        context = {
            "counts": counts,
            "count_cards": count_cards,
            "latest_timestamp": latest_timestamp,
            "market_events": DemoMarketEvent.objects.all()[:12],
            "agent_events": DemoAgentEvent.objects.select_related("market_event")[:12],
            "feature_rows": DemoFeatureRow.objects.select_related("market_event")[:12],
            "predictions": DemoPrediction.objects.select_related("feature_row")[:12],
            "alerts": DemoAlert.objects.select_related("prediction")[:12],
        }
        return render(request, "dashboard/data.html", context)


class TrainingDashboardView(View):
    _PROVENANCE = {
        "RuleEngine baseline": {
            "version": "v0.1-rule-baseline",
            "command": "python scripts/run_benchmark.py",
            "dataset_source": "Real Binance background data with synthetic agent scenarios",
            "split_method": "AegisBench train / validation / test scenario split",
            "metric_source": "benchmark",
            "artifact_timestamp": "2026-05-13",
        },
        "GRU-MTPP": {
            "version": "v0.1-gru-mtpp",
            "command": "python scripts/train_order_mtpp.py",
            "dataset_source": (
                "Synthetic order-event sequences over real-background market data"
            ),
            "split_method": "Variable-length sequence train / evaluation split",
            "metric_source": "synthetic + real-background",
            "artifact_timestamp": "2026-05-13",
        },
        "Order-S2P2 risk head": {
            "version": "v0.1-s2p2-nhp",
            "command": "python scripts/train_order_s2p2.py",
            "dataset_source": (
                "Synthetic unsafe-agent families with real Binance background context"
            ),
            "split_method": "Strict family-aware benchmark split",
            "metric_source": "benchmark",
            "artifact_timestamp": "2026-05-13",
        },
    }

    _FEATURE_IMPORTANCE = [
        {"name": "Order burst rate", "importance": 92},
        {"name": "Cancel rate", "importance": 84},
        {"name": "Spread widening", "importance": 68},
        {"name": "Side imbalance", "importance": 61},
        {"name": "Synthetic agent family", "importance": 54},
    ]

    def get(self, request):
        ensure_demo_seed()
        training_runs = [
            {
                "run": run,
                "pr_auc_pct": round(run.pr_auc * 100, 1),
                "f1_pct": round(run.f1 * 100, 1),
                "precision_pct": round(run.precision * 100, 1),
                "recall_pct": round(run.recall * 100, 1),
                "provenance": self._PROVENANCE.get(run.model_name, {}),
            }
            for run in DemoTrainingRun.objects.all()
        ]
        return render(
            request,
            "dashboard/training.html",
            {
                "training_runs": training_runs,
                "feature_importance": self._FEATURE_IMPORTANCE,
            },
        )


class AgentsDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        traces = DemoAgentTrace.objects.select_related(
            "prediction", "prediction__feature_row"
        )[:20]
        return render(request, "dashboard/agents.html", {"agent_traces": traces})


class ModelDashboardView(View):
    _FEATURE_IMPORTANCE = [
        {"name": "Order burst rate", "importance": 92},
        {"name": "Cancel rate", "importance": 84},
        {"name": "Spread bps", "importance": 68},
        {"name": "Side imbalance", "importance": 61},
        {"name": "Agent family", "importance": 54},
    ]

    def get(self, request):
        ensure_demo_seed()
        latest_prediction = DemoPrediction.objects.select_related("feature_row").first()
        latest_trace = None
        if latest_prediction:
            latest_trace = DemoAgentTrace.objects.filter(prediction=latest_prediction).first()
        best_run = DemoTrainingRun.objects.order_by("-pr_auc").first()
        return render(
            request,
            "dashboard/model.html",
            {
                "latest_prediction": latest_prediction,
                "latest_trace": latest_trace,
                "best_run": best_run,
                "feature_importance": self._FEATURE_IMPORTANCE,
            },
        )


class AlertsDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        alerts = DemoAlert.objects.select_related(
            "prediction", "prediction__feature_row"
        )[:30]
        context = {
            "alerts": alerts,
            "total_alerts": DemoAlert.objects.count(),
            "high_alerts": DemoAlert.objects.filter(severity="high").count(),
            "medium_alerts": DemoAlert.objects.filter(severity="medium").count(),
            "latest_alert": DemoAlert.objects.first(),
        }
        return render(request, "dashboard/alerts.html", context)


class BenchmarkDashboardView(View):
    def get(self, request):
        import json
        from pathlib import Path

        from django.conf import settings

        from dashboard.models import ModelMetric, TaskMetric

        ensure_demo_seed()
        phase79_path = Path(settings.BASE_DIR) / "reports" / "phase7_9_metrics.json"
        phase79 = {}
        if phase79_path.exists():
            phase79 = json.loads(phase79_path.read_text(encoding="utf-8"))
        context = {
            "task_metrics": TaskMetric.objects.filter(phase=7),
            "model_metrics": ModelMetric.objects.all().order_by("rank"),
            "training_runs": DemoTrainingRun.objects.all(),
            "phase79": phase79,
        }
        return render(request, "dashboard/benchmark.html", context)
