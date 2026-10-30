"""Temporal cross-validation splits for markout models.

Two schemes, both purged around each test window:

``walk_forward``
    Anchored (expanding) walk-forward. Rows are sorted by time and cut into
    ``n_splits + 1`` contiguous blocks. Fold ``k`` tests on block ``k + 1`` and trains
    only on rows strictly before ``test_start - purge_ms``. No fold ever sees the
    future, so this is the scheme to quote as "walk-forward".

``rolling_daily``
    Rolling walk-forward by calendar day (UTC), the scheme v3 reports (fix B5).
    Each fold tests one whole day ``d`` and trains on the ``train_days`` days
    before it, ending ``purge_ms`` before ``d`` starts. Days without a full
    ``train_days`` of history before them are never tested. ``n_splits`` and
    ``embargo_ms`` are ignored: nothing after the test day is ever used.

``purged_kfold``
    Purged k-fold with a post-test embargo (Lopez de Prado). Rows are cut into
    ``n_splits`` blocks; each fold tests one block and trains on every row outside
    ``[test_start - purge_ms, test_end + embargo_ms]``, which includes rows *after*
    the test window. It removes label overlap, not look-ahead in regime. The
    committed SOL report predating ``cv_scheme`` was produced with this scheme.

The array API (:func:`temporal_fold_arrays`) is the hot path used by training and
evaluation. It is ``O(n log n)`` for the sort plus ``O(n)`` per fold with no Python
loop over rows. The tuple API wraps it for small inputs and tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

CvScheme = Literal["walk_forward", "purged_kfold", "rolling_daily"]
CV_SCHEMES: tuple[CvScheme, ...] = ("walk_forward", "purged_kfold", "rolling_daily")
IndexArray = npt.NDArray[np.intp]
DAY_MS = 86_400_000.0
DEFAULT_ROLLING_TRAIN_DAYS = 7


@dataclass(frozen=True, slots=True)
class FoldArrays:
    """One temporal split as index arrays into the caller's original row order."""

    train: IndexArray
    test: IndexArray
    test_start_ms: float
    test_end_ms: float
    purge_start_ms: float
    embargo_end_ms: float


@dataclass(frozen=True, slots=True)
class TemporalFold:
    """One temporal split: train indices never overlap the purged test window."""

    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    test_start_ms: float
    test_end_ms: float
    purge_start_ms: float
    embargo_end_ms: float


def temporal_fold_arrays(
    timestamps_ms: Sequence[float] | npt.ArrayLike,
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    scheme: CvScheme = "walk_forward",
    train_days: int | None = None,
) -> tuple[FoldArrays, ...]:
    """Build temporal folds as ``np.intp`` index arrays.

    Ties in time keep input order (stable sort), so the output is deterministic for
    a given input regardless of how the caller batches rows. ``train_days`` applies
    to ``rolling_daily`` only (default ``DEFAULT_ROLLING_TRAIN_DAYS``).
    """
    ts = np.asarray(timestamps_ms, dtype=np.float64)
    if scheme == "rolling_daily":
        days = DEFAULT_ROLLING_TRAIN_DAYS if train_days is None else train_days
        return _rolling_daily_folds(ts, train_days=days, purge_ms=purge_ms)
    _validate_inputs(ts.size, n_splits, purge_ms, embargo_ms, scheme)
    order = np.argsort(ts, kind="stable")
    ordered_ts = ts[order]
    n_blocks = n_splits + 1 if scheme == "walk_forward" else n_splits
    bounds = _fold_bounds(ts.size, n_blocks)
    test_blocks = bounds[1:] if scheme == "walk_forward" else bounds
    folds: list[FoldArrays] = []
    for start, end in test_blocks:
        test_start = float(ordered_ts[start])
        test_end = float(ordered_ts[end - 1])
        purge_start = test_start - purge_ms
        embargo_end = test_end + embargo_ms
        # ordered_ts is sorted, so both train regions are contiguous prefixes/suffixes.
        before = int(np.searchsorted(ordered_ts, purge_start, side="left"))
        if scheme == "walk_forward":
            train_sorted = order[:before]
        else:
            after = int(np.searchsorted(ordered_ts, embargo_end, side="right"))
            train_sorted = np.concatenate((order[:before], order[after:]))
        folds.append(FoldArrays(
            train=train_sorted,
            test=order[start:end],
            test_start_ms=test_start,
            test_end_ms=test_end,
            purge_start_ms=purge_start,
            embargo_end_ms=embargo_end,
        ))
    return tuple(folds)


