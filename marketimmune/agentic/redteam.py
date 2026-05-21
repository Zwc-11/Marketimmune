"""RedTeamScenarioAgent — proposes new adversarial scenarios.

Operates fully deterministically by default. It composes new attacks
by:

  * picking a hostile base scenario from the registry,
  * mutating selected feature dimensions toward "evasion" (lower
    cancel rates, longer interarrivals, smaller order sizes — the
    things a thoughtful attacker would tune),
  * optionally pairing the result with a benign cover scenario to
    simulate disguised activity (e.g. "TWAP-cover spoofing").

The proposed scenario is emitted as a *value object* — no DB writes
in this layer. The orchestrator persists it through Django.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from marketimmune.agentic.base import Agent
from marketimmune.simulator.scenarios import ScenarioRegistry

# Feature dimensions a real attacker would tune to evade the current
# detector. Importance values come straight from the trained model
# (see reports/risk_head_benchmark.json).
EVASION_DIMENSIONS = (
    "w1000_agentic_min_interarrival_ms",   # 0.42 importance
    "w1000_agentic_burst_rate_per_second",  # 0.19 importance
    "w5000_order_quantity_max",            # 0.14 importance
    "w60000_market_price_drift",           # 0.10 importance
    "w1000_order_cancel_rate",             # 0.07 importance
)


@dataclass(frozen=True, slots=True)
class ScenarioProposal:
    """One adversarial scenario proposal, ready for simulation."""

    proposal_id: str
    name: str
    base_scenario: str
    cover_scenario: str | None
    expected_attack: str
    evasion_strategy: str
    difficulty: str
    features: Mapping[str, float]
    side: str
    order_price_offset: float
    order_quantity: float
    trade_quantity: float
    trade_price_offset: float
    rationale: str = ""
    # Provenance: did the rationale come from a deterministic template
    # or from an LLM call? Recruiters reading the dashboard should be
    # able to tell at a glance.
    rationale_source: str = "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "name": self.name,
            "base_scenario": self.base_scenario,
            "cover_scenario": self.cover_scenario,
            "expected_attack": self.expected_attack,
            "evasion_strategy": self.evasion_strategy,
            "difficulty": self.difficulty,
            "features": dict(self.features),
            "side": self.side,
            "order_price_offset": self.order_price_offset,
            "order_quantity": self.order_quantity,
            "trade_quantity": self.trade_quantity,
            "trade_price_offset": self.trade_price_offset,
            "rationale": self.rationale,
            "rationale_source": self.rationale_source,
        }


class RedTeamScenarioAgent(Agent):
    """Mutates known attacks toward harder-to-detect variants."""

    name = "RedTeamScenarioAgent"
    description = "Proposes adversarial scenarios derived from registry families."

    def __init__(self, *, seed: int | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self._rng = random.Random(seed)

    # ---- subclass contract ----------------------------------------

    def _execute(
        self,
        *,
        goal: str,
        difficulty: str = "medium",
        known_failures: list[str] | None = None,
        **_: Any,
    ) -> Mapping[str, Any]:
        catalog = ScenarioRegistry.catalog()
        hostile = [c for c in catalog if c["family"] == "hostile"]
        benign = [c for c in catalog if c["family"] == "benign"]
        if not hostile:
            raise RuntimeError("No hostile scenarios registered.")

        # 1. Pick a hostile base.
        base = self._rng.choice(hostile)
        self.record_tool_call(
            "ScenarioRegistry.catalog",
            result_summary=f"{len(hostile)} hostile, {len(benign)} benign",
        )
        self.record_trace(
            goal=goal,
            observation=f"Selected base scenario {base['name']!r} ({base['label']}).",
            decision=f"base={base['name']}",
            confidence=0.7,
        )

        # 2. Optionally pair with a benign cover (60% chance when one exists).
        cover = None
        if benign and self._rng.random() < 0.6:
            cover = self._rng.choice(benign)
            self.record_trace(
                goal=goal,
                observation=f"Pairing with benign cover {cover['name']!r}.",
                decision=f"cover={cover['name']}",
                confidence=0.55,
            )

        # 3. Build the mutated feature vector from the base scenario.
        scenario_impl = ScenarioRegistry.create(base["name"])
        base_output = scenario_impl.step(0, 100.0)
        features = dict(base_output.features)
        evasion_summary, mutated_keys = self._apply_evasion(features, difficulty)

        # 4. If contained known failures, lean harder into them.
        if known_failures:
            self.record_trace(
                goal=goal,
                observation=(
                    f"Adapting to {len(known_failures)} known model failure(s): "
                    f"{', '.join(known_failures[:3])}."
                ),
                decision="amplify mutation",
                confidence=0.6,
            )
            self._amplify_for_failures(features, known_failures)

        # 5. Build the proposal.
        name_bits = [base["name"]]
        if cover:
            name_bits.append(f"under_{cover['name']}")
        name_bits.append(f"d{difficulty[:3]}")
        proposal_name = "_".join(name_bits)

        deterministic_rationale = (
            f"Mutated {', '.join(mutated_keys)} from the {base['name']} "
            "template toward thresholds attackers would use to evade "
            "burst-rate and cancel-rate detectors."
        )
        rationale, rationale_source = self._build_rationale(
            base=base,
            cover=cover,
            mutated_keys=mutated_keys,
            difficulty=difficulty,
            deterministic=deterministic_rationale,
            goal=goal,
        )

        proposal = ScenarioProposal(
            proposal_id=f"prop_{base['name']}_{self._rng.randint(1000, 9999)}",
            name=proposal_name,
            base_scenario=base["name"],
            cover_scenario=cover["name"] if cover else None,
            expected_attack=base["label"],
            evasion_strategy=evasion_summary,
            difficulty=difficulty,
            features=features,
            side=base_output.side,
            order_price_offset=base_output.order_price_offset,
            order_quantity=base_output.order_quantity,
            trade_quantity=base_output.trade_quantity,
            trade_price_offset=base_output.trade_price_offset,
            rationale=rationale,
            rationale_source=rationale_source,
        )
        self.record_trace(
            goal=goal,
            observation=(
                f"Composed proposal {proposal.name!r} mutating "
                f"{len(mutated_keys)} feature(s)."
            ),
            decision="emit ScenarioProposal",
            confidence=0.75,
            evidence={"mutated": mutated_keys},
        )
        return {
            "output": proposal.to_dict(),
            "artifacts": {"proposal_id": proposal.proposal_id},
        }

    # ---- mutation policy ------------------------------------------

    def _apply_evasion(
        self,
        features: dict[str, float],
        difficulty: str,
    ) -> tuple[str, list[str]]:
        """Adjust selected features toward "harder-to-detect" values."""
        scale = {"easy": 0.30, "medium": 0.55, "hard": 0.85}.get(difficulty, 0.55)
        chosen = self._rng.sample(EVASION_DIMENSIONS, k=self._rng.randint(2, 4))
        for key in chosen:
            current = features.get(key, 0.0)
            if key == "w1000_agentic_min_interarrival_ms":
                # Longer interarrival = looks slower, less bursty.
                features[key] = current + 200.0 * scale
            elif key == "w1000_agentic_burst_rate_per_second":
                features[key] = max(0.5, current * (1.0 - 0.6 * scale))
            elif key == "w5000_order_quantity_max":
                features[key] = max(0.001, current * (1.0 - 0.5 * scale))
            elif key == "w60000_market_price_drift":
                features[key] = max(0.0, current * (1.0 - 0.4 * scale))
            elif key == "w1000_order_cancel_rate":
                features[key] = max(0.02, current * (1.0 - 0.55 * scale))
        return (
            f"reduce {len(chosen)} top-importance features at {difficulty} intensity",
            chosen,
        )

    # ---- LLM augmentation ----------------------------------------

    def _build_rationale(
        self,
        *,
        base: dict[str, Any],
        cover: dict[str, Any] | None,
        mutated_keys: list[str],
        difficulty: str,
        deterministic: str,
        goal: str,
    ) -> tuple[str, str]:
        """Return ``(text, source)`` where source is "deterministic" or "llm".

        The deterministic baseline is always usable. When an LLM client
        is wired in, we ask it to write a short attacker-perspective
        rationale and accept it only if it returns non-empty text.
        """
        if self.llm.name == "null":
            return deterministic, "deterministic"
        cover_clause = (
            f" while disguising itself as {cover['label']!r} flow"
            if cover else ""
        )
        system = (
            "You are the red-team strategist for a simulated exchange market-safety "
            "lab. Write a one-paragraph (<=80 words) rationale that describes how "
            "your proposed attack evades detectors that look at burst-rate and "
            "cancel-rate. Be concrete about which feature dimensions you tuned and "
            "why. Do not include disclaimers or unrelated content."
        )
        user = (
            f"Base attack: {base['label']} ({base['name']}).\n"
            f"Cover scenario: {cover['label'] if cover else 'none'}.\n"
            f"Difficulty: {difficulty}.\n"
            f"Mutated feature dimensions: {', '.join(mutated_keys)}.\n"
            f"Constraint: rationale must read as if written by a thoughtful "
            f"attacker probing a microstructure surveillance system{cover_clause}."
        )
        self.record_tool_call(
            "llm.complete",
            arguments={
                "system_chars": len(system),
                "user_chars": len(user),
                "provider": self.llm.name,
            },
        )
        text = self.llm.complete(system=system, user=user, max_tokens=240, temperature=0.5)
        if not text:
            self.record_trace(
                goal=goal,
                observation="LLM returned empty rationale; using deterministic fallback.",
                decision="fallback",
                confidence=0.4,
            )
            return deterministic, "deterministic"
        self.record_trace(
            goal=goal,
            observation=f"LLM-augmented rationale ({len(text)} chars).",
            decision="accept_llm_rationale",
            confidence=0.7,
        )
        return text, "llm"

    def _amplify_for_failures(
        self, features: dict[str, float], failures: list[str]
    ) -> None:
        """Stub: lean into feature dimensions the prior model failed on.

        Real implementation would parse failure cases from
        InvestigationCases; for now we just nudge the burst rate
        further toward stealth so the next loop iteration is harder.
        """
        if "burst_rate" in " ".join(failures):
            features["w1000_agentic_burst_rate_per_second"] = max(
                0.3,
                features.get("w1000_agentic_burst_rate_per_second", 1.0) * 0.5,
            )
