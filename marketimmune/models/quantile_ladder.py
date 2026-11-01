"""The v3 detector's model: LightGBM quantile regressions of the maker's markout.

The plan's Integration section specifies quantile regressions at tau = 0.1, 0.5, 0.9 of the
maker's markout (bps) on the next fill, retrained on a rolling window and scored on the next
day. The quantiles say how bad a fill is likely to be; the 10th percentile feeds the quoting
rule "pull when the 10th-percentile markout is below a limit".

Out-of-fold predictions use the classifier's rolling daily folds.
Quantile crossing is removed by sorting each row's predictions (Chernozhukov, Fernandez-Val &
Galichon, 2010). Each fold also gets a climatology forecast (the training window's empirical
quantiles), so skill is ``1 - pinball_model / pinball_climatology``.

NOTE: one binned ``lightgbm.Dataset`` per fold serves every tau; the seed is per fold, so the
bins are the ones a dataset per tau would get. Training runs on the physical core count (the
scikit-learn wrapper's default, which the pre-registered numbers were made with: the thread
count can change LightGBM's histogram sums). Prediction is per row and uses every core.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
from joblib import cpu_count

from marketimmune.models.compare import pinball_loss
from marketimmune.models.cross_validation import temporal_fold_arrays
from marketimmune.models.decomposition import group_contributions

FloatArray = npt.NDArray[np.float64]
DEFAULT_TAUS = (0.1, 0.5, 0.9)


@dataclass(frozen=True, slots=True)
class LgbParams:
    """Pre-registered settings (docs/preregistration/sol-dec-2025-ladder.md)."""

    n_estimators: int = 300
    learning_rate: float = 0.05
    num_leaves: int = 31
    min_child_samples: int = 200
    subsample: float = 0.8
    subsample_freq: int = 1
    colsample_bytree: float = 0.9

    def booster_params(self, tau: float, seed: int) -> dict[str, Any]:
        return {
            "objective": "quantile",
            "alpha": tau,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "min_child_samples": self.min_child_samples,
            "subsample": self.subsample,
            "subsample_freq": self.subsample_freq,
            "colsample_bytree": self.colsample_bytree,
            "random_state": seed,
            "num_threads": cpu_count(only_physical_cores=True),
            "verbose": -1,
        }


PREREGISTERED = LgbParams()


def quantile_column(tau: float) -> str:
    """``0.1 -> "q10"``, ``0.5 -> "q50"``, ``0.95 -> "q95"``."""
    return f"q{round(tau * 100):02d}"


@dataclass
class QuantileOOF:
    """Out-of-fold quantile predictions (NaN on rows no fold tested)."""

    taus: tuple[float, ...]
    predictions: dict[float, FloatArray]
    climatology: dict[float, FloatArray]
    fold_summaries: list[dict[str, Any]] = field(default_factory=list)
    # group -> per-row contribution of the ``contrib_tau`` model (plus ``bias``)
    contributions: dict[str, FloatArray] = field(default_factory=dict)

    @property
    def tested(self) -> npt.NDArray[np.bool_]:
        return ~np.isnan(self.predictions[self.taus[0]])


def train_quantile_oof(
    x: npt.ArrayLike,
    y: npt.ArrayLike,
    ts_ms: npt.ArrayLike,
    *,
    taus: Sequence[float] = DEFAULT_TAUS,
    params: LgbParams = PREREGISTERED,
    train_days: int | None = None,
    purge_ms: float = 60_000.0,
    seed: int = 42,
    contrib_tau: float | None = None,
    contrib_groups: Mapping[str, Sequence[int]] | None = None,
    test_days: Collection[str] | None = None,
) -> QuantileOOF:
    """Fit one booster per (fold, tau) with seed ``seed + fold``; predict the fold's test rows.

    With ``contrib_tau`` and ``contrib_groups``, that tau's per-feature contributions
    (TreeSHAP, before the no-crossing sort) are summed by group for every test row."""
    xs = np.asarray(x, dtype=np.float32)
    ys = np.asarray(y, dtype=np.float64)
    ts = np.asarray(ts_ms, dtype=np.float64)
    assert xs.shape[0] == ys.size == ts.size, f"{xs.shape=} {ys.size=} {ts.size=}"
    ordered = tuple(sorted(float(t) for t in taus))
    assert all(0.0 < t < 1.0 for t in ordered), f"{taus=}"
    preds: dict[float, FloatArray] = {t: np.full(ys.size, np.nan) for t in ordered}
    clim: dict[float, FloatArray] = {t: np.full(ys.size, np.nan) for t in ordered}
    groups = contrib_groups if contrib_tau is not None else None
    contrib: dict[str, FloatArray] = {g: np.full(ys.size, np.nan) for g in (*groups, "bias")} if groups is not None else {}
    summaries: list[dict[str, Any]] = []
    threads = os.cpu_count() or 1
    for fold_id, fold in enumerate(temporal_fold_arrays(ts, purge_ms=purge_ms, train_days=train_days, test_days=test_days), start=1):
        if fold.train.size < 2 or fold.test.size == 0:
            continue
        y_train, x_test = ys[fold.train], xs[fold.test]
        train = lgb.Dataset(xs[fold.train], label=y_train)
        for tau in ordered:
            booster = lgb.train(params.booster_params(tau, seed + fold_id), train, num_boost_round=params.n_estimators)
            preds[tau][fold.test] = booster.predict(x_test, num_threads=threads)
            clim[tau][fold.test] = float(np.quantile(y_train, tau))
            if groups is not None and tau == contrib_tau:
                raw = booster.predict(x_test, pred_contrib=True, num_threads=threads)
                for g, values in group_contributions(raw, groups).items():
                    contrib[g][fold.test] = values
        summaries.append(
            {
                "fold_id": fold_id,
                "n_train": int(fold.train.size),
                "n_test": int(fold.test.size),
                "test_start_ms": fold.test_start_ms,
                "test_end_ms": fold.test_end_ms,
            }
        )
    if len(ordered) > 1:
        stacked = np.sort(np.vstack([preds[t] for t in ordered]), axis=0)  # no crossing
        preds = {tau: stacked[k] for k, tau in enumerate(ordered)}
    return QuantileOOF(taus=ordered, predictions=preds, climatology=clim, fold_summaries=summaries, contributions=contrib)


def quantile_report(oof: QuantileOOF, y: npt.ArrayLike) -> dict[str, Any]:
    """Pinball loss and skill per tau, plus interval coverage and width."""
    ys = np.asarray(y, dtype=np.float64)
    tested = oof.tested & ~np.isnan(ys)
    out: dict[str, Any] = {"rows_tested": int(tested.sum()), "per_tau": {}}
    if not tested.any():
        return out
    yt = ys[tested]
    for tau in oof.taus:
        model = float(pinball_loss(yt, oof.predictions[tau][tested], tau).mean())
        base = float(pinball_loss(yt, oof.climatology[tau][tested], tau).mean())
        out["per_tau"][quantile_column(tau)] = {
            "pinball": model,
            "pinball_climatology": base,
            "skill": 1.0 - model / base if base > 0 else None,
            "hit_rate": float(np.mean(yt <= oof.predictions[tau][tested])),  # should be close to tau
        }
    lo, hi = oof.taus[0], oof.taus[-1]
    if hi > lo:
        q_lo, q_hi = oof.predictions[lo][tested], oof.predictions[hi][tested]
        out["interval"] = {
            "nominal": hi - lo,
            "coverage": float(np.mean((yt >= q_lo) & (yt <= q_hi))),
            "mean_width_bps": float(np.mean(q_hi - q_lo)),
        }
    return out
