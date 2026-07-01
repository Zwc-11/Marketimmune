"""Django ORM models for the dashboard app — split by concern.

The definitions live in three focused modules; this file re-exports them so
``from dashboard.models import X``, the migrations, and the admin keep working
unchanged. Django discovers the models through these imports and registers them
under the ``dashboard`` app, so the split produces **no new migration**.

* ``models_audit``     — the agentic immune-loop audit log (ImmuneLoopRun, …):
                          the append-only record of every agent run/decision.
* ``models_simulator`` — the replay/cockpit session tables (ReplaySession, …).
* ``models_demo``      — the legacy demo-dashboard tables (BenchmarkMetrics,
                          Demo* visual-demo rows).

See AUDIT_AND_PLAN.md §3 for why these were separated.
"""

from dashboard.models_audit import (
    AgentDecisionTraceRecord,
    AgentRunRecord,
    AgentToolCallRecord,
    HyperliquidBackfillJob,
    ImmuneLoopRun,
    ImmuneMemoryEntry,
    InvestigationCaseRecord,
    ModelPromotionDecision,
    PolicyDecisionRecord,
    ScenarioProposalRecord,
    ScoredFillDecision,
    ScoredFillDecisionLink,
    ScoredFillRefreshRun,
)
from dashboard.models_demo import (
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
from dashboard.models_simulator import (
    DecisionAuditTrace,
    FeatureSnapshot,
    ModelPrediction,
    ReplayCursor,
    ReplayEvent,
    ReplaySession,
    RiskAlert,
    SimulatedAgentOrder,
    SimulatedAgentTrade,
)

__all__ = [
    # agentic audit log (models_audit)
    "AgentDecisionTraceRecord",
    "AgentRunRecord",
    "AgentToolCallRecord",
    "HyperliquidBackfillJob",
    "ImmuneLoopRun",
    "ImmuneMemoryEntry",
    "InvestigationCaseRecord",
    "ModelPromotionDecision",
    "PolicyDecisionRecord",
    "ScenarioProposalRecord",
    "ScoredFillDecision",
    "ScoredFillDecisionLink",
    "ScoredFillRefreshRun",
    # replay / cockpit (models_simulator)
    "DecisionAuditTrace",
    "FeatureSnapshot",
    "ModelPrediction",
    "ReplayCursor",
    "ReplayEvent",
    "ReplaySession",
    "RiskAlert",
    "SimulatedAgentOrder",
    "SimulatedAgentTrade",
    # legacy demo dashboard (models_demo)
    "BenchmarkMetrics",
    "DemoAgentEvent",
    "DemoAgentTrace",
    "DemoAlert",
    "DemoFeatureRow",
    "DemoMarketEvent",
    "DemoPrediction",
    "DemoTrainingRun",
    "ModelMetric",
    "ProjectStats",
    "TaskMetric",
]
