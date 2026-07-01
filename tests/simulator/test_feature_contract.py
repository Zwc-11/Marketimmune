"""Contract test: live-product scenarios and the risk head agree on features.

Layer A (`simulator/scenarios.py` `ScenarioRegistry`) hand-writes a feature dict per
scenario; the risk head (`models/risk_head.py` `FEATURE_ORDER`) and the serving
feature store consume those exact keys. This test locks the contract so that adding or
removing a feature in one place without the other fails loudly — the interim guard for
the train/serve transform skew described in AUDIT_AND_PLAN.md §2.1 / §2.3.
"""

from marketimmune.models.risk_head import FEATURE_ORDER
from marketimmune.simulator.scenarios import ScenarioRegistry


def test_every_scenario_emits_exactly_feature_order() -> None:
    expected = set(FEATURE_ORDER)
    for meta in ScenarioRegistry.catalog():
        scenario = ScenarioRegistry.create(meta["name"])
        keys = set(scenario.step(0, 100.0).features)
        assert keys == expected, (
            f"scenario {meta['name']!r} emits {sorted(keys)}; expected {sorted(expected)}"
        )


def test_feature_order_has_no_duplicates() -> None:
    assert len(FEATURE_ORDER) == len(set(FEATURE_ORDER))
