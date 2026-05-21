"""Strategy / Registry contract tests for the agent scenarios."""

from __future__ import annotations

import pytest

from marketimmune.simulator import AgentScenario, ScenarioOutput, ScenarioRegistry

EXPECTED_NAMES = {
    "spoofing_layering",
    "quote_stuffing",
    "momentum_ignition",
    "twap_execution",
    "inventory_rebalancer",
    "passive_market_maker",
}


def test_registry_contains_all_named_scenarios() -> None:
    assert set(ScenarioRegistry.names()) == EXPECTED_NAMES


def test_registry_catalog_is_complete_and_typed() -> None:
    catalog = ScenarioRegistry.catalog()
    assert {entry["name"] for entry in catalog} == EXPECTED_NAMES
    for entry in catalog:
        assert entry["family"] in {"hostile", "benign"}
        assert entry["label"]
        assert entry["description"]


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_every_scenario_step_returns_well_formed_output(name: str) -> None:
    scenario = ScenarioRegistry.create(name)
    out = scenario.step(0, 100.0)
    assert isinstance(out, ScenarioOutput)
    assert out.side in {"BUY", "SELL"}
    assert out.order_quantity > 0
    # All ten engineered features must be present.
    assert set(out.features) >= {
        "w1000_agentic_burst_rate_per_second",
        "w5000_order_quantity_sum",
        "w5000_order_sell_ratio",
        "w1000_agentic_min_interarrival_ms",
        "w60000_market_price_drift",
        "w1000_order_cancel_rate",
        "w5000_agentic_self_cross_proxy_count",
        "w1000_agentic_unique_agents",
        "w5000_order_price_range",
        "w5000_order_quantity_max",
    }


def test_unknown_scenario_raises() -> None:
    with pytest.raises(KeyError):
        ScenarioRegistry.create("does_not_exist")


def test_inventory_rebalancer_alternates_side() -> None:
    scenario = ScenarioRegistry.create("inventory_rebalancer")
    sides = [scenario.step(i, 100.0).side for i in range(4)]
    assert sides == ["BUY", "SELL", "BUY", "SELL"]


def test_agent_scenario_abc_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        AgentScenario()  # type: ignore[abstract]
