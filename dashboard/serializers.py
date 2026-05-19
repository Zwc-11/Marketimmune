from rest_framework import serializers

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


class TaskMetricSerializer(serializers.ModelSerializer):
    task_display = serializers.CharField(source='get_task_name_display', read_only=True)

    class Meta:
        model = TaskMetric
        fields = [
            'id',
            'task_name',
            'task_display',
            'pr_auc',
            'auroc',
            'f1_score',
            'other_metrics',
            'status',
            'phase',
        ]


class ModelMetricSerializer(serializers.ModelSerializer):
    model_display = serializers.CharField(source='get_model_name_display', read_only=True)

    class Meta:
        model = ModelMetric
        fields = [
            'id',
            'model_name',
            'model_display',
            'task_name',
            'pr_auc',
            'auroc',
            'inference_latency_ms',
            'extra_metrics',
            'phase',
            'rank',
        ]


class BenchmarkMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BenchmarkMetrics
        fields = ['phase', 'title', 'data', 'created_at', 'updated_at']


class ProjectStatsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectStats
        fields = [
            'total_examples',
            'total_tasks',
            'total_phases',
            'total_models',
            'test_coverage',
            'type_errors',
            'linting_violations',
            'test_count',
            'last_updated',
        ]


class DemoMarketEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoMarketEvent
        fields = [
            'id',
            'timestamp',
            'symbol',
            'mid_price',
            'bid_price',
            'ask_price',
            'spread_bps',
            'source',
        ]


class DemoAgentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoAgentEvent
        fields = [
            'id',
            'market_event_id',
            'agent_id',
            'strategy',
            'simulated_order',
            'simulated_trade',
            'side',
            'quantity',
            'order_price',
        ]


class DemoFeatureRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoFeatureRow
        fields = ['id', 'market_event_id', 'features', 'created_at']


class DemoPredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoPrediction
        fields = [
            'id',
            'feature_row_id',
            'model_name',
            'risk_score',
            'risk_label',
            'explanation',
            'created_at',
        ]


class DemoAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoAlert
        fields = ['id', 'prediction_id', 'severity', 'message', 'created_at']


class DemoTrainingRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoTrainingRun
        fields = [
            'id',
            'model_name',
            'dataset_version',
            'split_summary',
            'pr_auc',
            'f1',
            'precision',
            'recall',
            'lead_time_ms',
            'artifact_path',
            'created_at',
        ]


class DemoAgentTraceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemoAgentTrace
        fields = [
            'id',
            'prediction_id',
            'observation',
            'risk_evidence',
            'decision',
            'action',
            'confidence',
            'created_at',
        ]
