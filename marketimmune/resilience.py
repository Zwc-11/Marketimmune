"""Resilience patterns for remote calls (Hyperliquid S3, DeepSeek) — v2 plan §8.

Two composable, dependency-free wrappers:

* :func:`with_retry` — retry on failure with exponential backoff + full jitter.
* :class:`CircuitBreaker` — trip open after repeated failures, fast-fail while open,
  then allow a single probe after a cooldown (half-open).

The side effects (``sleep``, the clock, the RNG) are injected, so both are fully
deterministic under test. Compose them around the injected callables from the ingest /
LLM layers, e.g.::

    fetch = with_retry(boto3_requester_pays_fetcher())
    archive = HyperliquidArchive(fetch=fetch, decompress=lz4_decompress)
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field


def with_retry[**P, T](
    fn: Callable[P, T],
    *,
    attempts: int = 3,
    base_delay_s: float = 0.1,
    max_delay_s: float = 10.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> Callable[P, T]:
    """Wrap ``fn`` to retry on ``exceptions`` with exponential backoff + full jitter."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    jitter_rng = rng if rng is not None else random.Random()

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        for attempt in range(1, attempts + 1):
            try:
                return fn(*args, **kwargs)
            except exceptions:
                if attempt >= attempts:
                    raise
                cap = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
                sleep(jitter_rng.uniform(0.0, cap))
        raise AssertionError("unreachable")  # pragma: no cover

    return wrapper


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit breaker is open."""


@dataclass
class CircuitBreaker:
    """Fast-fail wrapper that trips open after ``failure_threshold`` consecutive errors.

    While open it raises :class:`CircuitOpenError` until ``reset_timeout_s`` elapses, then
    allows one probe (half-open): a success closes it, a failure re-opens it.
    """

    failure_threshold: int = 5
    reset_timeout_s: float = 30.0
    now: Callable[[], float] = time.monotonic
    _failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    def call[**P, T](self, fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """Invoke ``fn`` through the breaker, tracking failures and open/closed state."""
        if self._opened_at is not None and self.now() - self._opened_at < self.reset_timeout_s:
            raise CircuitOpenError("circuit is open")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self.now()
            raise
        self._failures = 0
        self._opened_at = None
        return result
