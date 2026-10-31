"""Tests for the day-level rung comparison."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketimmune.models.compare import (
    brier_loss,
    compare_rungs,
    daily_means,
    diebold_mariano,
    log_loss,
    newey_west_lag,
    stationary_bootstrap_ci,
    stationary_bootstrap_indices,
)


def test_losses_and_daily_means() -> None:
    assert brier_loss([1, 0], [0.75, 0.25]).tolist() == [0.0625, 0.0625]
    assert log_loss([1], [1.0])[0] == pytest.approx(-math.log(1 - 1e-6))
    keys, means, counts = daily_means([1.0, 3.0, 5.0], ["b", "a", "a"])
    assert keys == ["a", "b"] and means.tolist() == [4.0, 1.0] and counts.tolist() == [2, 1]


def test_diebold_mariano_detects_a_consistent_improvement() -> None:
    rng = np.random.default_rng(0)
    d = 0.01 + rng.normal(scale=0.005, size=25)
    res = diebold_mariano(d)
    assert res.n == 25 and res.lag == newey_west_lag(25) == 2
    assert res.t_stat > 5 and res.p_value < 1e-4
    flat = diebold_mariano(rng.normal(scale=0.005, size=25))
    assert flat.p_value > 0.01
    assert diebold_mariano([0.0, 0.0, 0.0]).t_stat == 0.0
    assert diebold_mariano([1.0, 1.0, 1.0]).t_stat == math.inf
    with pytest.raises(AssertionError, match="3 days"):
        diebold_mariano([1.0, 2.0])
    with pytest.raises(AssertionError, match="NaN"):
        diebold_mariano([1.0, 2.0, np.nan])


def test_stationary_bootstrap_ci_brackets_the_mean() -> None:
    d = np.linspace(0.0, 2.0, 30)
    lo, hi = stationary_bootstrap_ci(d, n_boot=2000)
    assert lo < 1.0 < hi
    with pytest.raises(AssertionError, match="n=0"):
        stationary_bootstrap_ci([])
    with pytest.raises(AssertionError, match="mean_block"):
        stationary_bootstrap_ci([1.0], mean_block=0.5)


def test_bootstrap_indices_follow_blocks() -> None:
    idx = stationary_bootstrap_indices(10, 50, 3.0, np.random.default_rng(0))
    assert idx.shape == (50, 10) and idx.min() >= 0 and idx.max() < 10
    steps = (idx[:, 1:] - idx[:, :-1]) % 10
    assert 0.5 < float(np.mean(steps == 1)) < 0.8  # a block continues with probability 2/3
    assert np.array_equal(stationary_bootstrap_indices(1, 3, 1.0, np.random.default_rng(1)), np.zeros((3, 1), dtype=np.int64))


def test_compare_rungs_overall_and_by_regime() -> None:
    rng = np.random.default_rng(1)
    days = np.repeat([f"202512{d:02d}" for d in range(1, 6)], 200)
    y = rng.random(days.size) < 0.4
    good = np.clip(np.where(y, 0.7, 0.3) + rng.normal(scale=0.1, size=y.size), 0.01, 0.99)
    weak = np.full(y.size, 0.4)
    regime = np.arange(y.size) % 2 == 0
    out = compare_rungs(days, y, weak, good, regimes={"even": regime, "never": regime & False})
    assert out["all"]["days"] == 5 and out["all"]["days_improved"] == 5
    assert out["all"]["diebold_mariano"]["t_stat"] > 0
    lo, _hi = out["all"]["bootstrap_ci_95"]
    assert lo > 0
    assert out["even"]["rows"] == 500 and out["never"] == {"rows": 0}
    short = compare_rungs(days[:200], y[:200], weak[:200], good[:200], loss="log")
    assert "diebold_mariano" not in short["all"] and short["loss"] == "log"
    with pytest.raises(AssertionError, match="hinge"):
        compare_rungs(days, y, weak, good, loss="hinge")


def test_compare_rungs_pinball() -> None:
    days = np.repeat(["20251201", "20251202", "20251203"], 100)
    rng = np.random.default_rng(2)
    y = rng.normal(size=days.size)
    out = compare_rungs(days, y, np.full(y.size, 2.0), np.full(y.size, -1.28), loss="pinball", tau=0.1)
    assert out["loss"] == "pinball" and out["tau"] == 0.1
    assert out["all"]["days_improved"] == 3
