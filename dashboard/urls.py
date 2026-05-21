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
    path("simulator/", views.SimulatorCockpitView.as_view(), name="simulator_cockpit"),
    path("simulator/replay/", views.SimulatorReplayView.as_view(), name="simulator_replay"),
    path("simulator/agents/", views.SimulatorAgentsView.as_view(), name="simulator_agents"),
    path("simulator/risk/", views.SimulatorRiskView.as_view(), name="simulator_risk"),
    path("simulator/data/", views.SimulatorDataView.as_view(), name="simulator_data"),
    path("simulator/audit/", views.SimulatorAuditView.as_view(), name="simulator_audit"),
    path("api/simulator/state/", views.get_simulator_state, name="api_simulator_state"),
    path("api/simulator/control/", views.control_replay, name="api_simulator_control"),
    path("api/risk-head/health/", views.risk_head_health, name="api_risk_head_health"),
    path("dashboard/agentic/", views.AgenticLoopView.as_view(), name="agentic_loop"),
    path("dashboard/agentic/v2/", views.AgenticReactView.as_view(), name="agentic_react"),
    path(
        "dashboard/agentic/v2/simulator/",
        views.AgenticReactView.as_view(),
        name="agentic_react_simulator",
    ),
    path("api/agentic/run/", views.trigger_immune_loop, name="api_trigger_immune_loop"),
    path("api/agentic/state/", views.agentic_loop_state, name="api_agentic_state"),
    path("api/agentic/llm-status/", views.agentic_llm_status, name="api_agentic_llm_status"),
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
