"""Agent-behaviour scenarios — Strategy + Registry (Factory) patterns.

Each concrete `AgentScenario` encapsulates how a class of autonomous
trading agents behaves around every kline event. Adding a new scenario
means subclassing `AgentScenario` and decorating with `@register`. No
changes to the engine, the API, or the views are required — the cockpit
picks the new entry up automatically through `ScenarioRegistry.catalog`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Literal


# -- Output value object --------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScenarioOutput:
    """One scenario's contribution to a single replay tick."""

    features: dict[str, float]
    side: Literal["BUY", "SELL"]
    order_price_offset: float
    order_quantity: float
    trade_quantity: float
    trade_price_offset: float


# -- Strategy base --------------------------------------------------------


class AgentScenario(ABC):
    """Strategy: how a simulated agent fleet behaves at one event.

    Subclasses set the four class-level descriptors so the cockpit can
    advertise them without instantiating anything, then implement
    :meth:`step` to produce the per-event output.
    """

    name: ClassVar[str]
    family: ClassVar[Literal["hostile", "benign"]]
    label: ClassVar[str]
    description: ClassVar[str]

    @abstractmethod
    def step(self, idx: int, close_price: float, /) -> ScenarioOutput:
        """Return the scenario's overlay for kline `idx` at `close_price`.

        Both arguments are positional-only so subclasses are free to use
        any parameter names internally (`close`, `mid`, …) without
        breaking call sites.
        """


# -- Registry (Factory pattern) ------------------------------------------


class ScenarioRegistry:
    """Factory + catalogue for `AgentScenario` strategies."""

    _scenarios: ClassVar[dict[str, type[AgentScenario]]] = {}

    @classmethod
    def register(cls, scenario_cls: type[AgentScenario]) -> type[AgentScenario]:
        if not getattr(scenario_cls, "name", None):
            raise ValueError("AgentScenario subclasses must define a `name`.")
        cls._scenarios[scenario_cls.name] = scenario_cls
        return scenario_cls

    @classmethod
    def create(cls, name: str) -> AgentScenario:
        if name not in cls._scenarios:
            raise KeyError(
                f"Unknown scenario {name!r}. Known: {sorted(cls._scenarios)}"
            )
        return cls._scenarios[name]()

    @classmethod
    def names(cls) -> list[str]:
        return sorted(cls._scenarios)

    @classmethod
    def catalog(cls) -> list[dict]:
        """Inspectable list used by the UI and `prepare_simulator` command."""
        return [
            {
                "name": c.name,
                "family": c.family,
                "label": c.label,
                "description": c.description,
            }
            for c in cls._scenarios.values()
        ]


def register(scenario_cls: type[AgentScenario]) -> type[AgentScenario]:
    """Decorator shortcut for `ScenarioRegistry.register`."""
    return ScenarioRegistry.register(scenario_cls)


# -- Concrete strategies --------------------------------------------------
#
# Numerical templates are deliberately the same constants the previous
# (single big if/elif) implementation used so the RuleEngine policy
# outputs remain reproducible across this refactor.


@register
class SpoofingLayeringScenario(AgentScenario):
    name = "spoofing_layering"
    family = "hostile"
    label = "Spoofing / layering"
    description = (
        "Quotes large size away from the touch then cancels before fill; "
        "high cancel-to-fill ratio, biased sell-side."
    )

    def step(self, idx: int, close: float) -> ScenarioOutput:
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 18.0,
                "w5000_order_quantity_sum": 4.2,
                "w5000_order_sell_ratio": 0.95,
                "w1000_agentic_min_interarrival_ms": 4.0,
                "w60000_market_price_drift": 12.0,
                "w1000_order_cancel_rate": 0.65,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 5.0,
                "w5000_order_quantity_max": 5.0,
            },
            side="SELL",
            order_price_offset=5.0,
            order_quantity=5.0,
            trade_quantity=0.0,
            trade_price_offset=0.0,
        )


