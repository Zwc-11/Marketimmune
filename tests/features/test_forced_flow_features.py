"""Tests for the forced-flow forecast columns (plan L3b)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketimmune.features.forced_flow_features import (
    FORECAST_FEATURE_COLUMNS,
    GRID_INPUTS,
    forecast_features,
    verify_forecast_features_no_lookahead,
)


def _grid() -> dict[str, np.ndarray]:
    ts = np.array([10_000.0, 20_000.0, 30_000.0])
    g = {c: np.zeros(3) for c in GRID_INPUTS}
    g["ts_ms"] = ts
    g["F_bid_15s"] = np.array([1.0, 2.0, 3.0])
    g["F_ask_15s"] = np.array([10.0, 20.0, 30.0])
    g["P_bid_5s"] = np.array([0.1, 0.2, 0.3])
    g["heatmap_ask_1pct"] = np.array([5.0, 6.0, 7.0])
    return g


def test_strictly_before_and_maker_relative() -> None:
    f = forecast_features(np.array([20_000.0, 20_001.0, 25_000.0, 5_000.0, 400_000.0]), np.array([1.0, 1.0, -1.0, 1.0, 1.0]), _grid())
    assert set(f) == set(FORECAST_FEATURE_COLUMNS)
    # a fill at exactly 20000 uses the 10000 row, not its own grid time
    assert f["fc_same_15s"][0] == 1.0 and f["fc_opp_15s"][0] == 10.0
    assert f["fc_same_15s"][1] == 2.0 and f["fc_p_same_5s"][1] == pytest.approx(0.2)
    # maker on the ask: forced buys (F_ask) are the same side
    assert f["fc_same_15s"][2] == 20.0 and f["fc_opp_15s"][2] == 2.0
    assert f["fc_heat_same_1pct"][2] == 6.0
    # before the first row, or more than 120 s after the last: missing
    assert math.isnan(f["fc_same_15s"][3]) and math.isnan(f["fc_same_15s"][4])


def test_no_lookahead_check_and_empty_grid() -> None:
    t = np.linspace(0.0, 40_000.0, 50)
    side = np.where(np.arange(50) % 2 == 0, 1.0, -1.0)
    rep = verify_forecast_features_no_lookahead(t, side, _grid())
    assert rep["passed"] and rep["n_checked"] == 50 and rep["rows_with_forecast"] > 0
    f = forecast_features(t, side, {c: np.zeros(0) for c in GRID_INPUTS})
    assert np.isnan(f["fc_same_60s"]).all()
