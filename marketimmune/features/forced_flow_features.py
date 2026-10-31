"""Plan rung L3b: the forced-flow forecast as ladder columns.

``cli.forced_forecast`` writes a grid of forecasts (every 10 s), each made from information
strictly before its grid time. A fill takes the last grid row strictly before it, so a forecast
is at most one grid step old; a row older than ``MAX_AGE_MS`` (a missing day) gives NaN.

Sides are from the maker's view, as in ``features.order_events``: a maker filled on its bid
(``maker_side = +1``) is hit by forced sells, the forecast's bid side, so "same" is ``F_bid``
for ``maker_side = +1`` and ``F_ask`` for ``-1``. Columns, per horizon ``h`` in 5 / 15 / 60 s:

* ``fc_same_<h>s``, ``fc_opp_<h>s``: expected forced notional (USD) per side;
* ``fc_p_same_<h>s``, ``fc_p_opp_<h>s``: probability that a book slice of at least 10k USD is
  forced on that side within ``h``;

plus ``fc_heat_same_1pct``, ``fc_heat_opp_1pct``: notional with a point liquidation price within
1% of the mark (the static heatmap). Only the forecast columns of the grid are read
(``GRID_INPUTS``), never its realised outcomes.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
FORECAST_HORIZONS_S = (5, 15, 60)
MAX_AGE_MS = 120_000.0
# (grid bid column, grid ask column, same-side feature, opposite-side feature)
_PAIRS = (
    *(
        pair
        for h in FORECAST_HORIZONS_S
        for pair in (
            (f"F_bid_{h}s", f"F_ask_{h}s", f"fc_same_{h}s", f"fc_opp_{h}s"),
            (f"P_bid_{h}s", f"P_ask_{h}s", f"fc_p_same_{h}s", f"fc_p_opp_{h}s"),
        )
    ),
    ("heatmap_bid_1pct", "heatmap_ask_1pct", "fc_heat_same_1pct", "fc_heat_opp_1pct"),
)
GRID_INPUTS = ("ts_ms", *(c for pair in _PAIRS for c in pair[:2]))
FORECAST_FEATURE_COLUMNS = tuple(c for pair in _PAIRS for c in pair[2:])


def forecast_features(fill_ts_ms: npt.ArrayLike, maker_side: npt.ArrayLike, grid: Mapping[str, npt.ArrayLike]) -> dict[str, FloatArray]:
    """As-of join of the forecast grid to fills, strictly before each fill."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    gts = np.asarray(grid["ts_ms"], dtype=np.float64)
    if gts.size == 0:  # dates before the hazard scale exists have no grid
        return {c: np.full(t.size, np.nan) for c in FORECAST_FEATURE_COLUMNS}
    order = np.argsort(gts, kind="stable")
    gts = gts[order]
    j = np.searchsorted(gts, t, side="left") - 1
    ok = j >= 0
    ok[ok] &= t[ok] - gts[j[ok]] <= MAX_AGE_MS
    rows = order[np.maximum(j, 0)]
    bid_same = np.asarray(maker_side, dtype=np.float64) > 0
    out: dict[str, FloatArray] = {}
    for bid_col, ask_col, same, opp in _PAIRS:
        b = np.asarray(grid[bid_col], dtype=np.float64)[rows]
        a = np.asarray(grid[ask_col], dtype=np.float64)[rows]
        out[same] = np.where(ok, np.where(bid_same, b, a), np.nan)
        out[opp] = np.where(ok, np.where(bid_same, a, b), np.nan)
    return out


def verify_forecast_features_no_lookahead(
    fill_ts_ms: npt.ArrayLike, maker_side: npt.ArrayLike, grid: Mapping[str, npt.ArrayLike], *, sample: int = 500, seed: int = 0
) -> dict[str, Any]:
    """Recompute sampled fills' features with every grid row at or after the fill deleted; any
    difference means a forecast from the fill's time or later leaked."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    full = forecast_features(t, side, grid)
    gts = np.asarray(grid["ts_ms"], dtype=np.float64)
    rows = list(range(t.size))
    random.Random(seed).shuffle(rows)
    mismatched = 0
    for i in rows[:sample]:
        keep = gts < t[i]
        part = forecast_features(t[i : i + 1], side[i : i + 1], {k: np.asarray(v, dtype=np.float64)[keep] for k, v in grid.items()})
        mismatched += int(any(not (v[0] == full[c][i] or (np.isnan(v[0]) and np.isnan(full[c][i]))) for c, v in part.items()))
    return {
        "passed": mismatched == 0,
        "n_checked": min(sample, t.size),
        "n_mismatched": mismatched,
        "rows_with_forecast": int(np.sum(~np.isnan(full["fc_same_15s"]))),
    }
