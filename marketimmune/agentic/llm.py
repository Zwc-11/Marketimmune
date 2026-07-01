"""LLM client implementations for the agentic loop.

Ships one real provider — :class:`DeepSeekLLMClient` (DeepSeek V4, the default) —
and relies on the :class:`NullLLMClient` from :mod:`marketimmune.agentic.base`
for the deterministic-only mode. DeepSeek exposes an OpenAI-compatible API, so we
call it over ``httpx`` (already a dependency) and add no vendor SDK. The active
provider is chosen by ``MARKETIMMUNE_LLM_PROVIDER`` (default ``deepseek``),
leaving room to register more providers later without touching the agents.

Design rules
============

1.  **No silent calls.** A real client is only created when the selected
    provider's API key is present *and* ``MARKETIMMUNE_USE_LLM`` is truthy.
    The agentic service uses :func:`build_default_llm` so the operator's
    intent is always explicit.

2.  **Never raise into an agent.** A network error, rate limit, or bad
    response must not crash the immune loop. The client catches any
    exception and returns ``""`` — agents are required to behave well on an
    empty string (they fall back to their deterministic path).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

try:  # `python-dotenv` is optional; we never require it.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

from marketimmune.agentic.base import LLMClient, NullLLMClient
from marketimmune.resilience import CircuitBreaker, with_retry

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DeepSeek (OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------


class DeepSeekLLMClient:
    """LLM client backed by DeepSeek's OpenAI-compatible chat API.

    Talks to ``{base_url}/chat/completions`` over ``httpx`` with a Bearer key.
    The default model is ``deepseek-v4-pro`` (top reasoning/agentic tier);
    set ``DEEPSEEK_MODEL=deepseek-v4-flash`` for cheaper, faster iteration.
    """

    name = "deepseek"

    DEFAULT_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-v4-pro"
    DEFAULT_MAX_TOKENS = 4000
    DEFAULT_TIMEOUT_S = 60.0
    DEFAULT_RETRY_ATTEMPTS = 2
    # Output-token guard so a typo like DEEPSEEK_MAX_TOKENS=1000000 can't be
    # passed straight through and rejected as a 400.
    HARD_MAX_OUTPUT_TOKENS = 8192

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        post: Callable[..., Any] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_sleep: Callable[[float], None] | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set.")
        self._api_key = resolved_key
        self.base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL", self.DEFAULT_BASE_URL)
        ).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL", self.DEFAULT_MODEL)
        raw_max = int(
            max_tokens or os.environ.get("DEEPSEEK_MAX_TOKENS", str(self.DEFAULT_MAX_TOKENS))
        )
        self.max_tokens = max(256, min(raw_max, self.HARD_MAX_OUTPUT_TOKENS))
        if self.max_tokens != raw_max:
            _LOG.info(
                "DEEPSEEK_MAX_TOKENS %s capped to %s for API safety.",
                raw_max, self.max_tokens,
            )
        self.timeout_s = float(
            timeout_s or os.environ.get("DEEPSEEK_TIMEOUT_S", str(self.DEFAULT_TIMEOUT_S))
        )
        self._post = post or httpx.post
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=3,
            reset_timeout_s=30.0,
        )
        self.retry_attempts = retry_attempts
        self._retry_sleep = retry_sleep or time.sleep

    # ---- LLMClient protocol ---------------------------------------

    def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 256,
        temperature: float = 0.2,
    ) -> str:
        """Run one DeepSeek chat completion.

        Any failure — network, auth, rate limit, malformed response —
        returns an empty string and is logged. Callers must already have a
        deterministic fallback path; that is the contract.
        """
        effective_max = max(256, min(max_tokens, self.max_tokens))
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": effective_max,
            "temperature": temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = self._post_chat_completion(payload, headers)
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — boundary log + fallback.
            # Surface the real reason (bad model id, 401, 429, timeout) so a
            # developer tailing the logs can see it; the agent still falls
            # back to its deterministic path.
            _LOG.warning(
                "DeepSeek call failed (model=%s, base=%s): %s",
                self.model, self.base_url, exc,
            )
            return ""

        try:
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            # Reasoning-tier models also return `reasoning_content` (the
            # model's scratchpad). We surface only the final `content`, never
            # the reasoning, so it cannot leak into the structured trace.
            content = message.get("content") or ""
            return str(content).strip()
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            _LOG.warning("DeepSeek response parse failed: %s", exc)
            return ""

    def _post_chat_completion(
        self,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Any:
        def send() -> Any:
            response = self._post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        resilient_send = with_retry(
            send,
            attempts=self.retry_attempts,
            sleep=self._retry_sleep,
        )
        return self._circuit_breaker.call(resilient_send)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# Provider registry — add a new OpenAI-compatible or SDK-backed client here and
# select it with MARKETIMMUNE_LLM_PROVIDER. The agents never see this choice.
_PROVIDERS: dict[str, type[DeepSeekLLMClient]] = {
    "deepseek": DeepSeekLLMClient,
}

DEFAULT_PROVIDER = "deepseek"


def build_default_llm(*, load_env: bool = True) -> LLMClient:
    """Construct the LLM client the agentic loop should use.

    Decision matrix
    ---------------

    +----------------------+--------------------------+--------------------------+
    | MARKETIMMUNE_USE_LLM | provider key present?     | Returned client          |
    +======================+==========================+==========================+
    | unset / 0 / false    | (any)                    | :class:`NullLLMClient`   |
    | 1 / true / yes       | no (e.g. DEEPSEEK key)   | :class:`NullLLMClient`   |
    | 1 / true / yes       | yes                      | provider client          |
    +----------------------+--------------------------+--------------------------+

    The provider is ``MARKETIMMUNE_LLM_PROVIDER`` (default ``deepseek``). If the
    operator asked for the LLM but the key/provider is missing or unknown, we
    log a warning and fall back to deterministic — never raise.
    """
    if load_env and load_dotenv is not None:
        load_dotenv(override=False)

    flag = (os.environ.get("MARKETIMMUNE_USE_LLM") or "").strip().lower()
    use_llm = flag in {"1", "true", "yes", "on"}
    if not use_llm:
        return NullLLMClient()

    provider = (os.environ.get("MARKETIMMUNE_LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    client_cls = _PROVIDERS.get(provider)
    if client_cls is None:
        _LOG.warning(
            "Unknown MARKETIMMUNE_LLM_PROVIDER %r; using NullLLMClient. Known: %s",
            provider, sorted(_PROVIDERS),
        )
        return NullLLMClient()
    try:
        return client_cls()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "Could not initialise %s LLM (%s); using NullLLMClient.", provider, exc
        )
        return NullLLMClient()


__all__ = ["DeepSeekLLMClient", "build_default_llm"]
