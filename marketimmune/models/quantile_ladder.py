"""The v3 detector's model: quantile regressions of the maker's markout.

The plan's Integration section specifies LightGBM quantile regressions at
tau = 0.1, 0.5, 0.9 of the maker's markout (bps) on the next fill, retrained on
a rolling window and scored on the next day. Unlike the toxic/not-toxic
classifier, the quantiles say *how bad* a fill is likely to be, and the 10th
percentile feeds the quoting rule "pull when the 10th-percentile markout is
below a limit".

Out-of-fold predictions are produced on the same temporal folds as the
classifier (``rolling_daily`` by default). Quantile crossing is removed by
sorting each row's predictions (Chernozhukov, Fernandez-Val & Galichon, 2010).
Each fold also gets a climatology forecast (the training window's empirical
quantiles), so skill is reported as ``1 - pinball_model / pinball_climatology``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from marketimmune.models.cross_validation import CvScheme, temporal_fold_arrays
from marketimmune.models.decomposition import group_contributions

FloatArray = npt.NDArray[np.float64]
DEFAULT_TAUS = (0.1, 0.5, 0.9)


class QuantileRegressor(Protocol):
    def fit(self, x: Any, y: Any) -> Any: ...
    def predict(self, x: Any) -> Any: ...


RegressorFactory = Callable[[float, int], QuantileRegressor]


def pinball_loss(y: npt.ArrayLike, q: npt.ArrayLike, tau: float) -> FloatArray:
    """Elementwise pinball (quantile) loss of prediction ``q`` at level ``tau``."""
    if not 0.0 < tau < 1.0:
        raise ValueError("tau must be in (0, 1)")
    diff = np.asarray(y, dtype=np.float64) - np.asarray(q, dtype=np.float64)
    out: FloatArray = np.maximum(tau * diff, (tau - 1.0) * diff)
    return out


def quantile_column(tau: float) -> str:
    """``0.1 -> "q10"``, ``0.5 -> "q50"``, ``0.95 -> "q95"``."""
    return f"q{round(tau * 100):02d}"


def lightgbm_factory(**params: Any) -> RegressorFactory:
    """LightGBM ``objective="quantile"`` regressors (imported lazily)."""

    def make(tau: float, seed: int) -> QuantileRegressor:
        from lightgbm import LGBMRegressor

        settings: dict[str, Any] = {
            "n_estimators": 300,
            "learning_rate": 0.05,
            "num_leaves": 31,
            "min_child_samples": 200,
            "subsample": 0.8,
            "subsample_freq": 1,
            "colsample_bytree": 0.9,
            "verbose": -1,
        }
        settings.update(params)
        model: QuantileRegressor = LGBMRegressor(
            objective="quantile", alpha=tau, random_state=seed, **settings
        )
        return model

    return make


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
    factory: RegressorFactory | None = None,
    scheme: CvScheme = "rolling_daily",
    train_days: int | None = None,
    n_splits: int = 5,
    purge_ms: float = 60_000.0,
    embargo_ms: float = 0.0,
    seed: int = 42,
    contrib_tau: float | None = None,
    contrib_groups: Mapping[str, Sequence[int]] | None = None,
) -> QuantileOOF:
    """Fit one regressor per (fold, tau); predict the fold's test rows.

    With ``contrib_tau`` and ``contrib_groups`` (LightGBM models), the per-feature
    contributions of that tau's model (``pred_contrib=True``, before the
    no-crossing sort) are summed by group for every test row."""
    xs = np.asarray(x, dtype=np.float32)
    ys = np.asarray(y, dtype=np.float64)
    ts = np.asarray(ts_ms, dtype=np.float64)
    if xs.shape[0] != ys.size or ys.size != ts.size:
        raise ValueError("x, y and ts_ms must have the same number of rows")
    ordered = tuple(sorted(float(t) for t in taus))
    for tau in ordered:
        if not 0.0 < tau < 1.0:
            raise ValueError("every tau must be in (0, 1)")
    make = factory or lightgbm_factory()
    preds: dict[float, FloatArray] = {t: np.full(ys.size, np.nan) for t in ordered}
    clim: dict[float, FloatArray] = {t: np.full(ys.size, np.nan) for t in ordered}
    summaries: list[dict[str, Any]] = []
    contrib: dict[str, FloatArray] = {}
    if contrib_tau is not None and contrib_groups is not None:
        contrib = {g: np.full(ys.size, np.nan) for g in (*contrib_groups, "bias")}
    folds = temporal_fold_arrays(
        ts, n_splits=n_splits, purge_ms=purge_ms, embargo_ms=embargo_ms,
        scheme=scheme, train_days=train_days,
    )
    for fold_id, fold in enumerate(folds, start=1):
        if fold.train.size < 2 or fold.test.size == 0:
            continue
        for tau in ordered:
            model = make(tau, seed + fold_id)
            model.fit(xs[fold.train], ys[fold.train])
            preds[tau][fold.test] = np.asarray(model.predict(xs[fold.test]), dtype=np.float64)
            clim[tau][fold.test] = float(np.quantile(ys[fold.train], tau))
            if contrib and contrib_groups is not None and math.isclose(tau, contrib_tau or -1.0):
                raw = model.predict(xs[fold.test], pred_contrib=True)  # type: ignore[call-arg]
                for g, values in group_contributions(raw, contrib_groups).items():
                    contrib[g][fold.test] = values
        summaries.append({
            "fold_id": fold_id,
            "n_train": int(fold.train.size),
            "n_test": int(fold.test.size),
            "test_start_ms": fold.test_start_ms,
            "test_end_ms": fold.test_end_ms,
        })
    if len(ordered) > 1:
        stacked = np.sort(np.vstack([preds[t] for t in ordered]), axis=0)  # no crossing
        for k, tau in enumerate(ordered):
            preds[tau] = stacked[k]
    return QuantileOOF(taus=ordered, predictions=preds, climatology=clim,
                       fold_summaries=summaries, contributions=contrib)


def quantile_report(oof: QuantileOOF, y: npt.ArrayLike) -> dict[str, Any]:
    """Pinball loss and skill per tau, plus interval coverage and width."""
    ys = np.asarray(y, dtype=np.float64)
    tested = oof.tested & ~np.isnan(ys)
    out: dict[str, Any] = {"rows_tested": int(tested.sum()), "per_tau": {}}
    if not tested.any():
        return out
    for tau in oof.taus:
        model = float(pinball_loss(ys[tested], oof.predictions[tau][tested], tau).mean())
        base = float(pinball_loss(ys[tested], oof.climatology[tau][tested], tau).mean())
        hit = float(np.mean(ys[tested] <= oof.predictions[tau][tested]))
        out["per_tau"][quantile_column(tau)] = {
            "pinball": model,
            "pinball_climatology": base,
            "skill": 1.0 - model / base if base > 0 else None,
            "hit_rate": hit,  # should be close to tau
        }
    lo, hi = oof.taus[0], oof.taus[-1]
    if hi > lo:
        q_lo, q_hi = oof.predictions[lo][tested], oof.predictions[hi][tested]
        out["interval"] = {
            "nominal": hi - lo,
            "coverage": float(np.mean((ys[tested] >= q_lo) & (ys[tested] <= q_hi))),
            "mean_width_bps": float(np.mean(q_hi - q_lo)),
        }
    return out
