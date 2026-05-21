"""Simulator domain layer.

This package contains the pure-Python core of the exchange replay
simulator. It has no dependency on Django; the Django app calls into it
through the service entry points exposed here. Keeping the engine
framework-free means we can later run it inside a Jupyter notebook, a
backtest CLI, or a FastAPI service without rewriting it.

Public surface (the only names other modules should import):

    from marketimmune.simulator import (
        ReplayConfig,         # value object describing one replay run
        ReplayBuilder,        # service that builds a replay end-to-end
        ScenarioRegistry,     # factory for agent-behaviour strategies
        KlineRepository,      # repository for OHLC parquet files
        DepthRepository,      # repository for bookDepth parquet files
        DerivedQuote,         # bid/ask/spread derived from aggregated depth
    )
"""

from marketimmune.simulator.config import ReplayConfig
from marketimmune.simulator.data_loader import (
    DepthRepository,
    DepthSnapshot,
    KlineRepository,
    KlineRecord,
)
from marketimmune.simulator.pricing import DerivedQuote, derive_quote_from_depth
from marketimmune.simulator.replay_builder import ReplayBuilder, ReplayPlan, ReplayTick
from marketimmune.simulator.scenarios import (
    AgentScenario,
    ScenarioOutput,
    ScenarioRegistry,
)

__all__ = [
    "AgentScenario",
    "DepthRepository",
    "DepthSnapshot",
    "DerivedQuote",
    "KlineRecord",
    "KlineRepository",
    "ReplayBuilder",
    "ReplayConfig",
    "ReplayPlan",
    "ReplayTick",
    "ScenarioOutput",
    "ScenarioRegistry",
    "derive_quote_from_depth",
]
