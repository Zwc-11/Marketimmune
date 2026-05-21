"""MarketSimulatorAgent — runs one scenario through the replay engine.

This agent owns the boundary between the agentic loop and the
existing :mod:`marketimmune.simulator`. It takes a
:class:`ScenarioProposal` (or a registered scenario name), invokes
:class:`ReplayBuilder`, and returns a digest of the resulting market /
overlay state — but importantly, the *actual* parquet-backed tick
stream is also exposed as ``ticks`` so downstream agents can iterate.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.agentic.redteam import ScenarioProposal
from marketimmune.simulator import ReplayBuilder, ReplayConfig, ReplayPlan
from marketimmune.simulator.scenarios import AgentScenario, ScenarioOutput


class _ProposalScenarioAdapter(AgentScenario):
    """Plug a one-off `ScenarioProposal` into the existing replay builder.

    Instantiated *with* a proposal and passed straight to
    :meth:`ReplayBuilder.build(scenario=...)`. Never registered in the
    global `ScenarioRegistry`, so this stays free of side-effects.
    """

    # Class-level descriptors are required by the AgentScenario ABC
    # but are not used at run time when the instance is passed
    # directly into ReplayBuilder.build().
    name = "redteam_proposal"
    family = "hostile"
    label = "Red-team proposal"
    description = "Ephemeral adapter used inside MarketSimulatorAgent."

    def __init__(self, proposal: ScenarioProposal):
        self._proposal = proposal

    def step(self, idx, close, /):  # type: ignore[override]
        return ScenarioOutput(
            features=dict(self._proposal.features),
            side=self._proposal.side,  # type: ignore[arg-type]
            order_price_offset=self._proposal.order_price_offset,
            order_quantity=self._proposal.order_quantity,
            trade_quantity=self._proposal.trade_quantity,
            trade_price_offset=self._proposal.trade_price_offset,
        )


class MarketSimulatorAgent(Agent):
    """Runs a scenario through the existing parquet-backed replay."""

    name = "MarketSimulatorAgent"
    description = "Wraps ReplayBuilder so the loop can simulate a scenario."

    DEFAULT_LAKE = "data/lake/binance_usdm"
    DEFAULT_MODEL = "data/models/risk_head.joblib"

    def __init__(
        self,
        *,
        lake_root: str | Path = DEFAULT_LAKE,
        model_path: str | Path | None = DEFAULT_MODEL,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._lake_root = Path(lake_root)
        self._model_path = Path(model_path) if model_path else None

    def _execute(
        self,
        *,
        goal: str,
        proposal: dict | ScenarioProposal | None = None,
        scenario_name: str | None = None,
        limit: int = 60,
        **_: Any,
    ) -> Mapping[str, Any]:
        if proposal is None and scenario_name is None:
            raise ValueError("Need either a `proposal` or a `scenario_name`.")

        if proposal is not None:
            if isinstance(proposal, dict):
                proposal = ScenarioProposal(**{
                    k: v for k, v in proposal.items()
                    if k in ScenarioProposal.__annotations__
                })
            adapter = _ProposalScenarioAdapter(proposal)
            scenario_label = proposal.name
            self.record_trace(
                goal=goal,
                observation=f"Using red-team proposal {proposal.name!r}.",
                decision="adapter scenario",
                confidence=0.65,
            )
            plan = self._build(
                ReplayConfig(scenario_name=proposal.name, limit=limit),
                scenario=adapter,
            )
        else:
            scenario_label = scenario_name
            plan = self._build(ReplayConfig(scenario_name=scenario_name, limit=limit))

        # Summarise the plan into something compact for downstream agents.
        hostile_alerts = sum(1 for t in plan.ticks if t.policy_decision != "allow")
        peak_score = max((t.risk_score for t in plan.ticks), default=0.0)
        self.record_trace(
            goal=goal,
            observation=(
                f"Replay built: {len(plan.ticks)} ticks, "
                f"peak risk {peak_score:.2f}, {hostile_alerts} alert-or-block events."
            ),
            decision="emit ReplayPlan summary",
            confidence=0.85,
            evidence={
                "scenario": scenario_label,
                "tick_count": len(plan.ticks),
                "peak_risk_score": peak_score,
                "hostile_alerts": hostile_alerts,
            },
        )
        return {
            "output": {
                "run_id": plan.run_id,
                "scenario": scenario_label,
                "tick_count": len(plan.ticks),
                "peak_risk_score": peak_score,
                "hostile_alerts": hostile_alerts,
                "depth_snapshots": plan.depth_snapshot_count,
                # Pass the plan itself through `artifacts` so the
                # orchestrator can pipe ticks into the next agent.
            },
            "artifacts": {"plan": plan},  # type: ignore[dict-item]
        }

    def _build(
        self,
        config: ReplayConfig,
        *,
        scenario: AgentScenario | None = None,
    ) -> ReplayPlan:
        builder = ReplayBuilder.from_lake(
            self._lake_root, model_path=self._model_path,
        )
        self.record_tool_call(
            "ReplayBuilder.build",
            arguments={"scenario": config.scenario_name, "limit": config.limit},
            result_summary=(
                f"ML head loaded: {builder.risk_scorer is not None}"
            ),
        )
        return builder.build(config, scenario=scenario)
