from django.urls import include, path
from django.views.generic import RedirectView
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
router.register(r"training-runs", views.DemoTrainingRunViewSet, basename="training-runs")
router.register(r"demo/agent-traces", views.DemoAgentTraceViewSet)


urlpatterns = [
    # Root and legacy entrypoints now lead straight into the React SPA so
    # users see one consistent UI regardless of where they land.
    path(
        "",
        RedirectView.as_view(url="/dashboard/", permanent=False),
        name="demo_home_root",
    ),
    path(
        "demo/",
        RedirectView.as_view(url="/dashboard/", permanent=False),
        name="demo_home",
    ),
    # Legacy server-rendered simulator pages redirect to their React equivalents.
    path(
        "simulator/",
        RedirectView.as_view(url="/dashboard/live/", permanent=False),
        name="simulator_cockpit",
    ),
    path(
        "simulator/replay/",
        RedirectView.as_view(url="/dashboard/live/", permanent=False),
        name="simulator_replay",
    ),
    path(
        "simulator/agents/",
        RedirectView.as_view(url="/dashboard/agentic/", permanent=False),
        name="simulator_agents",
    ),
    path(
        "simulator/risk/",
        RedirectView.as_view(url="/dashboard/risk/", permanent=False),
        name="simulator_risk",
    ),
    path(
        "simulator/data/",
        RedirectView.as_view(url="/dashboard/memory/", permanent=False),
        name="simulator_data",
    ),
    path(
        "simulator/audit/",
        RedirectView.as_view(url="/dashboard/audit/", permanent=False),
        name="simulator_audit",
    ),
    # Simulator JSON APIs (consumed by the React cockpit).
    path("api/simulator/state/", views.get_simulator_state, name="api_simulator_state"),
    path("api/simulator/control/", views.control_replay, name="api_simulator_control"),
    path("api/risk-head/health/", views.risk_head_health, name="api_risk_head_health"),
    # Canonical React SPA routes — every `/dashboard/...` URL is the same
    # bundle; the React router picks the screen from `window.location`.
    path("dashboard/", views.AgenticReactView.as_view(), name="product_dashboard"),
    path("dashboard/live/", views.AgenticReactView.as_view(), name="product_live"),
    path("dashboard/agentic/", views.AgenticReactView.as_view(), name="product_agentic"),
    path("dashboard/risk/", views.AgenticReactView.as_view(), name="product_risk"),
    path(
        "dashboard/investigations/",
        views.AgenticReactView.as_view(),
        name="product_investigations",
    ),
    path("dashboard/models/", views.AgenticReactView.as_view(), name="product_models"),
    path("dashboard/memory/", views.AgenticReactView.as_view(), name="product_memory"),
    path("dashboard/audit/", views.AgenticReactView.as_view(), name="product_audit"),
    # Legacy "classic" single-page template kept under an explicit URL for
    # anyone who wants to inspect the original demo. Not linked from the nav.
    path("dashboard/agentic/classic/", views.AgenticLoopView.as_view(), name="agentic_loop"),
    # Aliases for the React bundle — some external pages still link these.
    path("dashboard/agentic/v2/", views.AgenticReactView.as_view(), name="agentic_react"),
    path(
        "dashboard/agentic/v2/simulator/",
        views.AgenticReactView.as_view(),
        name="agentic_react_simulator",
    ),
    # Agentic immune-loop APIs (consumed by the React SPA).
    path("api/agentic/run/", views.trigger_immune_loop, name="api_trigger_immune_loop"),
    path("api/agentic/state/", views.agentic_loop_state, name="api_agentic_state"),
    path("api/agentic/llm-status/", views.agentic_llm_status, name="api_agentic_llm_status"),
    path(
        "api/agentic/exchange-training-status/",
        views.exchange_training_status,
        name="api_exchange_training_status",
    ),
    # Legacy `/dashboard/*` template pages → React SPA equivalents.
    path(
        "dashboard/data/",
        RedirectView.as_view(url="/dashboard/memory/", permanent=False),
        name="dashboard_data",
    ),
    path(
        "dashboard/model/",
        RedirectView.as_view(url="/dashboard/models/", permanent=False),
        name="dashboard_model",
    ),
    path(
        "dashboard/alerts/",
        RedirectView.as_view(url="/dashboard/risk/", permanent=False),
        name="dashboard_alerts",
    ),
    path(
        "dashboard/training/",
        RedirectView.as_view(url="/dashboard/models/", permanent=False),
        name="dashboard_training",
    ),
    path(
        "dashboard/agents/",
        RedirectView.as_view(url="/dashboard/agentic/", permanent=False),
        name="dashboard_agents",
    ),
    path(
        "dashboard/benchmark/",
        RedirectView.as_view(url="/dashboard/models/", permanent=False),
        name="dashboard_benchmark",
    ),
    # DRF + JSON endpoints used by the legacy demo (still functional).
    path("api/", include(router.urls)),
    path("api/stats/", views.project_stats, name="project_stats"),
    path("api/summary/", views.dashboard_summary, name="dashboard_summary"),
    path("api/leaderboard/", views.leaderboard, name="leaderboard"),
    path("api/phase/<int:phase_id>/", views.phase_details, name="phase_details"),
    path("api/live/tick/", views.live_demo_tick, name="live_demo_tick"),
    path("api/demo/counts/", views.demo_counts, name="demo_counts"),
]
