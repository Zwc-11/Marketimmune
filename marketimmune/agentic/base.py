"""Agentic core — base classes, value objects, and the LLM client interface.

Design rules for this package:

1.  **Deterministic by default.** Every agent must work end-to-end with
    no API keys, no network calls. An optional `llm` collaborator can
    be passed in; agents call ``llm.complete(prompt, ...)`` only when
    one is supplied, and always have a deterministic fallback path so
    a demo never breaks because of a rate limit or auth error.

2.  **Explicit traces, not magic.** Every agent step yields an
    :class:`AgentRun` containing structured ``ToolCall`` and
    ``DecisionTrace`` records. Persistence is the caller's
    responsibility; the engine itself is framework-free.

3.  **Composable, not monolithic.** Agents are wired together by an
    ``ImmuneLoop`` orchestrator that lives outside this module. Each
    agent only knows about its inputs and outputs.

4.  **Honest about what is real.** When an agent uses simulated data,
    its decision trace must say so. Recruiters reading the code must
    be able to distinguish ``"real Binance kline volume"`` from
    ``"simulated scenario feature template"`` in one glance.
"""

from __future__ import annotations

import abc
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# LLM client protocol
# ---------------------------------------------------------------------------


class LLMClient(Protocol):
    """Pluggable language-model interface.

    Implementations may wrap OpenAI / Anthropic / a local model; the
    agentic core never imports any vendor SDK directly. A
    :class:`NullLLMClient` ships with the package and is used when the
    operator chose to run the loop fully deterministically.
    """

    name: str

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        ...


class NullLLMClient:
    """No-op LLM client used as the default in every agent.

    Returns an empty string for any prompt. The presence of this client
    means agents that *could* use an LLM must still emit a meaningful
    deterministic output, which is exactly the discipline we want.
    """

    name = "null"

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        return ""


# ---------------------------------------------------------------------------
# Value objects emitted by every agent
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single tool invocation an agent performed.

    Tools are arbitrary Python callables (a DB query, a model
    inference, a parquet read). We record the name + duration + result
    summary so the trace is rich enough to debug after the fact.
    """

    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    result_summary: str = ""
    occurred_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    """One reasoning step recorded by an agent.

    Captures the goal, what was observed, the chosen action, and an
    optional confidence. Recruiter-readable; investigators downstream
    consume these to build evidence cases.
    """

    goal: str
    observation: str
    decision: str
    confidence: float = 0.5
    evidence: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class AgentRun:
    """The structured output of one ``Agent.run(...)`` invocation.

    An :class:`AgentRun` is intentionally immutable. To represent a
    sequence of decisions, an agent emits one run per decision and the
    orchestrator collects them.
    """

    run_id: str
    agent_name: str
    goal: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float
    tool_calls: tuple[ToolCall, ...]
    traces: tuple[DecisionTrace, ...]
    output: Mapping[str, Any]
    success: bool = True
    error: str | None = None
    linked_artifacts: Mapping[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        last = self.traces[-1] if self.traces else None
        return (
            f"[{self.agent_name}] {self.goal} -> "
            f"{last.decision if last else 'no decision'}"
        )


# ---------------------------------------------------------------------------
# Agent base class
# ---------------------------------------------------------------------------


class Agent(abc.ABC):
    """Abstract base for every agent in the immune loop.

    Subclasses override :meth:`_execute`; the public :meth:`run` wraps
    that call with timing, error capture, and structured-trace
    assembly. This keeps the per-agent code focused on *what the agent
    does*, not on bookkeeping.
    """

    name: str
    description: str

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
    ):
        self.llm: LLMClient = llm or NullLLMClient()
        # ``_pending_*`` buffers are filled by helpers below and
        # consumed at the end of :meth:`run`.
        self._pending_tool_calls: list[ToolCall] = []
        self._pending_traces: list[DecisionTrace] = []

    # ---- public ----------------------------------------------------

    def run(self, *, goal: str, **inputs: Any) -> AgentRun:
        """Execute the agent and return a full structured trace."""
        run_id = _new_id(f"run_{self.name}")
        started_at = _utcnow()
        start_perf = time.perf_counter()
        # Reset per-run buffers in case the same instance is reused.
        self._pending_tool_calls = []
        self._pending_traces = []

        success = True
        error: str | None = None
        output: Mapping[str, Any] = {}
        artifacts: Mapping[str, Any] = {}

        try:
            result = self._execute(goal=goal, **inputs)
            if isinstance(result, dict):
                output = result.get("output", {}) or {}
                artifacts = result.get("artifacts", {}) or {}
            else:
                output = {"value": result}
        except Exception as exc:  # noqa: BLE001 — top-level boundary.
            success = False
            error = f"{type(exc).__name__}: {exc}"
            self.record_trace(
                goal=goal,
                observation="agent raised an exception",
                decision=f"abort with error: {error}",
                confidence=0.0,
            )

        finished_at = _utcnow()
        duration_ms = (time.perf_counter() - start_perf) * 1000.0
        return AgentRun(
            run_id=run_id,
            agent_name=self.name,
            goal=goal,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            tool_calls=tuple(self._pending_tool_calls),
            traces=tuple(self._pending_traces),
            output=output,
            success=success,
            error=error,
            linked_artifacts=artifacts,
        )

    # ---- helpers exposed to subclasses ----------------------------

    def record_tool_call(
        self,
        tool: str,
        *,
        arguments: Mapping[str, Any] | None = None,
        result_summary: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        self._pending_tool_calls.append(ToolCall(
            tool=tool,
            arguments=dict(arguments or {}),
            duration_ms=duration_ms,
            result_summary=result_summary,
        ))

    def record_trace(
        self,
        *,
        goal: str,
        observation: str,
        decision: str,
        confidence: float = 0.5,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self._pending_traces.append(DecisionTrace(
            goal=goal,
            observation=observation,
            decision=decision,
            confidence=max(0.0, min(1.0, confidence)),
            evidence=dict(evidence or {}),
        ))

    # ---- subclass contract ----------------------------------------

    @abc.abstractmethod
    def _execute(self, *, goal: str, **inputs: Any) -> Mapping[str, Any] | Any:
        """Do the agent's actual work and return its output mapping."""
