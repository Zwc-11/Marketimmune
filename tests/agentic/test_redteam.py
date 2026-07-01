"""Tests for RedTeamScenarioAgent."""

from __future__ import annotations

import pytest

from marketimmune.agentic.redteam import RedTeamScenarioAgent, ScenarioProposal
from marketimmune.simulator.scenarios import ScenarioRegistry

# ---------------------------------------------------------------------------
# Basic deterministic proposal
# ---------------------------------------------------------------------------


def test_redteam_produces_proposal() -> None:
    agent = RedTeamScenarioAgent(seed=42)
    run = agent.run(goal="generate adversarial scenario", difficulty="medium")
    assert run.success is True
    proposal = ScenarioProposal(**{
        k: v for k, v in run.output.items()
        if k in ScenarioProposal.__annotations__
    })
    assert proposal.base_scenario
    assert proposal.expected_attack


def test_redteam_proposal_to_dict() -> None:
    agent = RedTeamScenarioAgent(seed=7)
    run = agent.run(goal="test")
    d = run.output
    assert "proposal_id" in d
    assert "features" in d
    assert "name" in d
    assert "rationale_source" in d


def test_redteam_difficulty_easy() -> None:
    agent = RedTeamScenarioAgent(seed=1)
    run = agent.run(goal="easy scenario", difficulty="easy")
    assert run.success is True


def test_redteam_difficulty_hard() -> None:
    agent = RedTeamScenarioAgent(seed=2)
    run = agent.run(goal="hard scenario", difficulty="hard")
    assert run.success is True


def test_redteam_known_failures_amplifies_mutation() -> None:
    agent = RedTeamScenarioAgent(seed=3)
    run = agent.run(
        goal="hard with failures",
        difficulty="medium",
        known_failures=["burst_rate is too low"],
    )
    assert run.success is True


def test_redteam_with_cover_scenario() -> None:
    """Force a seed that produces a cover scenario (or just confirm it runs)."""
    # We can't force the cover scenario without inspecting internals,
    # but we run many seeds to exercise the cover branch.
    any_had_cover = False
    for seed in range(20):
        agent = RedTeamScenarioAgent(seed=seed)
        run = agent.run(goal="test", difficulty="medium")
        if run.success and run.output.get("cover_scenario") is not None:
            any_had_cover = True
            break
    assert any_had_cover, "At least one seed should produce a cover scenario"


def test_redteam_rationale_is_deterministic_by_default() -> None:
    agent = RedTeamScenarioAgent(seed=42)
    run = agent.run(goal="test")
    assert run.output["rationale_source"] == "deterministic"


def test_redteam_same_seed_is_reproducible() -> None:
    agent_a = RedTeamScenarioAgent(seed=99)
    agent_b = RedTeamScenarioAgent(seed=99)
    run_a = agent_a.run(goal="test")
    run_b = agent_b.run(goal="test")
    assert run_a.output["proposal_id"] == run_b.output["proposal_id"]


def test_redteam_fails_when_no_hostile_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ScenarioRegistry, "catalog", classmethod(lambda cls: []))
    run = RedTeamScenarioAgent(seed=1).run(goal="test")
    assert run.success is False
    assert "No hostile scenarios" in (run.error or "")


def test_redteam_accepts_llm_rationale() -> None:
    class _LLM:
        name = "deepseek"

        def complete(self, **_: object) -> str:
            return "LLM rationale"

    agent = RedTeamScenarioAgent(seed=42, llm=_LLM())
    rationale, source = agent._build_rationale(
        base={"label": "Spoofing", "name": "spoofing_layering"},
        cover={"label": "TWAP"},
        mutated_keys=["w1000_order_cancel_rate"],
        difficulty="hard",
        deterministic="fallback",
        goal="test",
    )
    assert rationale == "LLM rationale"
    assert source == "llm"


def test_redteam_falls_back_when_llm_is_empty() -> None:
    class _LLM:
        name = "deepseek"

        def complete(self, **_: object) -> str:
            return ""

    agent = RedTeamScenarioAgent(seed=42, llm=_LLM())
    rationale, source = agent._build_rationale(
        base={"label": "Spoofing", "name": "spoofing_layering"},
        cover=None,
        mutated_keys=["w1000_order_cancel_rate"],
        difficulty="hard",
        deterministic="fallback",
        goal="test",
    )
    assert rationale == "fallback"
    assert source == "deterministic"


def test_redteam_evasion_can_mutate_cancel_rate() -> None:
    agent = RedTeamScenarioAgent(seed=42)
    features = {"w1000_order_cancel_rate": 0.90}
    agent._rng.sample = lambda population, k: ["w1000_order_cancel_rate"]  # type: ignore[method-assign]
    _, chosen = agent._apply_evasion(features, "hard")
    assert chosen == ["w1000_order_cancel_rate"]
    assert features["w1000_order_cancel_rate"] < 0.90


def test_redteam_evasion_ignores_unknown_dimension() -> None:
    agent = RedTeamScenarioAgent(seed=42)
    features = {"future_feature": 1.0}
    agent._rng.sample = lambda population, k: ["future_feature"]  # type: ignore[method-assign]
    _, chosen = agent._apply_evasion(features, "hard")
    assert chosen == ["future_feature"]
    assert features["future_feature"] == 1.0


def test_redteam_amplify_ignores_unrelated_failures() -> None:
    agent = RedTeamScenarioAgent(seed=42)
    features = {"w1000_agentic_burst_rate_per_second": 1.0}
    agent._amplify_for_failures(features, ["quantity_max drift"])
    assert features["w1000_agentic_burst_rate_per_second"] == 1.0
