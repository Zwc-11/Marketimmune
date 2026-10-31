"""The no-look-ahead check: no feature may use information from at or after its fill.

:func:`check_no_lookahead` rebuilds a sample of rows with the future deleted and compares,
so a leak fails loudly (and in CI) instead of silently entering training. A Hyperliquid
snapshot stamped in the fill's own millisecond can already show the fill (fix L1), so the
cut deletes source rows *at* the fill's time too.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

import numpy as np

Row = Mapping[str, Any]
FeatureBuilder = Callable[..., Sequence[Mapping[str, Any]]]
_TAG = "__lookahead_label__"


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
) -> LookaheadReport:
    """Recompute features with the future deleted and compare.

    For ``sample`` label rows, ``build(labels, *sources)`` runs once uncut, for all
    sampled labels over every source row from the earliest sample's lookback on, and
    once per label at time ``t`` with every timestamped source row at or after ``t``
    deleted (untimestamped rows, such as static daily context, are kept in both). A
    feature that changes, or a row that disappears, means the builder read
    information from at or after the fill.

    ``build`` must be row-wise (each output depends only on its own label and the
    sources, as in an as-of join) and carry the label's keys into its output: the
    sampled labels are tagged so each uncut output finds its label. ``lookback_ms``
    bounds the cut runs to source rows in ``[t - lookback_ms, t)`` so the check stays
    linear in the sample size; a feature window longer than it shows up as a
    mismatch, never as a false pass. ``None`` keeps the full history.
    """
    if not labels:
        return LookaheadReport(0, 0, 0, tuple(columns), 0.0)
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(len(labels)), min(sample, len(labels))))
    indexed = [_TimeIndex.build(src, ts_key) for src in sources]
    lows = {i: -math.inf if lookback_ms is None else float(labels[i][ts_key]) - lookback_ms for i in picks}
    uncut = build([{**labels[i], _TAG: i} for i in picks], *(ix.window(min(lows.values()), math.inf) for ix in indexed))
    assert all(_TAG in row for row in uncut), "the feature builder must carry its label's keys through"
    full_by_label = {int(row[_TAG]): row for row in uncut}
    n_checked = n_mismatched = n_dropped = 0
    max_diff = 0.0
    examples: list[dict[str, Any]] = []
    for i in picks:
        full = full_by_label.get(i)
        if full is None:
            continue  # the builder skips this label even with all data: nothing to compare
        t = float(labels[i][ts_key])
        cut = build([labels[i]], *(ix.window(lows[i], t) for ix in indexed))
        n_checked += 1
        if not cut:
            n_dropped += 1
            if len(examples) < 5:
                examples.append({"label_index": i, "ts": t, "reason": "row needs future data"})
            continue
        diffs = {c: _diff(full.get(c), cut[0].get(c)) for c in columns}
        worst = max(diffs.values(), default=0.0)
        max_diff = max(max_diff, worst if math.isfinite(worst) else math.inf)
        if worst > atol:
            n_mismatched += 1
            if len(examples) < 5:
                examples.append({"label_index": i, "ts": t, "columns": {c: d for c, d in diffs.items() if d > atol}})
    return LookaheadReport(
        n_checked=n_checked,
        n_mismatched=n_mismatched,
        n_dropped=n_dropped,
        columns=tuple(columns),
        max_abs_diff=max_diff,
        examples=tuple(examples),
    )


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
        if np.all(ts[1:] >= ts[:-1]):  # sources usually arrive sorted
            return cls(ts=ts, rows=timed, static=static)
        order = np.argsort(ts, kind="stable")
        return cls(ts=ts[order], rows=[timed[j] for j in order.tolist()], static=static)

    def window(self, lo: float, hi: float) -> list[Row]:
        """Static rows plus timed rows with ``lo <= ts < hi``."""
        a = int(np.searchsorted(self.ts, lo, side="left")) if math.isfinite(lo) else 0
        b = int(np.searchsorted(self.ts, hi, side="left")) if math.isfinite(hi) else len(self.rows)
        return [*self.static, *self.rows[a:b]]


def _diff(a: object, b: object) -> float:
    """How far two feature values are apart: 0 when equal (NaN equals NaN), inf when only
    one is missing (None or NaN) or non-numeric values differ."""
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return math.inf
    if not (isinstance(a, Real) and isinstance(b, Real)):
        return 0.0 if a == b else math.inf
    fa, fb = float(a), float(b)
    if math.isnan(fa) or math.isnan(fb):
        return 0.0 if math.isnan(fa) and math.isnan(fb) else math.inf
    return abs(fa - fb)
