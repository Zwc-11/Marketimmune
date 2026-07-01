"""Purged and embargoed walk-forward cross-validation splits."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemporalFold:
    """One temporal split: train indices never overlap the test window."""

    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    test_start_ms: float
    test_end_ms: float
    purge_start_ms: float
    embargo_end_ms: float


def purged_walk_forward_splits(
    timestamps_ms: Sequence[float],
    *,
    n_splits: int = 5,
    purge_ms: float = 0.0,
    embargo_ms: float = 0.0,
) -> tuple[TemporalFold, ...]:
    """Create contiguous temporal test folds with purge + post-test embargo.

    Rows are sorted by timestamp, but returned indices refer to the original input.
    Train rows are excluded when their timestamp falls in
    ``[test_start - purge_ms, test_end + embargo_ms]``.
    """
    _validate_inputs(timestamps_ms, n_splits, purge_ms, embargo_ms)
    ordered = sorted(enumerate(timestamps_ms), key=lambda item: (item[1], item[0]))
    folds: list[TemporalFold] = []
    for start, end in _fold_bounds(len(ordered), n_splits):
        test = ordered[start:end]
        test_start = float(test[0][1])
        test_end = float(test[-1][1])
        purge_start = test_start - purge_ms
        embargo_end = test_end + embargo_ms
        train_indices = tuple(
            idx for idx, ts in ordered if float(ts) < purge_start or float(ts) > embargo_end
        )
        folds.append(TemporalFold(
            train_indices=train_indices,
            test_indices=tuple(idx for idx, _ts in test),
            test_start_ms=test_start,
            test_end_ms=test_end,
            purge_start_ms=purge_start,
            embargo_end_ms=embargo_end,
        ))
    return tuple(folds)


def _fold_bounds(total: int, n_splits: int) -> list[tuple[int, int]]:
    base, extra = divmod(total, n_splits)
    bounds: list[tuple[int, int]] = []
    start = 0
    for fold in range(n_splits):
        size = base + (1 if fold < extra else 0)
        end = start + size
        bounds.append((start, end))
        start = end
    return bounds


def _validate_inputs(
    timestamps_ms: Sequence[float],
    n_splits: int,
    purge_ms: float,
    embargo_ms: float,
) -> None:
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if len(timestamps_ms) < n_splits:
        raise ValueError("need at least one row per split")
    if purge_ms < 0.0 or embargo_ms < 0.0:
        raise ValueError("purge_ms and embargo_ms must be non-negative")
