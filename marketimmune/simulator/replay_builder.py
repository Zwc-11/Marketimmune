"""Replay orchestration service.

The Django management command and any future entry points should never
talk to klines, depth, scenarios, or the RuleEngine directly. They go
through `ReplayBuilder.build(...)` which returns a deterministic
`ReplayPlan` — a list of `ReplayTick`s. Persisting that plan is the
responsibility of the caller (the Django app maps it onto the ORM,
while a CLI tool could ship it to disk or a notebook).

This separation means we can:
  - run the builder in a test without a DB,
  - swap in a different RuleEngine without touching the cockpit,
  - replace parquet sources with a Kafka stream by just swapping the
    repositories passed into the builder.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from marketimmune.models.risk_head import RiskScorer
from marketimmune.policy.rules import PolicyAction, RuleEngine
from marketimmune.simulator.config import ReplayConfig
from marketimmune.simulator.data_loader import (
    DepthRepository,
    DepthSnapshot,
    KlineRecord,
    KlineRepository,
)
from marketimmune.simulator.pricing import DerivedQuote, derive_quote_from_depth
from marketimmune.simulator.scenarios import AgentScenario, ScenarioRegistry

# -- Output value objects ------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplayTick:
    """All information produced for one replay step.

    The Django app persists each tick across several ORM rows
    (`ReplayEvent`, `SimulatedAgentOrder`, ...), but the engine itself
    only needs to know about this single value object.
    """

    idx: int
    timestamp: datetime
    kline: KlineRecord
    depth: DepthSnapshot | None
    quote: DerivedQuote
    agent_side: str
    agent_order_price: float
    agent_order_quantity: float
    agent_trade_price: float
    agent_trade_quantity: float
    features: dict[str, float]
    risk_score: float
    risk_label: str
    risk_explanation: str
    risk_model_name: str
    matched_rules: tuple[str, ...]
    policy_decision: str
    recommended_control: str
    observation: str


@dataclass(frozen=True, slots=True)
class ReplayPlan:
    """A deterministic replay produced by `ReplayBuilder.build`."""

    run_id: str
    config: ReplayConfig
    ticks: tuple[ReplayTick, ...]
    depth_snapshot_count: int


# -- Service -------------------------------------------------------------


# RuleEngine → numeric risk score. Kept as a module constant so the
# mapping is documented in exactly one place.
_RISK_SCORE_BY_ACTION: dict[PolicyAction, float] = {
    PolicyAction.ALLOW: 0.15,
    PolicyAction.ALERT: 0.58,
    PolicyAction.BLOCK: 0.88,
}


@dataclass
class ReplayBuilder:
    """Service: build a `ReplayPlan` from market data + an agent scenario.

    Dependencies are injected so tests can substitute repositories and
    the policy engine for fakes. When a `risk_scorer` is provided we use
    its calibrated probability as the displayed risk score and fall
    back to the rule engine only for the discrete policy decision.
    """

    kline_repo: KlineRepository
    depth_repo: DepthRepository
    rule_engine: RuleEngine = field(default_factory=RuleEngine)
    risk_score_by_action: dict[PolicyAction, float] = field(
        default_factory=lambda: dict(_RISK_SCORE_BY_ACTION)
    )
    risk_scorer: RiskScorer | None = None

    # ---- public ----------------------------------------------------

    @classmethod
    def from_lake(
        cls,
        lake_root: Path | str,
        *,
        model_path: Path | str | None = None,
    ) -> ReplayBuilder:
        """Wire default parquet repos and optionally load a trained ML head.

        If `model_path` is provided and exists on disk, the ML risk head
        replaces the rule engine as the displayed risk score. The rule
        engine is still used to produce the discrete `policy_decision`
        because the action thresholds it encodes are the system of
        record for "block" vs "alert".
        """
        root = Path(lake_root)
        scorer: RiskScorer | None = None
        if model_path is not None:
            path = Path(model_path)
            if path.exists():
                scorer = RiskScorer.load(path)
        return cls(
            kline_repo=KlineRepository(root),
            depth_repo=DepthRepository(root),
            risk_scorer=scorer,
        )

    def build(
        self,
        config: ReplayConfig,
        *,
        scenario: AgentScenario | None = None,
    ) -> ReplayPlan:
        """Build a `ReplayPlan` for the given config.

        Pass `scenario` directly when you have a one-off (e.g. red-team
        proposal) that you don't want to register globally; otherwise
        the builder resolves `config.scenario_name` through the
        registry as usual.
        """
        date = config.replay_date or self._pick_aligned_date(config.symbol)
        klines = self.kline_repo.load(config.symbol, date, config.limit)
        if not klines:
            raise FileNotFoundError(
                f"No kline parquet available for {config.symbol} "
                f"(date={date}). Check the data lake."
            )
        replay_date = klines[0].timestamp.date().isoformat()
        depths = self.depth_repo.load(config.symbol, replay_date)
        if scenario is None:
            scenario = ScenarioRegistry.create(config.scenario_name)

        run_id = f"run_{config.scenario_name}_{uuid.uuid4().hex[:10]}"
        ticks = tuple(self._build_ticks(klines, depths, scenario))
        return ReplayPlan(
            run_id=run_id,
            config=config,
            ticks=ticks,
            depth_snapshot_count=len(depths),
        )

    # ---- internals -------------------------------------------------

    def _pick_aligned_date(self, symbol: str) -> str | None:
        """Pick the latest date where both kline AND depth parquets exist.

        Falls back to the latest kline date (depth ladder will be empty in
        that case but the cockpit still renders the candles honestly).
        """
        kline_dir = self.kline_repo.directory_for(symbol)
        depth_dir = self.depth_repo.directory_for(symbol)
        if not kline_dir.exists():
            return None
        fallback: str | None = None
        for kf in sorted(kline_dir.glob("*.parquet"), reverse=True):
            # Filename: SYMBOL-klines-1m-YYYY-MM-DD.parquet
            parts = kf.stem.split("-")
            if len(parts) < 6:
                continue
            date = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
            if fallback is None:
                fallback = date
            if (depth_dir / f"{symbol}-bookDepth-{date}.parquet").exists():
                return date
        return fallback

    def _build_ticks(
        self,
        klines: list[KlineRecord],
        depths: list[DepthSnapshot],
        scenario: AgentScenario,
    ) -> Iterator[ReplayTick]:
        for idx, kline in enumerate(klines):
            depth_snap = self.depth_repo.nearest(depths, kline.timestamp)
            quote = derive_quote_from_depth(kline.close, depth_snap)
            so = scenario.step(idx, kline.close)
            decision = self.rule_engine.decide(so.features)
            # ML head, when present, becomes the displayed score; the
            # rule engine still owns the discrete policy decision.
            if self.risk_scorer is not None:
                prediction = self.risk_scorer.predict(so.features)
                risk_score = prediction.score
                model_name = prediction.model_name
                top = ", ".join(f"{k}={v:+.2f}" for k, v in prediction.top_features)
                if decision.matched_rules:
                    explanation = (
                        f"ML score {risk_score:.2f} with top features [{top}]; "
                        f"rule overlay matched: {', '.join(decision.matched_rules)}."
                    )
                else:
                    explanation = (
                        f"ML score {risk_score:.2f} with top features [{top}]."
                    )
            else:
                risk_score = self.risk_score_by_action.get(decision.action, 0.10)
                model_name = "RuleEngine"
                explanation = (
                    f"Matched anomalous rules: {', '.join(decision.matched_rules)}."
                    if decision.matched_rules
                    else "Normal orderly background flow."
                )
            risk_label = decision.action.value.upper()
            recommended = _recommended_control_for(decision.action)
            observation = _observation_for(so.features)
            yield ReplayTick(
                idx=idx,
                timestamp=kline.timestamp,
                kline=kline,
                depth=depth_snap,
                quote=quote,
                agent_side=so.side,
                agent_order_price=kline.close + so.order_price_offset,
                agent_order_quantity=so.order_quantity,
                agent_trade_price=(
                    kline.close + so.trade_price_offset if so.trade_quantity > 0 else 0.0
                ),
                agent_trade_quantity=so.trade_quantity,
                features=so.features,
                risk_score=risk_score,
                risk_label=risk_label,
                risk_explanation=explanation,
                risk_model_name=model_name,
                matched_rules=tuple(decision.matched_rules),
                policy_decision=decision.action.value,
                recommended_control=recommended,
                observation=observation,
            )


# -- Pure helpers --------------------------------------------------------


def _recommended_control_for(action: PolicyAction) -> str:
    if action == PolicyAction.BLOCK:
        return "Halt connection for agent-id. Cancel all matching floating orders."
    if action == PolicyAction.ALERT:
        return "Raise alert severity and route to active compliance queue."
    return "None required"


def _observation_for(features: dict[str, float]) -> str:
    return (
        f"Observed interarrival {features['w1000_agentic_min_interarrival_ms']:.1f}ms, "
        f"burst {features['w1000_agentic_burst_rate_per_second']:.1f}/s, cancel-rate "
        f"{features['w1000_order_cancel_rate']:.2f}, sell-ratio "
        f"{features['w5000_order_sell_ratio']:.2f}."
    )
