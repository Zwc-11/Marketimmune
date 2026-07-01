"""Shared numeric helpers with no domain, I/O, or framework dependencies.

A neutral home for small statistics utilities used across packages (features,
replay, …) so that, for example, the feature pipeline never has to import from
the replay engine just to reuse a one-line helper. Add further pure helpers here.
"""

from __future__ import annotations

from statistics import quantiles


def p95(values: list[float]) -> float:
    """95th-percentile of ``values`` (``0.0`` if empty; the lone value if n == 1)."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return quantiles(values, n=20)[18]
