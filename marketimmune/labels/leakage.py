"""Point-in-time / leakage invariants (v2 plan §5.3, §10).

The hard rule that makes look-ahead bias structurally impossible: every feature used to
score a fill must be timestamped at or before that fill. Wire :func:`assert_as_of` into
the feature pipeline so a violation fails loudly — including in CI via pytest — instead
of silently leaking future information into training.
"""

from __future__ import annotations

from collections.abc import Sequence


class LeakageError(AssertionError):
    """Raised when a feature uses information from after the fill it labels."""


def is_point_in_time(feature_ts: Sequence[float], fill_ts: float) -> bool:
    """True iff every feature timestamp is at or before ``fill_ts`` (no look-ahead)."""
    return all(ts <= fill_ts for ts in feature_ts)


def assert_as_of(feature_ts: Sequence[float], fill_ts: float) -> None:
    """Raise :class:`LeakageError` if any feature timestamp is after ``fill_ts``."""
    if not is_point_in_time(feature_ts, fill_ts):
        raise LeakageError(f"look-ahead: feature ts {max(feature_ts)} > fill ts {fill_ts}")
