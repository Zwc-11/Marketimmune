from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

from marketimmune.agents.base import Agent
from marketimmune.agents.benign import InventoryRebalancer, PassiveMarketMaker, TwapExecutor
from marketimmune.agents.unsafe import (
    LatencyEdgeExploiter,
    MomentumIgniter,
    QuoteStuffer,
    RunawayInventory,
    SpoofingLayerer,
    StopRunSweeper,
    SynchronizedBurst,
    SyntheticWashTrader,
    VolatilityFeedback,
)
from marketimmune.scenarios.config import ScenarioConfig
from marketimmune.scenarios.labels import labels_for_events
from marketimmune.schemas.events import AgentOrderEvent
from marketimmune.schemas.labels import EventLabel, SessionLabel

AGENT_REGISTRY: dict[str, type[Agent]] = {
    PassiveMarketMaker.family: PassiveMarketMaker,
    TwapExecutor.family: TwapExecutor,
    InventoryRebalancer.family: InventoryRebalancer,
    SpoofingLayerer.family: SpoofingLayerer,
    QuoteStuffer.family: QuoteStuffer,
    MomentumIgniter.family: MomentumIgniter,
    SyntheticWashTrader.family: SyntheticWashTrader,
    SynchronizedBurst.family: SynchronizedBurst,
    LatencyEdgeExploiter.family: LatencyEdgeExploiter,
    StopRunSweeper.family: StopRunSweeper,
    RunawayInventory.family: RunawayInventory,
    VolatilityFeedback.family: VolatilityFeedback,
}


def payload_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


class GeneratedScenario:
    def __init__(
        self,
        *,
        config: ScenarioConfig,
        events: list[AgentOrderEvent],
        event_labels: list[EventLabel],
        session_label: SessionLabel,
    ) -> None:
        self.config = config
        self.events = events
        self.event_labels = event_labels
        self.session_label = session_label

    def manifest(self) -> dict[str, object]:
        event_payload = [event.model_dump(mode="json") for event in self.events]
        label_payload = [label.model_dump(mode="json") for label in self.event_labels]
        return {
            "scenario_id": self.config.scenario_id,
            "family": self.config.family,
            "seed": self.config.seed,
            "start": self.config.start.isoformat(),
            "mid_price": self.config.mid_price,
            "event_count": len(self.events),
            "unsafe": self.config.unsafe,
            "event_hash": payload_hash(event_payload),
            "label_hash": payload_hash(label_payload),
        }

    def write(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{self.config.scenario_id}_events.json").write_text(
            json.dumps([event.model_dump(mode="json") for event in self.events], indent=2),
            encoding="utf-8",
        )
        (root / f"{self.config.scenario_id}_labels.json").write_text(
            json.dumps([label.model_dump(mode="json") for label in self.event_labels], indent=2),
            encoding="utf-8",
        )
        (root / f"{self.config.scenario_id}_manifest.json").write_text(
            json.dumps(self.manifest(), indent=2),
            encoding="utf-8",
        )


def generate_scenario(config: ScenarioConfig) -> GeneratedScenario:
    agent_cls = AGENT_REGISTRY[config.family]
    agent = agent_cls(agent_id=f"agent-{config.family}", seed=config.seed)
    events = agent.generate(
        scenario_id=config.scenario_id,
        start=config.start,
        mid_price=config.mid_price,
        count=config.event_count,
    )
    events = apply_safety_variant(events, unsafe=config.unsafe, mid_price=config.mid_price)
    event_labels, session_label = labels_for_events(
        scenario_id=config.scenario_id,
        session_id=f"{config.scenario_id}-session",
        family=config.family,
        unsafe=config.unsafe,
        events=events,
    )
    return GeneratedScenario(
        config=config,
        events=events,
        event_labels=event_labels,
        session_label=session_label,
    )


def apply_safety_variant(
    events: list[AgentOrderEvent],
    *,
    unsafe: bool,
    mid_price: float,
) -> list[AgentOrderEvent]:
    transformed: list[AgentOrderEvent] = []
    preserve_price_level = len({event.price for event in events}) == 1
    for index, event in enumerate(events):
        if unsafe:
            drift = 1 + (index * 0.00008)
            timestamp = events[0].timestamp + timedelta(milliseconds=index * 8)
            price = event.price if preserve_price_level else event.price * drift
            quantity = max(event.quantity, 0.08)
        else:
            timestamp = events[0].timestamp + timedelta(milliseconds=index * 250)
            side_offset = -0.00005 if index % 2 == 0 else 0.00005
            price = mid_price * (1 + side_offset)
            quantity = min(event.quantity, 0.01)
        transformed.append(
            AgentOrderEvent(
                symbol=event.symbol,
                timestamp=timestamp,
                sequence=event.sequence,
                scenario_id=event.scenario_id,
                agent_id=event.agent_id,
                order_id=event.order_id,
                action=event.action,
                side=event.side,
                price=price,
                quantity=quantity,
                remaining_quantity=min(event.remaining_quantity, quantity),
            )
        )
    return transformed
