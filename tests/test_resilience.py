"""Tests for the resilience layer — deterministic, no real sleeping (100% coverage)."""

import random

import pytest

from marketimmune.resilience import CircuitBreaker, CircuitOpenError, with_retry


class FakeClock:
    """A controllable monotonic clock for the circuit-breaker tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# ---- with_retry ------------------------------------------------------------


def test_retry_succeeds_first_try() -> None:
    calls: list[int] = []

    def fn() -> str:
        calls.append(1)
        return "ok"

    # No rng/sleep injected -> exercises the default random.Random() branch.
    assert with_retry(fn)() == "ok"
    assert len(calls) == 1


def test_retry_recovers_after_failures() -> None:
    state = {"n": 0}
    slept: list[float] = []

    def flaky() -> str:
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    wrapped = with_retry(flaky, attempts=3, sleep=slept.append, rng=random.Random(0))
    assert wrapped() == "ok"
    assert state["n"] == 3
    assert len(slept) == 2  # slept once between each of the two failures


def test_retry_exhausts_and_reraises() -> None:
    def always_fail() -> str:
        raise RuntimeError("nope")

    wrapped = with_retry(always_fail, attempts=2, sleep=lambda _s: None, rng=random.Random(0))
    with pytest.raises(RuntimeError, match="nope"):
        wrapped()


def test_retry_rejects_bad_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        with_retry(lambda: None, attempts=0)


def test_retry_only_catches_listed_exceptions() -> None:
    def fn() -> None:
        raise KeyError("x")

    wrapped = with_retry(fn, attempts=3, exceptions=(ValueError,), sleep=lambda _s: None)
    with pytest.raises(KeyError):
        wrapped()


# ---- CircuitBreaker --------------------------------------------------------


def test_breaker_passes_through_success() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    assert breaker.call(lambda: "ok") == "ok"


def test_breaker_counts_failures_without_opening() -> None:
    breaker = CircuitBreaker(failure_threshold=2)

    def fail() -> None:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        breaker.call(fail)  # 1 failure < threshold 2 -> stays closed
    with pytest.raises(RuntimeError):
        breaker.call(fail)  # 2nd failure -> trips open


def test_breaker_opens_and_fast_fails() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=30.0, now=clock)

    def fail() -> None:
        raise RuntimeError("x")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(fail)
    # Open and still within the cooldown -> fast-fail without calling fn.
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "ignored")


def test_breaker_half_open_recovers() -> None:
    clock = FakeClock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=10.0, now=clock)

    def fail() -> None:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        breaker.call(fail)  # threshold 1 -> opens immediately
    clock.t = 11.0  # advance past the cooldown
    assert breaker.call(lambda: "ok") == "ok"  # half-open probe succeeds -> closes
