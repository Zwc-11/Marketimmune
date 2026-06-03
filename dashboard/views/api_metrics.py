"""DRF ViewSets exposing model / benchmark / demo records over the REST API."""
from __future__ import annotations

from rest_framework import viewsets

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
    TaskMetricSerializer,
)


class TaskMetricViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for task metrics."""

    queryset = TaskMetric.objects.all()
    serializer_class = TaskMetricSerializer


class ModelMetricViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for model metrics."""

    queryset = ModelMetric.objects.all()
    serializer_class = ModelMetricSerializer


class BenchmarkMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """API endpoint for benchmark metrics."""

    queryset = BenchmarkMetrics.objects.all()
    serializer_class = BenchmarkMetricsSerializer


class DemoMarketEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoMarketEvent.objects.all()
    serializer_class = DemoMarketEventSerializer


class DemoAgentEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAgentEvent.objects.select_related("market_event")
    serializer_class = DemoAgentEventSerializer


class DemoFeatureRowViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoFeatureRow.objects.select_related("market_event")
    serializer_class = DemoFeatureRowSerializer


class DemoPredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoPrediction.objects.select_related("feature_row")
    serializer_class = DemoPredictionSerializer


class DemoAlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAlert.objects.select_related("prediction")
    serializer_class = DemoAlertSerializer


class DemoTrainingRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoTrainingRun.objects.all()
    serializer_class = DemoTrainingRunSerializer


class DemoAgentTraceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DemoAgentTrace.objects.select_related("prediction")
    serializer_class = DemoAgentTraceSerializer
