"""Point-in-time / leakage invariants (v2 plan §5.3, §10).

The hard rule that makes look-ahead bias structurally impossible: every feature used to
score a fill must be timestamped at or before that fill. Wire :func:`assert_as_of` into
the feature pipeline so a violation fails loudly — including in CI via pytest — instead
of silently leaking future information into training.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np


class LeakageError(AssertionError):
    """Raised when a feature uses information from after the fill it labels."""


def is_point_in_time(feature_ts: Sequence[float], fill_ts: float) -> bool:
    """True iff every feature timestamp is at or before ``fill_ts`` (no look-ahead)."""
    return all(ts <= fill_ts for ts in feature_ts)


def assert_as_of(feature_ts: Sequence[float], fill_ts: float) -> None:
    """Raise :class:`LeakageError` if any feature timestamp is after ``fill_ts``."""
    if not is_point_in_time(feature_ts, fill_ts):
        raise LeakageError(f"look-ahead: feature ts {max(feature_ts)} > fill ts {fill_ts}")


def is_strictly_before(feature_ts: Sequence[float], fill_ts: float) -> bool:
    """True iff every feature timestamp is strictly before ``fill_ts`` (fix L1).

    A Hyperliquid snapshot stamped in the fill's own millisecond can already show
    the fill, so a feature row must be older than the fill, not merely no newer.
    """
    return all(ts < fill_ts for ts in feature_ts)


def assert_strictly_before(feature_ts: Sequence[float], fill_ts: float) -> None:
    """Raise :class:`LeakageError` if any feature timestamp is at or after ``fill_ts``."""
    if not is_strictly_before(feature_ts, fill_ts):
        raise LeakageError(f"look-ahead: feature ts {max(feature_ts)} >= fill ts {fill_ts}")


Row = Mapping[str, Any]
FeatureBuilder = Callable[..., Sequence[Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class LookaheadReport:
    """Outcome of :func:`check_no_lookahead` (fix B3: replaces ``leakage_safe = True``)."""

    n_checked: int
    n_mismatched: int
    n_dropped: int
    columns: tuple[str, ...]
    max_abs_diff: float
    examples: tuple[dict[str, Any], ...] = field(default=())

    @property
    def passed(self) -> bool:
        return self.n_checked > 0 and self.n_mismatched == 0 and self.n_dropped == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "n_checked": self.n_checked,
            "n_mismatched": self.n_mismatched,
            "n_dropped": self.n_dropped,
            "columns": list(self.columns),
            "max_abs_diff": self.max_abs_diff,
            "examples": list(self.examples),
        }


def check_no_lookahead(
    build: FeatureBuilder,
    labels: Sequence[Row],
    sources: Sequence[Sequence[Row]],
    *,
    columns: Sequence[str],
    sample: int = 200,
    seed: int = 0,
    ts_key: str = "ts_ms",
    lookback_ms: float | None = None,
    atol: float = 1e-9,
    batch_full: bool = True,
) -> LookaheadReport:
    """Recompute features with the future deleted and compare.

    For each sampled label row at time ``t``, ``build([label], *sources)`` is run
    twice: once on the sources as given and once with every timestamped source row
    at or after ``t`` deleted (untimestamped rows, such as static daily context, are
    kept in both). A feature that changes, or a row that disappears, means the
    builder read information from at or after the fill.

    ``lookback_ms`` bounds the cut run to source rows in ``[t - lookback_ms, t)`` so
    the check stays linear in the sample size. Set it above the longest feature
    window; a window longer than ``lookback_ms`` shows up as a mismatch, never as
    a false pass. ``None`` keeps the full history.

    With ``batch_full`` (the default) the uncut run is one ``build`` call for all
    sampled labels over every source row from the earliest sample's lookback on,
    instead of one call per label over ``[t - lookback_ms, end)``; the label rows
    are tagged so each output finds its label. That needs a row-wise builder (each
    output depends only on its own label and the sources, as in an as-of join); a
    builder that drops the tag falls back to one call per label.
    """
    if not labels:
        return LookaheadReport(0, 0, 0, tuple(columns), 0.0)
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(len(labels)), min(sample, len(labels))))
    indexed = [_TimeIndex.build(src, ts_key) for src in sources]
    lows = {
        i: -math.inf if lookback_ms is None else float(labels[i][ts_key]) - lookback_ms
        for i in picks
    }
    full_by_label = (
        _full_rows_in_one_call(build, labels, picks, indexed, min(lows.values()))
        if batch_full and picks
        else None
    )
    n_checked = n_mismatched = n_dropped = 0
    max_diff = 0.0
    examples: list[dict[str, Any]] = []
    for i in picks:
        label = labels[i]
        t = float(label[ts_key])
        lo = lows[i]
        full = (
            full_by_label.get(i, [])
            if full_by_label is not None
            else build([label], *(ix.window(lo, math.inf) for ix in indexed))
        )
        if not full:
            continue  # the builder skips this label even with all data: nothing to compare
        cut = build([label], *(ix.window(lo, t) for ix in indexed))
        n_checked += 1
        if not cut:
            n_dropped += 1
            if len(examples) < 5:
                examples.append({"label_index": i, "ts": t, "reason": "row needs future data"})
            continue
        diffs = {c: _diff(full[0].get(c), cut[0].get(c)) for c in columns}
        worst = max(diffs.values(), default=0.0)
        max_diff = max(max_diff, worst if math.isfinite(worst) else math.inf)
        if worst > atol:
            n_mismatched += 1
            if len(examples) < 5:
                bad = {c: d for c, d in diffs.items() if d > atol}
                examples.append({"label_index": i, "ts": t, "columns": bad})
    return LookaheadReport(
        n_checked=n_checked,
        n_mismatched=n_mismatched,
        n_dropped=n_dropped,
        columns=tuple(columns),
        max_abs_diff=max_diff,
        examples=tuple(examples),
    )


_TAG = "__lookahead_label__"


def _full_rows_in_one_call(
    build: FeatureBuilder,
    labels: Sequence[Row],
    picks: Sequence[int],
    indexed: Sequence[_TimeIndex],
    lo: float,
) -> dict[int, list[Row]] | None:
    """``{label index: [output row]}`` from one uncut ``build`` call, or ``None`` when
    the builder does not carry the tag through (then each label is built alone)."""
    tagged = [{**labels[i], _TAG: i} for i in picks]
    out = build(tagged, *(ix.window(lo, math.inf) for ix in indexed))
    if any(_TAG not in row for row in out):
        return None
    return {int(row[_TAG]): [row] for row in out}


@dataclass(frozen=True, slots=True)
class _TimeIndex:
    """Timestamped rows sorted by time, plus the untimestamped rows."""

    ts: np.ndarray[Any, np.dtype[np.float64]]
    rows: list[Row]
    static: list[Row]

    @classmethod
    def build(cls, rows: Sequence[Row], ts_key: str) -> _TimeIndex:
        timed = [r for r in rows if r.get(ts_key) is not None]
        static = [r for r in rows if r.get(ts_key) is None]
        ts = np.fromiter((float(r[ts_key]) for r in timed), dtype=np.float64, count=len(timed))
        order = np.argsort(ts, kind="stable")
        return cls(ts=ts[order], rows=[timed[j] for j in order.tolist()], static=static)

    def window(self, lo: float, hi: float) -> list[Row]:
        """Static rows plus timed rows with ``lo <= ts < hi``."""
        a = int(np.searchsorted(self.ts, lo, side="left")) if math.isfinite(lo) else 0
        b = int(np.searchsorted(self.ts, hi, side="left")) if math.isfinite(hi) else len(self.rows)
        return [*self.static, *self.rows[a:b]]


def _diff(a: object, b: object) -> float:
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return math.inf
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0 if a == b else math.inf
    if math.isnan(fa) and math.isnan(fb):
        return 0.0
    return abs(fa - fb)