@register
class QuoteStuffingScenario(AgentScenario):
    name = "quote_stuffing"
    family = "hostile"
    label = "Quote stuffing"
    description = "Bursty order flow with very high cancel rate, tiny fills."

    def step(self, idx: int, close: float) -> ScenarioOutput:
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 45.0,
                "w5000_order_quantity_sum": 0.5,
                "w5000_order_sell_ratio": 0.5,
                "w1000_agentic_min_interarrival_ms": 2.0,
                "w60000_market_price_drift": 1.0,
                "w1000_order_cancel_rate": 0.85,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 5.0,
                "w5000_order_quantity_max": 0.01,
            },
            side="SELL",
            order_price_offset=0.5,
            order_quantity=0.01,
            trade_quantity=0.0,
            trade_price_offset=0.0,
        )


@register
class MomentumIgnitionScenario(AgentScenario):
    name = "momentum_ignition"
    family = "hostile"
    label = "Momentum ignition"
    description = "Large aggressive buys to ignite directional move; large fills."

    def step(self, idx: int, close: float) -> ScenarioOutput:
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 14.0,
                "w5000_order_quantity_sum": 8.5,
                "w5000_order_sell_ratio": 0.05,
                "w1000_agentic_min_interarrival_ms": 15.0,
                "w60000_market_price_drift": 65.0,
                "w1000_order_cancel_rate": 0.12,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 80.0,
                "w5000_order_quantity_max": 10.0,
            },
            side="BUY",
            order_price_offset=12.0,
            order_quantity=10.0,
            trade_quantity=8.0,
            trade_price_offset=10.0,
        )


@register
class TwapExecutionScenario(AgentScenario):
    name = "twap_execution"
    family = "benign"
    label = "TWAP execution"
    description = "Slow, evenly spaced child orders. Benign reference flow."

    def step(self, idx: int, close: float) -> ScenarioOutput:
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 1.0,
                "w5000_order_quantity_sum": 0.5,
                "w5000_order_sell_ratio": 0.1,
                "w1000_agentic_min_interarrival_ms": 1200.0,
                "w60000_market_price_drift": 0.5,
                "w1000_order_cancel_rate": 0.04,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 5.0,
                "w5000_order_quantity_max": 0.05,
            },
            side="BUY",
            order_price_offset=-0.5,
            order_quantity=0.05,
            trade_quantity=0.05,
            trade_price_offset=-0.5,
        )


@register
class InventoryRebalancerScenario(AgentScenario):
    name = "inventory_rebalancer"
    family = "benign"
    label = "Inventory rebalancer"
    description = "Alternating two-sided trades to flatten position; small size."

    def step(self, idx: int, close: float) -> ScenarioOutput:
        side: Literal["BUY", "SELL"] = "BUY" if idx % 2 == 0 else "SELL"
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 2.0,
                "w5000_order_quantity_sum": 1.2,
                "w5000_order_sell_ratio": 0.45,
                "w1000_agentic_min_interarrival_ms": 800.0,
                "w60000_market_price_drift": 1.5,
                "w1000_order_cancel_rate": 0.1,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 5.0,
                "w5000_order_quantity_max": 0.15,
            },
            side=side,
            order_price_offset=0.0,
            order_quantity=0.15,
            trade_quantity=0.15,
            trade_price_offset=0.0,
        )


@register
class PassiveMarketMakerScenario(AgentScenario):
    name = "passive_market_maker"
    family = "benign"
    label = "Passive market maker"
    description = "Quotes both sides at the touch with moderate cancel rate."

    def step(self, idx: int, close: float) -> ScenarioOutput:
        side: Literal["BUY", "SELL"] = "BUY" if idx % 2 == 0 else "SELL"
        return ScenarioOutput(
            features={
                "w1000_agentic_burst_rate_per_second": 3.5,
                "w5000_order_quantity_sum": 2.0,
                "w5000_order_sell_ratio": 0.5,
                "w1000_agentic_min_interarrival_ms": 150.0,
                "w60000_market_price_drift": 0.2,
                "w1000_order_cancel_rate": 0.15,
                "w5000_agentic_self_cross_proxy_count": 0.0,
                "w1000_agentic_unique_agents": 1.0,
                "w5000_order_price_range": 5.0,
                "w5000_order_quantity_max": 0.2,
            },
            side=side,
            order_price_offset=0.0,
            order_quantity=0.2,
            trade_quantity=0.1,
            trade_price_offset=0.0,
        )
