"""Tests for the quantile ladder (v3 detector model)."""

from __future__ import annotations

import numpy as np
import pytest
from lightgbm import LGBMRegressor

from marketimmune.models.compare import pinball_loss
from marketimmune.models.cross_validation import DAY_MS
from marketimmune.models.quantile_ladder import LgbParams, quantile_column, quantile_report, train_quantile_oof

SMALL = LgbParams(n_estimators=30, min_child_samples=20)


def _days(n_days: int = 4, per_day: int = 50) -> np.ndarray:
    return np.repeat(np.arange(n_days), per_day) * DAY_MS + np.tile(np.linspace(0, DAY_MS * 0.9, per_day), n_days)


def test_pinball_and_column_names() -> None:
    assert pinball_loss([2.0, 0.0], [1.0, 1.0], 0.9).tolist() == pytest.approx([0.9, 0.1])
    assert quantile_column(0.1) == "q10" and quantile_column(0.95) == "q95"
    with pytest.raises(AssertionError, match="tau"):
        pinball_loss([1.0], [1.0], 1.0)


def test_oof_uses_rolling_folds_climatology_and_no_crossing() -> None:
    ts = _days()
    rng = np.random.default_rng(0)
    y = rng.normal(size=ts.size)
    oof = train_quantile_oof(rng.normal(size=(ts.size, 2)), y, ts, params=SMALL, train_days=2, purge_ms=0.0)
    assert oof.tested.sum() == 100 and not oof.tested[:100].any()  # days 2 and 3 tested
    assert [f["n_train"] for f in oof.fold_summaries] == [100, 100]
    assert oof.climatology[0.5][100] == pytest.approx(float(np.quantile(y[:100], 0.5)))
    t = oof.tested
    assert np.all(oof.predictions[0.1][t] <= oof.predictions[0.5][t]) and np.all(oof.predictions[0.5][t] <= oof.predictions[0.9][t])
    report = quantile_report(oof, y)
    assert report["rows_tested"] == 100 and set(report["per_tau"]) == {"q10", "q50", "q90"} and "interval" in report


def test_shared_dataset_matches_the_sklearn_wrapper() -> None:
    """One binned Dataset per fold, reused across taus, gives the boosters the pre-registered
    ``LGBMRegressor`` settings give (then the no-crossing sort)."""
    ts = _days(2, 400)
    rng = np.random.default_rng(1)
    x = rng.normal(size=(ts.size, 3)).astype(np.float32)
    y = x[:, 0] + rng.normal(scale=0.5, size=ts.size)
    taus = (0.2, 0.5, 0.8)
    oof = train_quantile_oof(x, y, ts, taus=taus, params=SMALL, train_days=1, purge_ms=0.0, seed=42)
    refs = [
        LGBMRegressor(
            objective="quantile", alpha=tau, random_state=43, n_estimators=30, learning_rate=0.05, num_leaves=31,
            min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.9, verbose=-1,
        ).fit(x[:400], y[:400]).predict(x[400:])
        for tau in taus
    ]  # fmt: skip
    expect = np.sort(np.vstack(refs), axis=0)
    for k, tau in enumerate(taus):
        assert np.array_equal(oof.predictions[tau][400:], expect[k])


def test_validation_and_empty_report() -> None:
    ts = _days()
    with pytest.raises(AssertionError, match="xs.shape"):
        train_quantile_oof(np.zeros((3, 1)), [1.0], ts)
    with pytest.raises(AssertionError, match="taus"):
        train_quantile_oof(np.zeros((ts.size, 1)), np.zeros(ts.size), ts, taus=(0.0,))
    oof = train_quantile_oof(np.zeros((ts.size, 1)), np.zeros(ts.size), ts, taus=(0.5,), params=SMALL, train_days=2)
    assert "interval" not in quantile_report(oof, np.zeros(ts.size))
    assert quantile_report(oof, np.full(ts.size, np.nan)) == {"rows_tested": 0, "per_tau": {}}


def test_lightgbm_learns_a_signal() -> None:
    ts = _days(4, 400)
    rng = np.random.default_rng(1)
    x = rng.normal(size=(ts.size, 2))
    y = 3.0 * x[:, 0] + rng.normal(scale=0.5, size=ts.size)
    oof = train_quantile_oof(x, y, ts, params=LgbParams(n_estimators=60, min_child_samples=20), train_days=2)
    assert quantile_report(oof, y)["per_tau"]["q50"]["skill"] > 0.5
