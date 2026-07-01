"""Covers the InvestigatorAgent LLM-narrative path with an injected fake LLM.

Uses the shared ``plan`` / ``alert`` fixtures from conftest. A fake LLM (name != "null")
drives the LLM branch; an empty response exercises the deterministic fallback.
"""

from marketimmune.agentic.investigator import InvestigatorAgent
from marketimmune.agentic.sentinel import SentinelAlert
from marketimmune.simulator.replay_builder import ReplayPlan


class _FakeLLM:
    name = "fake"

    def __init__(self, text: str) -> None:
        self._text = text

    def complete(
        self, system: str, user: str, *, max_tokens: int = 256, temperature: float = 0.2
    ) -> str:
        return self._text


def test_investigator_accepts_llm_narrative(plan: ReplayPlan, alert: SentinelAlert) -> None:
    agent = InvestigatorAgent(llm=_FakeLLM("Analyst memo: suspected spoofing/layering."))
    run = agent.run(goal="build cases", plan=plan, alerts=[alert])
    assert run.success
    assert any(trace.decision == "accept_llm_narrative" for trace in run.traces)


def test_investigator_falls_back_on_empty_llm(plan: ReplayPlan, alert: SentinelAlert) -> None:
    agent = InvestigatorAgent(llm=_FakeLLM(""))
    run = agent.run(goal="build cases", plan=plan, alerts=[alert])
    assert run.success
    assert any(trace.decision == "fallback" for trace in run.traces)
