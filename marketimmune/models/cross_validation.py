"""Rolling daily walk-forward folds (fix B5; the scheme the v3 ladder pre-registered).

Each fold tests one whole UTC day ``d`` and trains on the ``train_days`` days before it,
ending ``purge_ms`` before ``d`` starts, so no training label reaches into the test day.
Days without a full ``train_days`` of history before them are never tested, and nothing
after the test day is ever used. Index arrays point into the caller's row order.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import numpy.typing as npt

from marketimmune.utils import DAY_MS as DAY_MS

CvScheme = Literal["rolling_daily"]
CV_SCHEMES: tuple[CvScheme, ...] = ("rolling_daily",)
DEFAULT_ROLLING_TRAIN_DAYS = 7
IndexArray = npt.NDArray[np.intp]


@dataclass(frozen=True, slots=True)
class FoldArrays:
    """One fold: train/test index arrays plus the test window and purge start (ms)."""

    train: IndexArray
    test: IndexArray
    test_start_ms: float
    test_end_ms: float
    purge_start_ms: float
    embargo_end_ms: float


def temporal_fold_arrays(
    timestamps_ms: npt.ArrayLike,
    *,
    purge_ms: float = 0.0,
    train_days: int | None = None,
    test_days: Collection[str] | None = None,
) -> tuple[FoldArrays, ...]:
    """Rolling daily folds; ties in time keep input order (stable sort). With ``test_days``
    (``YYYYMMDD``), only those days are tested; the others still train later folds."""
    days_back = DEFAULT_ROLLING_TRAIN_DAYS if train_days is None else train_days
    assert days_back >= 1 and purge_ms >= 0.0, f"{train_days=} {purge_ms=}"
    ts = np.asarray(timestamps_ms, dtype=np.float64)
    assert ts.size, "need at least one row"
    order = np.argsort(ts, kind="stable")
    ordered = ts[order]
    days = np.unique(np.floor(ordered / DAY_MS))
    first_day = float(days[0])
    folds: list[FoldArrays] = []
    for day in days.tolist():
        if day - first_day < days_back:
            continue
        if test_days is not None and datetime.fromtimestamp(day * DAY_MS / 1000.0, UTC).strftime("%Y%m%d") not in test_days:
            continue
        day_start = day * DAY_MS
        a, b, lo, hi = np.searchsorted(ordered, (day_start, day_start + DAY_MS, day_start - days_back * DAY_MS, day_start - purge_ms))
        if b <= a or hi <= lo:
            continue
        folds.append(
            FoldArrays(
                train=order[lo:hi],
                test=order[a:b],
                test_start_ms=float(ordered[a]),
                test_end_ms=float(ordered[b - 1]),
                purge_start_ms=day_start - purge_ms,
                embargo_end_ms=float(ordered[b - 1]),
            )
        )
    assert folds, f"rolling_daily needs more than {days_back} day(s) of data; got {days.size} distinct day(s)"
    return tuple(folds)
