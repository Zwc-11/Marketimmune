import json
from pathlib import Path

from django.conf import settings
from django.db.models import Max
from django.shortcuts import render
from django.views import View
from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from dashboard.demo_data import create_demo_tick, ensure_demo_seed
from dashboard.models import (
    BenchmarkMetrics,
    DecisionAuditTrace,
    DemoAgentEvent,
    DemoAgentTrace,
    DemoAlert,
    DemoFeatureRow,
    DemoMarketEvent,
    DemoPrediction,
    DemoTrainingRun,
    ImmuneLoopRun,
    ImmuneMemoryEntry,
    ModelMetric,
    ModelPrediction,
    ModelPromotionDecision,
    ProjectStats,
    ReplayEvent,
    ReplaySession,
    RiskAlert,
    SimulatedAgentOrder,
    SimulatedAgentTrade,
    TaskMetric,
)
from dashboard.serializers import (
    BenchmarkMetricsSerializer,
    DemoAgentEventSerializer,
    DemoAgentTraceSerializer,
    DemoAlertSerializer,
    DemoFeatureRowSerializer,
    DemoMarketEventSerializer,
    DemoPredictionSerializer,
    DemoTrainingRunSerializer,
    ModelMetricSerializer,
    ProjectStatsSerializer,
    TaskMetricSerializer,
)
from dashboard.services import AgenticService, SimulatorService
from marketimmune.simulator import ReplayConfig, ScenarioRegistry


def _load_benchmark_report() -> dict:
    """Load the gradient-boosting risk-head benchmark report.

    Returns an empty dict when the artifact has not been produced yet;
    the template handles the "untrained" UI gracefully.
    """
    path = Path(settings.BASE_DIR) / "reports" / "risk_head_benchmark.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — bad JSON shouldn't break the dashboard.
        return {}


class DashboardView(View):
    """Serve the main dashboard page"""
    def get(self, request):
        context = {
            'title': 'MarketImmune Benchmark Dashboard',
        }
        return render(request, 'dashboard/index.html', context)


class DemoHomeView(View):
    """Serve the official demo-first homepage."""

    def get(self, request):
        ensure_demo_seed()
        return render(request, 'dashboard/demo.html')


class LiveDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        return render(request, 'dashboard/live.html')


class DataDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        counts = {
            'market_events': DemoMarketEvent.objects.count(),
            'synthetic_agent_events': DemoAgentEvent.objects.count(),
            'feature_rows': DemoFeatureRow.objects.count(),
            'predictions': DemoPrediction.objects.count(),
            'alerts': DemoAlert.objects.count(),
        }
        count_cards = [
            ('Market events', counts['market_events']),
            ('Synthetic agent events', counts['synthetic_agent_events']),
            ('Feature rows', counts['feature_rows']),
            ('Predictions', counts['predictions']),
            ('Alerts', counts['alerts']),
        ]
        latest_timestamp = DemoMarketEvent.objects.aggregate(Max('timestamp'))['timestamp__max']
        context = {
            'counts': counts,
            'count_cards': count_cards,
            'latest_timestamp': latest_timestamp,
            'market_events': DemoMarketEvent.objects.all()[:12],
            'agent_events': DemoAgentEvent.objects.select_related('market_event')[:12],
            'feature_rows': DemoFeatureRow.objects.select_related('market_event')[:12],
            'predictions': DemoPrediction.objects.select_related('feature_row')[:12],
            'alerts': DemoAlert.objects.select_related('prediction')[:12],
        }
        return render(request, 'dashboard/data.html', context)


class TrainingDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        provenance = {
            'RuleEngine baseline': {
                'version': 'v0.1-rule-baseline',
                'command': 'python scripts/run_benchmark.py',
                'dataset_source': 'Real Binance background data with synthetic agent scenarios',
                'split_method': 'AegisBench train / validation / test scenario split',
                'metric_source': 'benchmark',
                'artifact_timestamp': '2026-05-13',
            },
            'GRU-MTPP': {
                'version': 'v0.1-gru-mtpp',
                'command': 'python scripts/train_order_mtpp.py',
                'dataset_source': (
                    'Synthetic order-event sequences over real-background market data'
                ),
                'split_method': 'Variable-length sequence train / evaluation split',
                'metric_source': 'synthetic + real-background',
                'artifact_timestamp': '2026-05-13',
            },
            'Order-S2P2 risk head': {
                'version': 'v0.1-s2p2-nhp',
                'command': 'python scripts/train_order_s2p2.py',
                'dataset_source': (
                    'Synthetic unsafe-agent families with real Binance background context'
                ),
                'split_method': 'Strict family-aware benchmark split',
                'metric_source': 'benchmark',
                'artifact_timestamp': '2026-05-13',
            },
        }
        training_runs = []
        for run in DemoTrainingRun.objects.all():
            training_runs.append({
                'run': run,
                'pr_auc_pct': round(run.pr_auc * 100, 1),
                'f1_pct': round(run.f1 * 100, 1),
                'precision_pct': round(run.precision * 100, 1),
                'recall_pct': round(run.recall * 100, 1),
                'provenance': provenance.get(run.model_name, {}),
            })
        feature_importance = [
            {'name': 'Order burst rate', 'importance': 92},
            {'name': 'Cancel rate', 'importance': 84},
            {'name': 'Spread widening', 'importance': 68},
            {'name': 'Side imbalance', 'importance': 61},
            {'name': 'Synthetic agent family', 'importance': 54},
        ]
        return render(
            request,
            'dashboard/training.html',
            {'training_runs': training_runs, 'feature_importance': feature_importance},
        )


class AgentsDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        traces = DemoAgentTrace.objects.select_related('prediction', 'prediction__feature_row')[:20]
        return render(request, 'dashboard/agents.html', {'agent_traces': traces})


class ModelDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        latest_prediction = DemoPrediction.objects.select_related('feature_row').first()
        latest_trace = None
        if latest_prediction:
            latest_trace = DemoAgentTrace.objects.filter(prediction=latest_prediction).first()
        best_run = DemoTrainingRun.objects.order_by('-pr_auc').first()
        feature_importance = [
            {'name': 'Order burst rate', 'importance': 92},
            {'name': 'Cancel rate', 'importance': 84},
            {'name': 'Spread bps', 'importance': 68},
            {'name': 'Side imbalance', 'importance': 61},
            {'name': 'Agent family', 'importance': 54},
        ]
        return render(
            request,
            'dashboard/model.html',
            {
                'latest_prediction': latest_prediction,
                'latest_trace': latest_trace,
                'best_run': best_run,
                'feature_importance': feature_importance,
            },
        )


class AlertsDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        alerts = DemoAlert.objects.select_related('prediction', 'prediction__feature_row')[:30]
        context = {
            'alerts': alerts,
            'total_alerts': DemoAlert.objects.count(),
            'high_alerts': DemoAlert.objects.filter(severity='high').count(),
            'medium_alerts': DemoAlert.objects.filter(severity='medium').count(),
            'latest_alert': DemoAlert.objects.first(),
        }
        return render(request, 'dashboard/alerts.html', context)


class BenchmarkDashboardView(View):
    def get(self, request):
        ensure_demo_seed()
        phase79_path = Path(settings.BASE_DIR) / 'reports' / 'phase7_9_metrics.json'
        phase79 = {}
        if phase79_path.exists():
            phase79 = json.loads(phase79_path.read_text(encoding='utf-8'))
        context = {
            'task_metrics': TaskMetric.objects.filter(phase=7),
            'model_metrics': ModelMetric.objects.all().order_by('rank'),
            'training_runs': DemoTrainingRun.objects.all(),
            'phase79': phase79,
        }
        return render(request, 'dashboard/benchmark.html', context)


class TaskMetricViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for task metrics"""
    queryset = TaskMetric.objects.all()
    serializer_class = TaskMetricSerializer


class ModelMetricViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for model metrics"""
    queryset = ModelMetric.objects.all()
    serializer_class = ModelMetricSerializer


class BenchmarkMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for benchmark metrics"""
    queryset = BenchmarkMetrics.objects.all()
    serializer_class = BenchmarkMetricsSerializer


class DemoMarketEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoMarketEvent.objects.all()
    serializer_class = DemoMarketEventSerializer


class DemoAgentEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAgentEvent.objects.select_related('market_event')
    serializer_class = DemoAgentEventSerializer


class DemoFeatureRowViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoFeatureRow.objects.select_related('market_event')
    serializer_class = DemoFeatureRowSerializer


class DemoPredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoPrediction.objects.select_related('feature_row')
    serializer_class = DemoPredictionSerializer


class DemoAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAlert.objects.select_related('prediction')
    serializer_class = DemoAlertSerializer


class DemoTrainingRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoTrainingRun.objects.all()
    serializer_class = DemoTrainingRunSerializer


class DemoAgentTraceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAgentTrace.objects.select_related('prediction')
    serializer_class = DemoAgentTraceSerializer


@api_view(['GET'])
def project_stats(request):
    """Get overall project statistics"""
    try:
        stats = ProjectStats.objects.latest('last_updated')
        serializer = ProjectStatsSerializer(stats)
        return Response(serializer.data)
    except ProjectStats.DoesNotExist:
        return Response({'error': 'Project stats not available'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def dashboard_summary(request):
    """Get comprehensive dashboard summary"""
    try:
        stats = ProjectStats.objects.latest('last_updated')
        task_metrics = TaskMetric.objects.all()
        model_metrics = ModelMetric.objects.all().order_by('rank')
        
        return Response({
            'stats': ProjectStatsSerializer(stats).data,
            'task_metrics': TaskMetricSerializer(task_metrics, many=True).data,
            'model_metrics': ModelMetricSerializer(model_metrics, many=True).data,
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def leaderboard(request):
    """Get model leaderboard"""
    models = ModelMetric.objects.all().order_by('rank')
    serializer = ModelMetricSerializer(models, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def phase_details(request, phase_id):
    """Get details for a specific phase"""
    try:
        benchmark = BenchmarkMetrics.objects.get(phase=phase_id)
        task_metrics = TaskMetric.objects.filter(phase=phase_id)
        
        return Response({
            'benchmark': BenchmarkMetricsSerializer(benchmark).data,
            'tasks': TaskMetricSerializer(task_metrics, many=True).data,
        })
    except BenchmarkMetrics.DoesNotExist:
        return Response({'error': 'Phase not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET', 'POST'])
def live_demo_tick(request):
    """Create and return one live demo tick for browser polling."""

    tick = create_demo_tick()
    previous_feature = DemoFeatureRow.objects.exclude(id=tick.feature_row.id).first()
    previous_prediction = DemoPrediction.objects.exclude(id=tick.prediction.id).first()
    current_cancel = tick.feature_row.features.get('cancel_rate_1s', 0)
    previous_cancel = 0
    if previous_feature:
        previous_cancel = previous_feature.features.get('cancel_rate_1s', 0)
    previous_score = previous_prediction.risk_score if previous_prediction else 0
    risk_direction = 'increased' if tick.prediction.risk_score >= previous_score else 'decreased'
    scenario_name = {
        'latency-burst-sweeper': 'latency burst',
        'inventory-balancer': 'inventory rebalancer',
    }.get(tick.agent_event.strategy, tick.agent_event.strategy.replace('-', ' '))
    if tick.market_event.spread_bps >= 4:
        market_regime = 'thin liquidity'
    elif tick.prediction.risk_score >= 0.75:
        market_regime = 'volatile'
    else:
        market_regime = 'calm'
    imbalance = tick.feature_row.features.get('side_imbalance', 0)
    why_risk_changed = (
        f"Risk {risk_direction} because cancel-to-fill proxy moved from "
        f"{previous_cancel:.2f} to {current_cancel:.2f} and order-book imbalance "
        f"shifted to {imbalance:.2f}."
    )
    latest_alert = tick.alert.message if tick.alert else 'No alert; monitoring normal flow'
    return Response({
        'event_id': tick.market_event.id,
        'prediction_id': tick.prediction.id,
        'timestamp': tick.market_event.timestamp.isoformat(),
        'symbol': tick.market_event.symbol,
        'mid_price': tick.market_event.mid_price,
        'scenario_name': scenario_name,
        'market_regime': market_regime,
        'simulated_order': tick.agent_event.simulated_order,
        'simulated_trade': tick.agent_event.simulated_trade,
        'current_risk_score': tick.prediction.risk_score,
        'predicted_risk_label': tick.prediction.risk_label,
        'latest_alert': latest_alert,
        'why_risk_changed': why_risk_changed,
        'features': tick.feature_row.features,
        'agent_reasoning': {
            'observation': tick.agent_trace.observation,
            'risk_evidence': tick.agent_trace.risk_evidence,
            'model_interpretation': tick.prediction.explanation,
            'policy_decision': tick.agent_trace.decision,
            'recommended_control': tick.agent_trace.action,
            'confidence': tick.agent_trace.confidence,
        },
    })


@api_view(['GET'])
def demo_counts(request):
    ensure_demo_seed()
    return Response({
        'market_events': DemoMarketEvent.objects.count(),
        'synthetic_agent_events': DemoAgentEvent.objects.count(),
        'features': DemoFeatureRow.objects.count(),
        'predictions': DemoPrediction.objects.count(),
        'alerts': DemoAlert.objects.count(),
        'agent_traces': DemoAgentTrace.objects.count(),
        'training_runs': DemoTrainingRun.objects.count(),
    })


class SimulatorCockpitView(View):
    """Serve the main exchange replay cockpit."""
    def get(self, request):
        # Surface the scenario catalogue to the template so the dropdown
        # is built from the registry rather than hard-coded HTML options.
        return render(
            request,
            'dashboard/simulator_cockpit.html',
            {'scenarios': ScenarioRegistry.catalog()},
        )


class SimulatorReplayView(View):
    """Serve the historical BTC replay page."""
    def get(self, request):
        sessions = ReplaySession.objects.all()[:12]
        return render(request, 'dashboard/simulator_replay.html', {'sessions': sessions})


class SimulatorAgentsView(View):
    """Serve the agent scenario selection and simulated order behavior page."""
    def get(self, request):
        return render(request, 'dashboard/simulator_agents.html')


class SimulatorRiskView(View):
    """Serve the risk model predictions and alerts page."""
    def get(self, request):
        alerts = RiskAlert.objects.all()[:50]
        report = _load_benchmark_report()
        importances = report.get("feature_importances", {}) if report else {}
        ranked_importances = sorted(
            importances.items(), key=lambda kv: -kv[1]
        )[:10]
        return render(
            request,
            'dashboard/simulator_risk.html',
            {
                'alerts': alerts,
                'report': report,
                'ranked_importances': ranked_importances,
            },
        )


class SimulatorDataView(View):
    """Serve the data provenance and stored rows page."""
    def get(self, request):
        counts = {
            'sessions': ReplaySession.objects.count(),
            'events': ReplayEvent.objects.count(),
            'orders': SimulatedAgentOrder.objects.count(),
            'trades': SimulatedAgentTrade.objects.count(),
            'predictions': ModelPrediction.objects.count(),
            'alerts': RiskAlert.objects.count(),
        }
        return render(request, 'dashboard/simulator_data.html', {'counts': counts})


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
        from django.conf import settings as _settings
        from django.http import HttpResponse

        bundle = Path(_settings.BASE_DIR) / self.BUNDLE_PATH
        if not bundle.exists():
            return HttpResponse(
                "<h1>React bundle missing</h1>"
                "<p>Build the frontend first:</p>"
                "<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>",
                status=503,
                content_type="text/html",
            )
        return HttpResponse(
            bundle.read_text(encoding="utf-8"),
            content_type="text/html",
        )


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
            'dashboard/agentic_loop.html',
            {
                'loop': loop,
                'agent_runs': agent_runs,
                'cases': cases,
                'decisions': decisions,
                'proposal': proposal,
                'memories': memories,
                'recent_loops': recent_loops,
                'promotion': promotion,
                'recent_promotions': recent_promotions,
            },
        )


@api_view(['GET'])
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
        "loop": None,
        "memories": [
            {
                "memory_id": m.memory_id,
                "threat_name": m.threat_name,
                "description": m.description,
                "key_signals": m.key_signals,
                "best_detector": m.best_detector,
                "novelty_score": m.novelty_score,
                "times_seen": m.times_seen,
                "last_seen_at": m.last_seen_at.isoformat(),
            }
            for m in memories
        ],
        "promotion": (
            {
                "decision_id": promotion.decision_id,
                "verdict": promotion.verdict,
                "candidate_model": promotion.candidate_model,
                "incumbent_model": promotion.incumbent_model,
                "rationale": promotion.rationale,
                "metrics": promotion.metrics,
                "created_at": promotion.created_at.isoformat(),
            } if promotion else None
        ),
        "recent_loops": [
            {
                "loop_id": lr.loop_id,
                "started_at": lr.started_at.isoformat(),
                "duration_ms": lr.duration_ms,
                "aggregate_posture": lr.aggregate_posture,
                "alert_count": lr.alert_count,
                "case_count": lr.case_count,
                "new_memory_count": lr.new_memory_count,
                "proposal_name": lr.proposal_name,
            }
            for lr in recent_loops
        ],
    }
    if loop:
        proposal = loop.proposals.first()
        payload["loop"] = {
            "loop_id": loop.loop_id,
            "started_at": loop.started_at.isoformat(),
            "duration_ms": loop.duration_ms,
            "aggregate_posture": loop.aggregate_posture,
            "alert_count": loop.alert_count,
            "case_count": loop.case_count,
            "new_memory_count": loop.new_memory_count,
            "agent_runs": [
                {
                    "agent_name": ar.agent_name,
                    "goal": ar.goal,
                    "duration_ms": ar.duration_ms,
                    "success": ar.success,
                    "tool_call_count": ar.tool_calls.count(),
                    "trace_count": ar.decision_traces.count(),
                }
                for ar in loop.agent_runs.all()
            ],
            "proposal": (
                {
                    "name": proposal.name,
                    "base_scenario": proposal.base_scenario,
                    "cover_scenario": proposal.cover_scenario,
                    "expected_attack": proposal.expected_attack,
                    "evasion_strategy": proposal.evasion_strategy,
                    "difficulty": proposal.difficulty,
                    "rationale": proposal.rationale,
                    "rationale_source": proposal.features.get("rationale_source"),
                } if proposal else None
            ),
            "cases": [
                {
                    "case_id": c.case_id,
                    "suspected_behavior": c.suspected_behavior,
                    "severity": c.severity,
                    "confidence": c.confidence,
                    "matched_rules": c.matched_rules,
                    "explanation": c.explanation,
                    "narrative": c.model_evidence.get("narrative", ""),
                    "narrative_source": c.model_evidence.get("narrative_source", "deterministic"),
                    "feature_evidence": c.feature_evidence,
                    "model_evidence": {
                        k: v for k, v in c.model_evidence.items()
                        if k not in {"narrative", "narrative_source"}
                    },
                    "recommended_next_step": c.recommended_next_step,
                }
                for c in loop.cases.all()
            ],
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "case_id": d.case_id,
                    "recommended_action": d.recommended_action,
                    "severity": d.severity,
                    "rationale": d.rationale,
                    "confidence": d.confidence,
                }
                for d in loop.policy_decisions.all()
            ],
        }
    return Response(payload)


@api_view(['GET'])
def agentic_llm_status(request):
    """Report whether the agentic loop is configured to call an LLM.

    Never returns the API key itself. Just the provider name, model
    id, and the on/off flag — enough for the UI to show a badge.
    """
    import os

    from marketimmune.agentic import build_default_llm

    flag = (os.environ.get("MARKETIMMUNE_USE_LLM") or "").strip().lower()
    requested = flag in {"1", "true", "yes", "on"}
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    client = build_default_llm(load_env=False)  # already loaded by manage.py
    enabled = client.name != "null"
    return Response({
        "enabled": enabled,
        "requested": requested,
        "has_key": has_key,
        "provider": client.name,
        "model": getattr(client, "model", ""),
    })


@api_view(['POST'])
def trigger_immune_loop(request):
    """Run one immune loop synchronously and return its summary."""
    difficulty = request.data.get('difficulty', 'medium') if hasattr(request, 'data') else 'medium'
    limit = int(request.data.get('limit', 30)) if hasattr(request, 'data') else 30
    try:
        loop = AgenticService.run_once(difficulty=difficulty, tick_limit=limit)
    except Exception as exc:  # noqa: BLE001
        return Response({'error': str(exc)}, status=500)
    return Response({
        'loop_id': loop.loop_id,
        'aggregate_posture': loop.aggregate_posture,
        'alert_count': loop.alert_count,
        'case_count': loop.case_count,
        'new_memory_count': loop.new_memory_count,
        'duration_ms': loop.duration_ms,
        'proposal_name': loop.proposal_name,
    })


class SimulatorAuditView(View):
    """Serve the decision audit traces page."""
    def get(self, request):
        traces = DecisionAuditTrace.objects.all()[:50]
        return render(request, 'dashboard/simulator_audit.html', {'traces': traces})


@api_view(['GET'])
def get_simulator_state(request):
    """Return the most recent replay session as a fully-formed cockpit DTO.

    All market-data fields originate from the parquet lake; only the
    overlays under `agent_orders` / `agent_trades` are simulated.
    """
    try:
        return Response(SimulatorService().snapshot())
    except Exception as exc:  # noqa: BLE001 — surface to UI for diagnosis.
        return Response(
            {"error": f"Failed to assemble simulator state: {exc}"},
            status=500,
        )


@api_view(['GET'])
def risk_head_health(request):
    """Live-measure the ML risk head's inference latency.

    Returns p50 / p95 / p99 in milliseconds plus the persisted offline
    benchmark report. When no trained model exists on disk the response
    reports `available: false` so the UI can show a "train me" banner.
    """
    import time

    import numpy as np

    from marketimmune.models import FEATURE_ORDER, RiskScorer

    model_path = Path(settings.BASE_DIR) / "data" / "models" / "risk_head.joblib"
    if not model_path.exists():
        return Response({
            "available": False,
            "message": "No trained model. Run `python scripts/train_risk_head.py`.",
            "report": _load_benchmark_report(),
        })

    n = int(request.GET.get('samples', 500))
    scorer = RiskScorer.load(model_path)
    rng = np.random.default_rng(0)
    sample = {name: float(rng.random() * 5) for name in FEATURE_ORDER}
    times: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        scorer.predict(sample)
        times.append((time.perf_counter() - start) * 1000.0)
    arr = np.asarray(times)
    return Response({
        "available": True,
        "model_name": scorer.MODEL_NAME,
        "samples": n,
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "mean_ms": float(arr.mean()),
        "report": _load_benchmark_report(),
        "feature_importances": scorer.feature_importances,
    })


@api_view(['POST', 'GET'])
def control_replay(request):
    """Start a new replay session for a chosen scenario."""
    payload = request.data if hasattr(request, 'data') else {}
    scenario = payload.get('scenario') or request.GET.get('scenario', 'spoofing_layering')
    limit = int(payload.get('limit') or request.GET.get('limit', 1440))
    symbol = payload.get('symbol') or request.GET.get('symbol', 'BTCUSDT')
    speed = int(payload.get('speed') or request.GET.get('speed', 10))
    replay_date = payload.get('date') or request.GET.get('date')
    if scenario not in ScenarioRegistry.names():
        return Response(
            {'status': 'error', 'message': f"Unknown scenario {scenario!r}."},
            status=400,
        )
    try:
        SimulatorService().start(ReplayConfig(
            symbol=symbol,
            scenario_name=scenario,
            speed=speed,
            limit=limit,
            replay_date=replay_date,
        ))
        return Response({'status': 'success', 'message': f"Started scenario {scenario}."})
    except Exception as exc:  # noqa: BLE001
        return Response({'status': 'error', 'message': str(exc)}, status=500)