def temporal_splits(
    timestamps_ms: Sequence[float],
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
    scheme: CvScheme = "walk_forward",
) -> tuple[TemporalFold, ...]:
    """Tuple-valued wrapper around :func:`temporal_fold_arrays`."""
    return tuple(
        TemporalFold(
            train_indices=tuple(int(idx) for idx in fold.train.tolist()),
            test_indices=tuple(int(idx) for idx in fold.test.tolist()),
            test_start_ms=fold.test_start_ms,
            test_end_ms=fold.test_end_ms,
            purge_start_ms=fold.purge_start_ms,
            embargo_end_ms=fold.embargo_end_ms,
        )
        for fold in temporal_fold_arrays(
            timestamps_ms,
            n_splits=n_splits,
            purge_ms=purge_ms,
            embargo_ms=embargo_ms,
            scheme=scheme,
        )
    )


def walk_forward_splits(
    timestamps_ms: Sequence[float],
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
) -> tuple[TemporalFold, ...]:
    """Anchored walk-forward folds: every train row precedes its test window."""
    return temporal_splits(
        timestamps_ms,
        n_splits=n_splits,
        purge_ms=purge_ms,
        scheme="walk_forward",
    )


def purged_kfold_splits(
    timestamps_ms: Sequence[float],
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
) -> tuple[TemporalFold, ...]:
    """Purged k-fold with embargo; train rows may come from after the test window."""
    return temporal_splits(
        timestamps_ms,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        scheme="purged_kfold",
    )


# Backwards-compatible name. It always meant purged k-fold, which is why the new
# code spells the scheme out; keep the alias so older notebooks still import.
purged_walk_forward_splits = purged_kfold_splits


def _rolling_daily_folds(
    ts: npt.NDArray[np.float64],
    *,
    train_days: int,
    purge_ms: float,
) -> tuple[FoldArrays, ...]:
    if train_days < 1:
        raise ValueError("train_days must be >= 1")
    if purge_ms < 0.0:
        raise ValueError("purge_ms must be non-negative")
    if ts.size == 0:
        raise ValueError("need at least one row")
    order = np.argsort(ts, kind="stable")
    ordered = ts[order]
    days = np.unique(np.floor(ordered / DAY_MS))
    first_day = float(days[0])
    folds: list[FoldArrays] = []
    for day in days.tolist():
        if day - first_day < train_days:
            continue
        day_start = day * DAY_MS
        a = int(np.searchsorted(ordered, day_start, side="left"))
        b = int(np.searchsorted(ordered, day_start + DAY_MS, side="left"))
        purge_start = day_start - purge_ms
        lo = int(np.searchsorted(ordered, day_start - train_days * DAY_MS, side="left"))
        hi = int(np.searchsorted(ordered, purge_start, side="left"))
        if b <= a or hi <= lo:
            continue
        folds.append(FoldArrays(
            train=order[lo:hi],
            test=order[a:b],
            test_start_ms=float(ordered[a]),
            test_end_ms=float(ordered[b - 1]),
            purge_start_ms=purge_start,
            embargo_end_ms=float(ordered[b - 1]),
        ))
    if not folds:
        raise ValueError(
            f"rolling_daily needs more than {train_days} day(s) of data; "
            f"got {days.size} distinct day(s)"
        )
    return tuple(folds)


def _fold_bounds(total: int, n_blocks: int) -> list[tuple[int, int]]:
    base, extra = divmod(total, n_blocks)
    bounds: list[tuple[int, int]] = []
    start = 0
    for block in range(n_blocks):
        end = start + base + (1 if block < extra else 0)
        bounds.append((start, end))
        start = end
    return bounds


def _validate_inputs(
    n_rows: int,
    n_splits: int,
    purge_ms: float,
    embargo_ms: float,
    scheme: str,
) -> None:
    if scheme not in CV_SCHEMES:
        raise ValueError(f"scheme must be one of {', '.join(CV_SCHEMES)}")
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    n_blocks = n_splits + 1 if scheme == "walk_forward" else n_splits
    if n_rows < n_blocks:
        raise ValueError("need at least one row per split")
    if purge_ms < 0.0 or embargo_ms < 0.0:
        raise ValueError("purge_ms and embargo_ms must be non-negative")
