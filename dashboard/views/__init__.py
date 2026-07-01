"""Dashboard view package.

Re-exports all view classes and function views so existing
``from dashboard import views`` callers (e.g. ``dashboard/urls.py``)
continue to work unchanged after the split.
"""
from __future__ import annotations

from .agentic import (
    AgenticLoopView,
    AgenticReactView,
    agentic_llm_status,
    agentic_loop_state,
    exchange_training_status,
    trigger_immune_loop,
)
from .api_demo import (
    dashboard_summary,
    demo_counts,
    leaderboard,
    live_demo_tick,
    phase_details,
    project_stats,
)
from .api_hyperliquid import hyperliquid_candles, hyperliquid_live_snapshot
from .api_hyperliquid_backfill import hyperliquid_backfill_jobs
from .api_markout_model import markout_fill_decisions, markout_model_health
from .api_metrics import (
    BenchmarkMetricsViewSet,
    DemoAgentEventViewSet,
    DemoAgentTraceViewSet,
    DemoAlertViewSet,
    DemoFeatureRowViewSet,
    DemoMarketEventViewSet,
    DemoPredictionViewSet,
    DemoTrainingRunViewSet,
    ModelMetricViewSet,
    TaskMetricViewSet,
)
from .legacy_dashboard import (
    AgentsDashboardView,
    AlertsDashboardView,
    BenchmarkDashboardView,
    DashboardView,
    DataDashboardView,
    DemoHomeView,
    LiveDashboardView,
    ModelDashboardView,
    TrainingDashboardView,
)
from .simulator import (
    SimulatorAgentsView,
    SimulatorAuditView,
    SimulatorCockpitView,
    SimulatorDataView,
    SimulatorReplayView,
    SimulatorRiskView,
    control_replay,
    get_simulator_state,
    risk_head_health,
)

__all__ = [
    # Legacy server-rendered dashboard pages.
    "AgentsDashboardView",
    "AlertsDashboardView",
    "BenchmarkDashboardView",
    "DashboardView",
    "DataDashboardView",
    "DemoHomeView",
    "LiveDashboardView",
    "ModelDashboardView",
    "TrainingDashboardView",
    # ViewSets exposed on the DRF router.
    "BenchmarkMetricsViewSet",
    "DemoAgentEventViewSet",
    "DemoAgentTraceViewSet",
    "DemoAlertViewSet",
    "DemoFeatureRowViewSet",
    "DemoMarketEventViewSet",
    "DemoPredictionViewSet",
    "DemoTrainingRunViewSet",
    "ModelMetricViewSet",
    "TaskMetricViewSet",
    # Function-based API views.
    "dashboard_summary",
    "demo_counts",
    "leaderboard",
    "live_demo_tick",
    "phase_details",
    "project_stats",
    "hyperliquid_candles",
    "hyperliquid_live_snapshot",
    "hyperliquid_backfill_jobs",
    "markout_model_health",
    "markout_fill_decisions",
    # Simulator views.
    "SimulatorAgentsView",
    "SimulatorAuditView",
    "SimulatorCockpitView",
    "SimulatorDataView",
    "SimulatorReplayView",
    "SimulatorRiskView",
    "control_replay",
    "get_simulator_state",
    "risk_head_health",
    # Agentic views.
    "AgenticLoopView",
    "AgenticReactView",
    "agentic_llm_status",
    "agentic_loop_state",
    "exchange_training_status",
    "trigger_immune_loop",
]
