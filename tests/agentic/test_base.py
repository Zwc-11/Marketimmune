"""Tests for marketimmune.agentic.base."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from marketimmune.agentic.base import (
    Agent,
    AgentRun,
    DecisionTrace,
    NullLLMClient,
    ToolCall,
)

# ---------------------------------------------------------------------------
# NullLLMClient
# ---------------------------------------------------------------------------


def test_null_llm_client_returns_empty_string() -> None:
    client = NullLLMClient()
    assert client.complete("sys", "user") == ""
    assert client.name == "null"


def test_null_llm_client_extra_kwargs() -> None:
    client = NullLLMClient()
    assert client.complete("s", "u", max_tokens=512, temperature=0.5) == ""


# ---------------------------------------------------------------------------
# Agent (concrete subclass)
# ---------------------------------------------------------------------------


class _EchoAgent(Agent):
    name = "EchoAgent"
    description = "Returns its goal as output."

    def _execute(self, *, goal: str, **inputs: Any) -> Mapping[str, Any]:
        self.record_tool_call("echo_tool", arguments={"goal": goal}, result_summary="ok")
        self.record_trace(
            goal=goal, observation="echoing", decision="return goal", confidence=0.99
        )
        return {"output": {"echoed": goal}, "artifacts": {"raw": goal}}


class _ErrorAgent(Agent):
    name = "ErrorAgent"
    description = "Always raises."

    def _execute(self, *, goal: str, **inputs: Any) -> Mapping[str, Any]:
        raise RuntimeError("deliberate error")


class _ScalarAgent(Agent):
    name = "ScalarAgent"
    description = "Returns a scalar value."

    def _execute(self, *, goal: str, **inputs: Any) -> str:
        return f"value:{goal}"


def test_agent_run_success() -> None:
    agent = _EchoAgent()
    run = agent.run(goal="hello")
    assert run.success is True
    assert run.error is None
    assert run.output["echoed"] == "hello"
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].tool == "echo_tool"
    assert len(run.traces) == 1
    assert run.traces[0].decision == "return goal"
    assert run.traces[0].confidence == 0.99


def test_agent_run_error_capture() -> None:
    agent = _ErrorAgent()
    run = agent.run(goal="boom")
    assert run.success is False
    assert "RuntimeError" in (run.error or "")
    assert "deliberate error" in (run.error or "")
    assert len(run.traces) == 1
    assert "abort" in run.traces[0].decision


def test_agent_run_wraps_scalar_output() -> None:
    agent = _ScalarAgent()
    run = agent.run(goal="plain")
    assert run.success is True
    assert run.output == {"value": "value:plain"}


def test_agent_run_summary_with_traces() -> None:
    agent = _EchoAgent()
    run = agent.run(goal="demo")
    assert "EchoAgent" in run.summary
    assert "return goal" in run.summary


def test_agent_run_summary_no_traces() -> None:
    """AgentRun.summary falls back gracefully when there are no traces."""
    agent = _EchoAgent()
    run = agent.run(goal="demo")
    # Manufacture a run with empty traces tuple.
    empty_run = AgentRun(
        run_id=run.run_id,
        agent_name=run.agent_name,
        goal=run.goal,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        tool_calls=(),
        traces=(),
        output={},
    )
    assert "no decision" in empty_run.summary


def test_agent_reuse_resets_buffers() -> None:
    agent = _EchoAgent()
    agent.run(goal="first")
    agent.run(goal="second")
    # Second run should only have 1 tool call, not 2.
    run = agent.run(goal="third")
    assert len(run.tool_calls) == 1


def test_record_tool_call_defaults() -> None:
    agent = _EchoAgent()
    agent._pending_tool_calls = []
    agent.record_tool_call("my_tool")
    tc = agent._pending_tool_calls[0]
    assert isinstance(tc, ToolCall)
    assert tc.tool == "my_tool"
    assert tc.arguments == {}


def test_record_trace_clamps_confidence() -> None:
    agent = _EchoAgent()
    agent._pending_traces = []
    agent.record_trace(
        goal="g", observation="obs", decision="dec", confidence=1.5, evidence={"k": "v"}
    )
    dt = agent._pending_traces[0]
    assert isinstance(dt, DecisionTrace)
    assert dt.confidence == 1.0  # clamped to 1.0


def test_agent_linked_artifacts() -> None:
    agent = _EchoAgent()
    run = agent.run(goal="test")
    assert run.linked_artifacts["raw"] == "test"


def test_null_llm_is_used_by_default() -> None:
    agent = _EchoAgent()
    assert isinstance(agent.llm, NullLLMClient)


def test_custom_llm_is_wired() -> None:
    custom_llm = NullLLMClient()
    custom_llm.name = "custom"  # type: ignore[misc]
    agent = _EchoAgent(llm=custom_llm)
    assert agent.llm.name == "custom"
