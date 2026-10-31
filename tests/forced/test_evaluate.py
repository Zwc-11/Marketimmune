"""Tests for the forced-flow forecaster's evaluation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketimmune.forced.evaluate import (
    assign_bins,
    bin_edges,
    binned_map,
    evaluate_forecasts,
    lead_times,
    long_frame,
)


def test_bins_keep_zero_apart() -> None:
    s = np.array([0.0, 0.0, 1.0, 2.0, 3.0, 4.0])
    edges = bin_edges(s, n_bins=2)
    assert edges.tolist() == [2.5]
    assert assign_bins(np.array([0.0, 1.0, 2.6, 99.0]), edges).tolist() == [0, 1, 2, 2]
    assert bin_edges(np.zeros(3)).size == 0


def test_binned_map_uses_training_bins_only() -> None:
    train_s = np.array([0.0, 0.0, 1.0, 1.0, 5.0, 5.0])
    train_y = np.array([0.0, 0.0, 10.0, 20.0, 100.0, 300.0])
    got = binned_map(train_s, train_y, np.array([0.0, 1.0, 7.0]),
                     lambda v: float(v.mean()), n_bins=2)
    assert got.tolist() == [0.0, 15.0, 200.0]


def test_lead_time_counts_the_alarm_run() -> None:
    long = pd.DataFrame({"date": ["d"] * 5, "side": ["bid"] * 5,
                         "ts_ms": [0.0, 10_000.0, 20_000.0, 30_000.0, 40_000.0],
                         "onset_ms": [np.nan, np.nan, 25_000.0, np.nan, 45_000.0]})
    sig = np.array([0.0, 1.0, 1.0, 1.0, 0.0])
    lt = lead_times(long, sig, np.full(5, 0.5), grid_s=10.0)
    assert lt["hit"].tolist() == [True, False]
    # alarm on at t=10s and 20s; onset at 25s -> 15 s of warning
    assert lt["lead_s"].tolist() == [pytest.approx(15.0), 0.0]


def _frame(days: int = 4, n: int = 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts = []
    for d in range(days):
        heat = rng.exponential(1.0, n) * (rng.random(n) < 0.3)
        f_bid = heat * 1_000.0 + rng.exponential(10.0, n)
        real = np.where(rng.random(n) < 0.05 + 0.5 * (heat > 1.0), f_bid * 20.0, 0.0)
        ts = np.arange(n) * 10_000.0
        onset = np.where(real > 0, ts + 5_000.0, np.nan)
        part = pd.DataFrame({
            "date": f"2025120{d + 1}", "ts_ms": ts, "sigma_1s": rng.random(n) * 1e-4,
            "oi_long_usd": 1e6 - np.cumsum(real), "oi_short_usd": 1e6,
            "heatmap_bid_1pct": heat * 5e4, "heatmap_ask_1pct": 0.0,
            "F_bid_60s": f_bid, "F_ask_60s": 0.0, "P_bid_60s": np.minimum(f_bid / 2e4, 1.0),
            "P_ask_60s": 0.0, "real_bid_60s": real, "real_ask_60s": 0.0,
            "persist_bid_60s": np.roll(real, 1), "persist_ask_60s": 0.0,
            "onset_bid_ms": onset, "onset_ask_ms": np.nan,
            "cascade_60s": f_bid * 0.001,
        })
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def test_evaluate_report_shape_and_skill() -> None:
    frame = _frame()
    long = long_frame(frame, [60.0], 10.0)
    assert len(long) == 2 * len(frame) and long["sig_oi_change"].min() >= 0.0
    res = evaluate_forecasts(frame, [60.0], binary_usd=1_000.0)
    e = res["60s"]
    assert e["scored_days"] == 3  # the first day only trains the calibration
    # the model carries the heatmap's information plus noise; both beat climatology
    assert e["brier"]["model"]["brier"] < e["brier"]["climatology"]["brier"]
    assert e["brier"]["heatmap"]["brier"] < e["brier"]["climatology"]["brier"]
    assert "dm_t" in e["dm_brier"]["model_vs_heatmap"]["all"]
    assert set(e["pinball_q90"]) >= {"model", "model_raw", "model_persist", "zero", "heatmap"}
    assert "all" in e["dm_brier"]["model_persist_vs_persistence"]
    assert res["lead_time"]["model"]["onsets"] > 0
    assert res["cascade"]["60s"]["mean_relative_change"] == pytest.approx(0.001)


def test_flag_splits_bins_and_zero_signal_never_alarms() -> None:
    s = np.array([1.0, 1.0, 1.0, 1.0])
    y = np.array([0.0, 0.0, 10.0, 30.0])
    flag = np.array([False, False, True, True])
    got = binned_map(s, y, np.array([1.0, 1.0]), lambda v: float(v.mean()),
                     train_flag=flag, test_flag=np.array([False, True]))
    assert got.tolist() == [0.0, 20.0]
    long = pd.DataFrame({"date": ["d"] * 2, "side": ["bid"] * 2, "ts_ms": [0.0, 10_000.0],
                         "onset_ms": [np.nan, 15_000.0]})
    lt = lead_times(long, np.zeros(2), np.zeros(2), grid_s=10.0)
    assert lt["hit"].tolist() == [False]
