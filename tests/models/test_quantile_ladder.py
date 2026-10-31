"""Tests for the quantile ladder (v3 detector model)."""

from __future__ import annotations

import numpy as np
import pytest

from marketimmune.models.cross_validation import DAY_MS
from marketimmune.models.quantile_ladder import (
    lightgbm_factory,
    pinball_loss,
    quantile_column,
    quantile_report,
    train_quantile_oof,
)


class TrainQuantile:
    """Predicts the training quantile (climatology) plus ``bias``."""

    def __init__(self, tau: float, bias: float = 0.0) -> None:
        self.tau, self.bias, self.value = tau, bias, 0.0

    def fit(self, x: np.ndarray, y: np.ndarray) -> TrainQuantile:
        self.value = float(np.quantile(y, self.tau))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value + self.bias)


def _days(n_days: int = 4, per_day: int = 50) -> np.ndarray:
    return np.repeat(np.arange(n_days), per_day) * DAY_MS + np.tile(
        np.linspace(0, DAY_MS * 0.9, per_day), n_days
    )


def test_pinball_and_column_names() -> None:
    assert pinball_loss([2.0, 0.0], [1.0, 1.0], 0.9).tolist() == pytest.approx([0.9, 0.1])
    assert quantile_column(0.1) == "q10" and quantile_column(0.95) == "q95"
    with pytest.raises(ValueError, match="tau"):
        pinball_loss([1.0], [1.0], 1.0)


def test_oof_uses_rolling_folds_and_matches_climatology() -> None:
    ts = _days()
    rng = np.random.default_rng(0)
    y = rng.normal(size=ts.size)
    oof = train_quantile_oof(
        np.zeros((ts.size, 1)), y, ts, factory=lambda tau, seed: TrainQuantile(tau),
        train_days=2, purge_ms=0.0,
    )
    assert oof.tested.sum() == 100 and not oof.tested[:100].any()  # days 2 and 3 tested
    assert [f["n_train"] for f in oof.fold_summaries] == [100, 100]
    np.testing.assert_allclose(oof.predictions[0.5][oof.tested], oof.climatology[0.5][oof.tested])
    report = quantile_report(oof, y)
    assert report["per_tau"]["q50"]["skill"] == pytest.approx(0.0)
    assert 0.5 < report["interval"]["coverage"] < 1.0


def test_crossing_quantiles_are_sorted() -> None:
    ts = _days()
    bias = {0.1: 5.0, 0.5: 0.0, 0.9: -5.0}  # q10 above q90 before rearrangement
    oof = train_quantile_oof(
        np.zeros((ts.size, 1)), np.arange(ts.size, dtype=float), ts,
        factory=lambda tau, seed: TrainQuantile(tau, bias[tau]), train_days=2,
    )
    t = oof.tested
    assert np.all(oof.predictions[0.1][t] <= oof.predictions[0.5][t])
    assert np.all(oof.predictions[0.5][t] <= oof.predictions[0.9][t])


def test_validation_and_empty_report() -> None:
    ts = _days()
    with pytest.raises(ValueError, match="same number of rows"):
        train_quantile_oof(np.zeros((3, 1)), [1.0], ts)
    with pytest.raises(ValueError, match="tau"):
        train_quantile_oof(np.zeros((ts.size, 1)), np.zeros(ts.size), ts, taus=(0.0,))
    oof = train_quantile_oof(
        np.zeros((ts.size, 1)), np.zeros(ts.size), ts, taus=(0.5,),
        factory=lambda tau, seed: TrainQuantile(tau), train_days=2,
    )
    assert "interval" not in quantile_report(oof, np.zeros(ts.size))
    assert quantile_report(oof, np.full(ts.size, np.nan)) == {"rows_tested": 0, "per_tau": {}}


def test_lightgbm_learns_a_signal() -> None:
    pytest.importorskip("lightgbm")
    ts = _days(4, 400)
    rng = np.random.default_rng(1)
    x = rng.normal(size=(ts.size, 2))
    y = 3.0 * x[:, 0] + rng.normal(scale=0.5, size=ts.size)
    oof = train_quantile_oof(
        x, y, ts, factory=lightgbm_factory(n_estimators=60, min_child_samples=20), train_days=2
    )
    skill = quantile_report(oof, y)["per_tau"]["q50"]["skill"]
    assert skill > 0.5
