from django.urls import include, path
from rest_framework.routers import DefaultRouter

from dashboard import views

router = DefaultRouter()
router.register(r"task-metrics", views.TaskMetricViewSet)
router.register(r"model-metrics", views.ModelMetricViewSet)
router.register(r"benchmark-metrics", views.BenchmarkMetricsViewSet)
router.register(r"demo/market-events", views.DemoMarketEventViewSet)
router.register(r"demo/agent-events", views.DemoAgentEventViewSet)
router.register(r"demo/features", views.DemoFeatureRowViewSet)
router.register(r"demo/predictions", views.DemoPredictionViewSet)
router.register(r"demo/alerts", views.DemoAlertViewSet)
router.register(r"demo/training-runs", views.DemoTrainingRunViewSet)
router.register(r"demo/agent-traces", views.DemoAgentTraceViewSet)

urlpatterns = [
    path("", views.DemoHomeView.as_view(), name="demo_home_root"),
    path("demo/", views.DemoHomeView.as_view(), name="demo_home"),
    path("dashboard/live/", views.LiveDashboardView.as_view(), name="dashboard_live"),
    path("dashboard/data/", views.DataDashboardView.as_view(), name="dashboard_data"),
    path("dashboard/model/", views.ModelDashboardView.as_view(), name="dashboard_model"),
    path("dashboard/alerts/", views.AlertsDashboardView.as_view(), name="dashboard_alerts"),
    path("dashboard/training/", views.TrainingDashboardView.as_view(), name="dashboard_training"),
    path("dashboard/agents/", views.AgentsDashboardView.as_view(), name="dashboard_agents"),
    path(
        "dashboard/benchmark/", views.BenchmarkDashboardView.as_view(), name="dashboard_benchmark"
    ),
    path("api/", include(router.urls)),
    path("api/stats/", views.project_stats, name="project_stats"),
    path("api/summary/", views.dashboard_summary, name="dashboard_summary"),
    path("api/leaderboard/", views.leaderboard, name="leaderboard"),
    path("api/phase/<int:phase_id>/", views.phase_details, name="phase_details"),
    path("api/live/tick/", views.live_demo_tick, name="live_demo_tick"),
    path("api/demo/counts/", views.demo_counts, name="demo_counts"),
]
