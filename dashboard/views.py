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
