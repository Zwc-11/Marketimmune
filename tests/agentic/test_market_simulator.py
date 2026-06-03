"""Tests for MarketSimulatorAgent.

These tests create minimal in-memory parquet files so ReplayBuilder
can run without the full Binance lake.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.agentic.market_simulator import MarketSimulatorAgent
from marketimmune.agentic.redteam import ScenarioProposal


# ---------------------------------------------------------------------------
# Helpers to write minimal parquet lake data
# ---------------------------------------------------------------------------


def _write_kline_parquet(lake_root: Path, symbol: str = "BTCUSDT") -> None:
    out_dir = lake_root / "klines" / symbol / "1m"
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "event_id": ["ev1", "ev2", "ev3"],
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
                "2026-01-01T00:02:00Z",
            ],
            "open_price": [100.0, 101.0, 102.0],
            "high_price": [105.0, 106.0, 107.0],
            "low_price": [99.0, 100.0, 101.0],
            "close_price": [101.0, 102.0, 103.0],
            "volume": [1000.0, 2000.0, 3000.0],
            "trade_count": [10, 20, 30],
        }
    )
    pq.write_table(table, out_dir / f"{symbol}-klines-1m-2026-01-01.parquet")


def _write_depth_parquet(lake_root: Path, symbol: str = "BTCUSDT") -> None:
    out_dir = lake_root / "bookDepth" / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": ["2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z"],
            "percentage": [1.0, -1.0],
            "depth": [5.0, 4.0],
            "notional": [500.0, 400.0],
        }
    )
    pq.write_table(table, out_dir / f"{symbol}-bookDepth-2026-01-01.parquet")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_market_simulator_requires_proposal_or_scenario_name() -> None:
    agent = MarketSimulatorAgent()
    run = agent.run(goal="simulate")
    assert run.success is False
    assert "ValueError" in (run.error or "")


def test_market_simulator_with_scenario_name(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    _write_depth_parquet(tmp_path)
    agent = MarketSimulatorAgent(lake_root=tmp_path, model_path=None)
    run = agent.run(
        goal="simulate registered scenario",
        scenario_name="spoofing_layering",
        limit=3,
    )
    assert run.success is True
    plan = run.linked_artifacts["plan"]
    assert plan is not None
    assert len(plan.ticks) > 0
    assert run.output["tick_count"] > 0


def test_market_simulator_with_scenario_proposal(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    _write_depth_parquet(tmp_path)

    from marketimmune.agentic.redteam import RedTeamScenarioAgent
    rt_agent = RedTeamScenarioAgent(seed=42)
    rt_run = rt_agent.run(goal="propose")
    proposal = ScenarioProposal(
        **{k: v for k, v in rt_run.output.items() if k in ScenarioProposal.__annotations__}
    )

    agent = MarketSimulatorAgent(lake_root=tmp_path, model_path=None)
    run = agent.run(goal="simulate proposal", proposal=proposal, limit=3)
    assert run.success is True
    assert run.linked_artifacts["plan"] is not None


def test_market_simulator_with_dict_proposal(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)

    from marketimmune.agentic.redteam import RedTeamScenarioAgent
    rt_agent = RedTeamScenarioAgent(seed=42)
    rt_run = rt_agent.run(goal="propose")

    agent = MarketSimulatorAgent(lake_root=tmp_path, model_path=None)
    # Pass the proposal as a plain dict (exercises the dict conversion branch)
    run = agent.run(goal="simulate from dict", proposal=rt_run.output, limit=3)
    assert run.success is True


def test_market_simulator_no_kline_data_fails(tmp_path: Path) -> None:
    """An empty lake directory should raise FileNotFoundError inside the agent."""
    agent = MarketSimulatorAgent(lake_root=tmp_path, model_path=None)
    run = agent.run(goal="simulate", scenario_name="spoofing_layering", limit=3)
    assert run.success is False
