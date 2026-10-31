"""Plan rung L3b: the forced-flow forecast as ladder columns.

``cli.forced_forecast`` writes a grid of forecasts (default every 10 s), each made
from information strictly before its grid time: fills before ``t`` for the
position book, mids before ``t``, Binance trades at or before ``t - latency``, and
a liquidation-distance prior, hazard scale and impact fitted on earlier days. A
fill takes the last grid row strictly before it, so a forecast is at most one
grid step old; a row older than ``max_age_ms`` (a missing day) gives NaN.

Sides are from the maker's view, as in ``features.order_events``: a maker filled
on its bid (``maker_side = +1``) is hit by forced sells, which is the forecast's
bid side, so "same" is ``F_bid`` for ``maker_side = +1`` and ``F_ask`` for ``-1``.

Columns, per horizon ``h`` in 5 / 15 / 60 s:

* ``fc_same_<h>s``, ``fc_opp_<h>s``: expected forced notional (USD) per side;
* ``fc_p_same_<h>s``, ``fc_p_opp_<h>s``: probability that a book slice of at
  least 10k USD is forced on that side within ``h``;

plus ``fc_heat_same_1pct``, ``fc_heat_opp_1pct``: notional with a point
liquidation price within 1% of the mark (the static heatmap).

The grid file also holds realised outcomes (``real_*``, ``onset_*``); only the
forecast columns are ever read here (``GRID_INPUTS``).
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
FORECAST_HORIZONS_S = (5, 15, 60)
DEFAULT_MAX_AGE_MS = 120_000.0


def grid_inputs(horizons_s: Sequence[int] = FORECAST_HORIZONS_S) -> tuple[str, ...]:
    cols = ["ts_ms"]
    for h in horizons_s:
        cols += [f"F_bid_{h}s", f"F_ask_{h}s", f"P_bid_{h}s", f"P_ask_{h}s"]
    return (*cols, "heatmap_bid_1pct", "heatmap_ask_1pct")


def forecast_feature_columns(horizons_s: Sequence[int] = FORECAST_HORIZONS_S) -> tuple[str, ...]:
    cols: list[str] = []
    for h in horizons_s:
        cols += [f"fc_same_{h}s", f"fc_opp_{h}s", f"fc_p_same_{h}s", f"fc_p_opp_{h}s"]
    return (*cols, "fc_heat_same_1pct", "fc_heat_opp_1pct")


GRID_INPUTS = grid_inputs()
FORECAST_FEATURE_COLUMNS = forecast_feature_columns()


def forecast_features(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    grid: Mapping[str, npt.ArrayLike],
    *,
    horizons_s: Sequence[int] = FORECAST_HORIZONS_S,
    max_age_ms: float = DEFAULT_MAX_AGE_MS,
) -> dict[str, FloatArray]:
    """As-of join of the forecast grid to fills, strictly before each fill."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    gts = np.asarray(grid["ts_ms"], dtype=np.float64)
    order = np.argsort(gts, kind="stable")
    gts = gts[order]
    j = np.searchsorted(gts, t, side="left") - 1
    ok = j >= 0
    ok[ok] &= t[ok] - gts[j[ok]] <= max_age_ms
    jj = np.maximum(j, 0)
    bid_same = side > 0

    def pick(bid_col: str, ask_col: str) -> tuple[FloatArray, FloatArray]:
        b = np.asarray(grid[bid_col], dtype=np.float64)[order][jj] if gts.size else np.zeros(t.size)
        a = np.asarray(grid[ask_col], dtype=np.float64)[order][jj] if gts.size else np.zeros(t.size)
        same = np.where(ok, np.where(bid_same, b, a), np.nan)
        opp = np.where(ok, np.where(bid_same, a, b), np.nan)
        return same, opp

    out: dict[str, FloatArray] = {}
    for h in horizons_s:
        out[f"fc_same_{h}s"], out[f"fc_opp_{h}s"] = pick(f"F_bid_{h}s", f"F_ask_{h}s")
        out[f"fc_p_same_{h}s"], out[f"fc_p_opp_{h}s"] = pick(f"P_bid_{h}s", f"P_ask_{h}s")
    out["fc_heat_same_1pct"], out["fc_heat_opp_1pct"] = pick("heatmap_bid_1pct",
                                                             "heatmap_ask_1pct")
    return out


def empty_grid(horizons_s: Sequence[int] = FORECAST_HORIZONS_S) -> dict[str, FloatArray]:
    return {c: np.zeros(0) for c in grid_inputs(horizons_s)}


def verify_forecast_features_no_lookahead(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    grid: Mapping[str, npt.ArrayLike],
    *,
    sample: int = 500,
    seed: int = 0,
) -> dict[str, Any]:
    """Recompute sampled fills' features with every grid row at or after the fill
    deleted; any difference means a forecast from the fill's time or later leaked."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    full = forecast_features(t, side, grid)
    gts = np.asarray(grid["ts_ms"], dtype=np.float64)
    rows = list(range(t.size))
    random.Random(seed).shuffle(rows)
    mismatched = 0
    for i in rows[:sample]:
        keep = gts < t[i]
        cut = {k: np.asarray(v, dtype=np.float64)[keep] for k, v in grid.items()}
        part = forecast_features(t[i: i + 1], side[i: i + 1], cut)
        for name, values in part.items():
            a, b = values[0], full[name][i]
            if not (a == b or (np.isnan(a) and np.isnan(b))):
                mismatched += 1
                break
    n = min(sample, t.size)
    return {"passed": mismatched == 0, "n_checked": n, "n_mismatched": mismatched,
            "rows_with_forecast": int(np.sum(~np.isnan(full["fc_same_15s"])))
            if "fc_same_15s" in full else 0}
