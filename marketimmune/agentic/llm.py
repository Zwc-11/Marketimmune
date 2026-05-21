"""LLM client implementations for the agentic loop.

Currently ships one real provider — :class:`AnthropicLLMClient` — and
relies on the :class:`NullLLMClient` from :mod:`marketimmune.agentic.base`
for the deterministic-only mode.

Design rules
============

1.  **No silent calls.** A client is only created when both
    ``ANTHROPIC_API_KEY`` is present *and* ``MARKETIMMUNE_USE_LLM`` is
    truthy. The agentic service uses :func:`build_default_llm` so the
    operator's intent is always explicit.

2.  **Never raise into an agent.** A network error, rate limit, or
    bad-prompt response must not crash the immune loop. The client
    catches any ``Exception`` from the SDK and returns ``""`` — agents
    are required to behave well on an empty string.

3.  **Extended thinking is on by default.** Claude Sonnet 4.5+ supports
    the ``thinking={"type": "enabled", "budget_tokens": N}`` parameter
    which makes the model deliberate before answering. The agentic
    loop is short (≤6 LLM calls per iteration), so spending a few
    thousand thinking tokens per call is cheap and noticeably improves
    the quality of red-team rationale and investigator narratives.
"""

from __future__ import annotations

import logging
import os

# Anthropic is an optional runtime dependency — the agentic loop runs
# fine without it. Import lazily so a missing wheel doesn't break the
# whole package.
try:  # pragma: no cover — exercised only when the SDK is installed.
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

try:  # `python-dotenv` is also optional; we never require it.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

from marketimmune.agentic.base import LLMClient, NullLLMClient

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------


class AnthropicLLMClient:
    """LLM client backed by Anthropic Claude with extended thinking."""

    name = "anthropic"

    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
    DEFAULT_MAX_TOKENS = 4000
    DEFAULT_THINKING_BUDGET = 2000
    # Hard cap on the per-request `max_tokens` Anthropic accepts.
    # The Sonnet family caps output at 64k tokens; we cap a bit below
    # that to leave headroom and to keep latency bounded.
    HARD_MAX_OUTPUT_TOKENS = 16000

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
    ):
        if anthropic is None:
            raise RuntimeError(
                "anthropic package is not installed; "
                "`pip install anthropic>=0.40` first."
            )
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = anthropic.Anthropic(api_key=resolved_key)
        self.model = model or os.environ.get("CLAUDE_MODEL", self.DEFAULT_MODEL)
        # Capped here — a typo like `CLAUDE_MAX_TOKENS=1000000` would
        # otherwise be passed straight through to the API and rejected
        # as a 400 invalid_request_error.
        raw_max = int(
            max_tokens or os.environ.get("CLAUDE_MAX_TOKENS", self.DEFAULT_MAX_TOKENS)
        )
        self.max_tokens = max(1024, min(raw_max, self.HARD_MAX_OUTPUT_TOKENS))
        if self.max_tokens != raw_max:
            _LOG.info(
                "CLAUDE_MAX_TOKENS %s capped to %s for API safety.",
                raw_max, self.max_tokens,
            )
        self.thinking_budget = int(
            thinking_budget
            or os.environ.get("CLAUDE_THINKING_BUDGET", self.DEFAULT_THINKING_BUDGET)
        )
        if self.thinking_budget >= self.max_tokens:
            # Auto-shrink rather than throwing — a misconfig should
            # degrade, not crash the loop.
            self.thinking_budget = max(1024, self.max_tokens - 1024)
            _LOG.info(
                "thinking_budget shrunk to %s for max_tokens=%s.",
                self.thinking_budget,
                self.max_tokens,
            )

    # ---- LLMClient protocol ---------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        """Run one Claude call with extended thinking enabled.

        Any failure — network, auth, refusal, malformed response —
        returns an empty string and is logged. Callers must already
        have a deterministic fallback path; that is the contract.
        """
        # Extended thinking requires temperature == 1.0 in the
        # Anthropic API and an output budget strictly greater than the
        # thinking budget; we honour both here regardless of what the
        # caller passed for `temperature`.
        # Output budget = caller's request + thinking, but never more
        # than the hard cap we negotiated with the API.
        effective_max = min(
            self.max_tokens,
            max(max_tokens + self.thinking_budget + 256, self.thinking_budget + 1024),
        )
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=effective_max,
                temperature=1.0,
                system=system,
                thinking={
                    "type": "enabled",
                    "budget_tokens": self.thinking_budget,
                },
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — boundary log + fallback.
            # Surface the *real* Anthropic message: bad model id,
            # invalid_request_error, rate limit, etc. The agent will
            # fall back to its deterministic path, but a developer
            # tailing the logs needs to see what went wrong.
            _LOG.warning(
                "Anthropic call failed (model=%s, max_tokens=%s): %s",
                self.model, effective_max, exc,
            )
            return ""

        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            # "thinking" blocks are deliberately not surfaced to the
            # agent — they are internal model reasoning that should
            # not leak into the structured trace.
        return "\n".join(p for p in text_parts if p).strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_default_llm(*, load_env: bool = True) -> LLMClient:
    """Construct the LLM client the agentic loop should use.

    Decision matrix
    ---------------

    +-----------------------------+-----------------------+------------------------+
    | MARKETIMMUNE_USE_LLM        | ANTHROPIC_API_KEY     | Returned client        |
    +=============================+=======================+========================+
    | unset / 0 / false           | (any)                 | :class:`NullLLMClient` |
    | 1 / true / yes              | unset                 | :class:`NullLLMClient` |
    | 1 / true / yes              | set                   | :class:`AnthropicLLMClient` |
    +-----------------------------+-----------------------+------------------------+

    If the operator asked for the LLM but the SDK or key is missing,
    we log a warning and fall back to deterministic — never raise.
    """
    if load_env and load_dotenv is not None:
        load_dotenv(override=False)

    flag = (os.environ.get("MARKETIMMUNE_USE_LLM") or "").strip().lower()
    use_llm = flag in {"1", "true", "yes", "on"}
    if not use_llm:
        return NullLLMClient()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _LOG.warning(
            "MARKETIMMUNE_USE_LLM is on but ANTHROPIC_API_KEY is missing; "
            "falling back to NullLLMClient."
        )
        return NullLLMClient()
    try:
        return AnthropicLLMClient()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("Could not initialise AnthropicLLMClient (%s); using NullLLMClient.", exc)
        return NullLLMClient()


__all__ = ["AnthropicLLMClient", "build_default_llm"]
