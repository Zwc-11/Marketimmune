"""Tests for the margin-free forced-flow forecaster."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.cli import forced_forecast
from marketimmune.forced.forecaster import (
    PositionBook,
    brier_decomposition,
    conditional_median_distance,
    ewma_sigma_1s,
    forced_impact_samples,
    forecast_forced_flow,
    impact_slope,
    liquidation_distances,
    realised_forced_notional,
    trigger_probability,
)


def test_conditional_median_distance_respects_survival() -> None:
    d = np.array([0.02, 0.025, 0.03, 0.05])
    got = conditional_median_distance(d, np.array([0.0, 0.026, 0.06]))
    assert got[0] == pytest.approx(0.025) and got[1] == pytest.approx(0.03)
    assert math.isnan(got[2])


def test_trigger_probability_reflection_and_crossed() -> None:
    p = trigger_probability(np.array([-0.01, 0.0, 0.002]), np.array([0.001] * 3), 4.0)
    assert p[0] == pytest.approx(2 * 0.5 * math.erfc(5 / math.sqrt(2)), rel=1e-6)
    assert p[1] == 1.0 and p[2] == 1.0


def test_forecast_sides_slices_scale_and_heatmap() -> None:
    deltas = np.array([0.025] * 9)
    book = PositionBook(size=np.array([10.0, -2000.0, 5.0, 1.0]), entry=np.array([100.0, 100.0, np.nan, 100.0]))
    # mark 97.6: the 10-unit long has lost 2.4% and its liquidation at 97.5 is close
    f = forecast_forced_flow(book, 97.6, 0.001, deltas, [15.0])
    assert f["F_bid_15s"] > 0.0 and f["F_ask_15s"] == pytest.approx(0.0, abs=1e-6)
    assert f["heatmap_bid_1pct"] == pytest.approx(11 * 97.6)
    assert 0.0 < f["P_any_15s"] <= 1.0
    half = forecast_forced_flow(book, 97.6, 0.001, deltas, [15.0], {15.0: 0.5})
    assert half["F_bid_15s"] == pytest.approx(0.5 * f["F_bid_15s"], rel=1e-6)
    # the short (2000 x ~102 = 205k USD) is liquidated in 20% slices
    up = forecast_forced_flow(book, 102.45, 0.001, deltas, [15.0])
    pi = trigger_probability(np.array([math.log(102.45 / 102.5)]), np.array([0.001]), 15.0)[0]
    assert up["F_ask_15s"] == pytest.approx(0.2 * 2000 * 102.45 * pi, rel=1e-6)
    # survived past every sampled distance: not a max-leverage position, no hazard
    beyond = forecast_forced_flow(book, 102.6, 0.001, deltas, [15.0])
    assert beyond["F_ask_15s"] == 0.0
    empty = forecast_forced_flow(PositionBook(np.zeros(0), np.zeros(0)), 100.0, 0.001, deltas, [5.0])
    assert set(empty.values()) == {0.0}
    assert {"F_bid_5s", "Fraw_ask_5s", "P_bid_5s", "cascade_5s", "heatmap_bid_1pct"} <= set(empty)


def test_raw_binary_and_cascade_pass() -> None:
    deltas = np.array([0.025] * 9)
    book = PositionBook(size=np.array([10.0, 500.0, -3.0]), entry=np.array([100.0] * 3))
    base = forecast_forced_flow(book, 97.6, 0.001, deltas, [15.0], {15.0: 0.5}, binary_usd=10_000.0)
    # raw is the unscaled first pass; scaled F is half of it (no probability capped)
    assert base["Fraw_bid_15s"] == pytest.approx(2.0 * base["F_bid_15s"], rel=1e-9)
    assert base["cascade_15s"] == 0.0
    # only the 500-unit long (48.8k USD) is at least 10k USD: P_bid is its trigger probability
    pi = trigger_probability(np.array([math.log(97.5 / 97.6)]), np.array([0.001]), 15.0)[0]
    assert base["P_bid_15s"] == pytest.approx(0.5 * pi, rel=1e-9)
    assert base["P_ask_15s"] == 0.0
    # forced selling pushes the mark down: the second pass forecasts more long flow
    casc = forecast_forced_flow(book, 97.6, 0.001, deltas, [15.0], {15.0: 0.5}, impact_bps_per_musd=1_000.0)
    assert casc["F_bid_15s"] > base["F_bid_15s"]
    assert casc["cascade_15s"] == pytest.approx(casc["F_bid_15s"] + casc["F_ask_15s"] - base["F_bid_15s"] - base["F_ask_15s"])
    assert casc["Fraw_bid_15s"] == base["Fraw_bid_15s"]


def test_impact_samples_and_slope() -> None:
    mid_ts = np.array([0.0, 1_000.0, 1_500.0, 3_000.0, 3_500.0])
    mid = np.array([100.0, 100.0, 99.0, 99.0, 99.5])
    # one forced sell block at t=1000 (two orders), one forced buy at t=3000
    x, y = forced_impact_samples(
        np.array([1_000.0, 1_000.0, 3_000.0]), np.array([True, True, False]), np.array([400.0, 600.0, 500.0]), mid_ts, mid
    )
    assert x.tolist() == [-1_000.0, 500.0]
    assert y[0] == pytest.approx(1e4 * math.log(0.99))  # mid before t vs last mid by t+1s
    assert y[1] == pytest.approx(1e4 * math.log(99.5 / 99.0))
    slope = impact_slope(x, y)
    xm = x / 1e6
    assert slope == pytest.approx(float(xm @ y / (xm @ xm)))
    assert impact_slope(np.zeros(0), np.zeros(0)) is None
    assert forced_impact_samples(np.zeros(0), np.zeros(0, bool), np.zeros(0), mid_ts, mid)[0].size == 0


def test_sigma_realised_flow_and_brier() -> None:
    ts = np.arange(0, 120_000, 500.0)
    mid = 100.0 * np.exp(np.cumsum(np.full(ts.size, 1e-4)))
    sig = ewma_sigma_1s(ts, mid, np.array([500.0, 60_000.0]))
    assert math.isnan(sig[0]) and sig[1] == pytest.approx(2e-4, rel=0.05)
    assert math.isnan(ewma_sigma_1s(ts[:1], mid[:1], np.array([1000.0]))[0])
    bid, ask = realised_forced_notional(
        np.array([1000.0, 2000.0, 9000.0]), np.array([True, False, True]), np.array([5.0, 7.0, 11.0]), np.array([0.0, 1000.0]), 5.0
    )
    assert bid.tolist() == [5.0, 0.0] and ask.tolist() == [7.0, 7.0]  # window is (t, t+h]
    dec = brier_decomposition(np.array([0.1, 0.1, 0.9, 0.9]), np.array([0.0, 0.0, 1.0, 1.0]))
    assert dec["brier"] == pytest.approx(0.01) and dec["uncertainty"] == pytest.approx(0.25)
    assert dec["brier"] == pytest.approx(dec["reliability"] - dec["resolution"] + dec["uncertainty"])


def test_liquidation_distances_from_positions() -> None:
    rows = pd.DataFrame(
        {
            "wallet": ["a", "a", "b"],
            "ts_ms": [1, 2, 3],
            "seq": [0, 1, 2],
            "start_pos": [0.0, 2.0, 0.0],
            "px": [100.0, 97.5, 50.0],
            "entry_px_after": [100.0, np.nan, 50.0],
            "forced": [False, True, True],
        }
    )
    assert liquidation_distances(rows).tolist() == pytest.approx([0.025])


def test_cli_needs_three_dates(tmp_path: Path) -> None:
    out = forced_forecast.build(forced_forecast.parse_args(["--lake-root", str(tmp_path)]))
    assert "skipped" in out


def test_onsets_need_a_quiet_minute_and_land_on_the_grid() -> None:
    ts = np.array([10_000.0, 10_000.0, 30_000.0, 95_000.0, 200_000.0])
    on = forced_forecast.onset_times(ts)
    assert on.tolist() == [10_000.0, 95_000.0, 200_000.0]
    grid = np.array([0.0, 10_000.0, 90_000.0, 190_000.0])
    got = forced_forecast.onsets_on_grid(on, grid, 10.0)
    # 10000 falls in (0, 10000]; 95000 in (90000, 100000]; 200000 in (190000, 200000]
    assert got[0] == 10_000.0 and math.isnan(got[1])
    assert got[2] == 95_000.0 and got[3] == 200_000.0
