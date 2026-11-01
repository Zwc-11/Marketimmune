"""Tests for the rolling daily walk-forward folds (fix B5)."""

from __future__ import annotations

import numpy as np
import pytest

from marketimmune.models.cross_validation import DAY_MS, temporal_fold_arrays


def _days(n_days: int, per_day: int = 4) -> list[float]:
    return [d * DAY_MS + i * DAY_MS / per_day for d in range(n_days) for i in range(per_day)]


def test_rolling_daily_trains_only_on_the_window_before_each_test_day() -> None:
    ts = _days(6)
    folds = temporal_fold_arrays(ts, train_days=2, purge_ms=60_000.0)
    assert len(folds) == 4  # days 2..5; days 0 and 1 lack two days of history
    for fold in folds:
        day_start = fold.test_start_ms
        assert all(day_start <= ts[i] < day_start + DAY_MS for i in fold.test)
        assert all(day_start - 2 * DAY_MS <= ts[i] < day_start - 60_000.0 for i in fold.train)
        assert len(fold.train) == 8 and len(fold.test) == 4


def test_rolling_daily_keeps_the_callers_row_order_and_ties() -> None:
    ts = list(reversed(_days(3, per_day=2))) + [DAY_MS * 2.0]
    (fold,) = temporal_fold_arrays(ts, train_days=2)
    assert [ts[i] for i in fold.test] == [2 * DAY_MS, 2 * DAY_MS, 2.5 * DAY_MS]
    assert fold.test.tolist() == [1, 6, 0]  # time order, ties in input order


def test_rolling_daily_default_window_and_too_little_data() -> None:
    assert len(temporal_fold_arrays(_days(9))) == 2  # default 7-day window
    with pytest.raises(AssertionError, match="more than 7 day"):
        temporal_fold_arrays(_days(3))
    for bad in ({"train_days": 0}, {"purge_ms": -1.0}):
        with pytest.raises(AssertionError):
            temporal_fold_arrays(_days(3), **bad)
    with pytest.raises(AssertionError, match="at least one row"):
        temporal_fold_arrays([], train_days=1)


def test_rolling_daily_skips_gap_days() -> None:
    ts = [t for t in _days(5) if not (2 * DAY_MS <= t < 3 * DAY_MS)]
    folds = temporal_fold_arrays(ts, train_days=1)
    # day 2 is empty (no test rows) and day 3's one-day window is empty (no train rows)
    assert [int(f.test_start_ms // DAY_MS) for f in folds] == [1, 4]


def test_rolling_daily_tests_only_the_given_days() -> None:
    ts = np.repeat(np.arange(10) * DAY_MS, 3).astype(np.float64)  # 1970-01-01 to 01-10
    all_folds = temporal_fold_arrays(ts, train_days=2)
    picked = temporal_fold_arrays(ts, train_days=2, test_days={"19700104", "19700110"})
    assert [f.test_start_ms for f in picked] == [3 * DAY_MS, 9 * DAY_MS]
    by_start = {f.test_start_ms: f for f in all_folds}
    assert all(np.array_equal(f.train, by_start[f.test_start_ms].train) for f in picked)
