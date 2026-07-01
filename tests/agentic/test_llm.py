"""Tests for the DeepSeek LLM client + provider factory — 100% coverage, no network."""

import httpx
import pytest

import marketimmune.agentic.llm as llm_module
from marketimmune.agentic.base import NullLLMClient
from marketimmune.agentic.llm import DeepSeekLLMClient, build_default_llm
from marketimmune.resilience import CircuitBreaker


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def _post_returning(payload: object):
    def _post(url, *, json, headers, timeout):  # noqa: ANN001, ANN202 - test stub
        return _FakeResponse(payload)

    return _post


def _post_raising():
    def _post(url, *, json, headers, timeout):  # noqa: ANN001, ANN202 - test stub
        raise httpx.HTTPError("boom")

    return _post


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekLLMClient()


def test_caps_max_tokens() -> None:
    client = DeepSeekLLMClient(api_key="k", max_tokens=10_000_000)
    assert client.max_tokens == DeepSeekLLMClient.HARD_MAX_OUTPUT_TOKENS


def test_complete_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": "  hi  "}}]}
    monkeypatch.setattr(httpx, "post", _post_returning(payload))
    assert DeepSeekLLMClient(api_key="k").complete("sys", "user") == "hi"


def test_complete_empty_content(monkeypatch: pytest.MonkeyPatch) -> None:
    # choices present but no message/content -> "" (covers the `or ""` fallbacks).
    monkeypatch.setattr(httpx, "post", _post_returning({"choices": [{}]}))
    assert DeepSeekLLMClient(api_key="k").complete("sys", "user") == ""


def test_complete_no_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", _post_returning({"choices": []}))
    assert DeepSeekLLMClient(api_key="k").complete("sys", "user") == ""


def test_complete_malformed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    # choices is not a list -> indexing raises -> caught -> "".
    monkeypatch.setattr(httpx, "post", _post_returning({"choices": 123}))
    assert DeepSeekLLMClient(api_key="k").complete("sys", "user") == ""


def test_complete_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", _post_raising())
    client = DeepSeekLLMClient(api_key="k", retry_sleep=lambda _seconds: None)
    assert client.complete("sys", "user") == ""


def test_complete_retries_transient_error() -> None:
    calls = 0

    def _post(url, *, json, headers, timeout):  # noqa: ANN001, ANN202 - test stub
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.HTTPError("transient")
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    client = DeepSeekLLMClient(
        api_key="k",
        post=_post,
        retry_attempts=2,
        retry_sleep=lambda _seconds: None,
    )
    assert client.complete("sys", "user") == "ok"
    assert calls == 2


def test_complete_fast_fails_when_circuit_open() -> None:
    calls = 0
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=30.0, now=lambda: 0.0)

    def _post(url, *, json, headers, timeout):  # noqa: ANN001, ANN202 - test stub
        nonlocal calls
        calls += 1
        raise httpx.HTTPError("boom")

    client = DeepSeekLLMClient(
        api_key="k",
        post=_post,
        circuit_breaker=breaker,
        retry_attempts=1,
        retry_sleep=lambda _seconds: None,
    )
    assert client.complete("sys", "user") == ""
    assert client.complete("sys", "user") == ""
    assert calls == 1


def test_factory_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKETIMMUNE_USE_LLM", raising=False)
    assert isinstance(build_default_llm(load_env=False), NullLLMClient)


def test_factory_loads_dotenv_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def _load_dotenv(*, override: bool = False) -> None:
        calls.append(override)

    monkeypatch.setattr(llm_module, "load_dotenv", _load_dotenv)
    monkeypatch.delenv("MARKETIMMUNE_USE_LLM", raising=False)
    assert isinstance(build_default_llm(load_env=True), NullLLMClient)
    assert calls == [False]


def test_factory_builds_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETIMMUNE_USE_LLM", "1")
    monkeypatch.setenv("MARKETIMMUNE_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert build_default_llm(load_env=False).name == "deepseek"


def test_factory_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETIMMUNE_USE_LLM", "1")
    monkeypatch.setenv("MARKETIMMUNE_LLM_PROVIDER", "bogus")
    assert isinstance(build_default_llm(load_env=False), NullLLMClient)


def test_factory_init_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETIMMUNE_USE_LLM", "1")
    monkeypatch.setenv("MARKETIMMUNE_LLM_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # Provider known but key missing -> client init raises -> caught -> Null.
    assert isinstance(build_default_llm(load_env=False), NullLLMClient)
