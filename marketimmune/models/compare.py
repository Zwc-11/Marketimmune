"""Is rung B better than rung A? Day-level tests on out-of-fold predictions.

Fills within a day share news, volatility and wallets, so per-fill errors are
far from independent; the unit of evidence is the day. For each day the mean
loss of each model is taken and ``d_t = loss_A - loss_B`` (positive = B better).

* :func:`diebold_mariano`: mean of ``d_t`` over a Newey-West (Bartlett) HAC
  standard error, with the Harvey-Leybourne-Newbold small-sample factor and a
  Student-t p-value on ``n - 1`` degrees of freedom.
* :func:`stationary_bootstrap_ci`: Politis-Romano stationary bootstrap of the
  mean of ``d_t`` (geometric blocks, mean length ``mean_block`` days).

Losses: Brier and log loss on the toxic label; pinball at a chosen tau on the
markout for the v3 quantile ladder.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def brier_loss(y: npt.ArrayLike, p: npt.ArrayLike) -> FloatArray:
    out: FloatArray = (np.asarray(y, dtype=np.float64) - np.asarray(p, dtype=np.float64)) ** 2
    return out


def log_loss(y: npt.ArrayLike, p: npt.ArrayLike, eps: float = 1e-6) -> FloatArray:
    yy = np.asarray(y, dtype=np.float64)
    pp = np.clip(np.asarray(p, dtype=np.float64), eps, 1.0 - eps)
    out: FloatArray = -(yy * np.log(pp) + (1.0 - yy) * np.log(1.0 - pp))
    return out


LOSSES = {"brier": brier_loss, "log": log_loss, "pinball": None}


def make_loss(name: str, tau: float = 0.5) -> Any:
    """Per-row loss ``f(y, prediction)``: Brier or log loss on the toxic label, or
    pinball at ``tau`` on the markout (the quantile ladder)."""
    if name not in LOSSES:
        raise ValueError(f"loss must be one of {sorted(LOSSES)}")
    if name == "pinball":
        from marketimmune.models.quantile_ladder import pinball_loss

        return lambda y, q: pinball_loss(y, q, tau)
    return LOSSES[name]


def daily_means(
    values: npt.ArrayLike, days: Sequence[Any] | npt.NDArray[Any]
) -> tuple[list[Any], FloatArray, npt.NDArray[np.int64]]:
    """Mean of ``values`` per day, days in sorted order, with row counts."""
    v = np.asarray(values, dtype=np.float64)
    keys, inverse = np.unique(np.asarray(days), return_inverse=True)
    counts = np.bincount(inverse, minlength=keys.size)
    sums = np.bincount(inverse, weights=v, minlength=keys.size)
    return keys.tolist(), sums / counts, counts.astype(np.int64)


@dataclass(frozen=True, slots=True)
class DMResult:
    n: int
    mean: float
    se: float
    t_stat: float
    p_value: float
    lag: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def newey_west_lag(n: int) -> int:
    """Newey-West (1994) automatic lag: floor(4 (n / 100)^(2/9))."""
    return max(0, int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))


def diebold_mariano(d: npt.ArrayLike, *, lag: int | None = None) -> DMResult:
    """Test ``E[d] = 0`` for a series of loss differentials (one per day)."""
    x = np.asarray(d, dtype=np.float64)
    x = x[~np.isnan(x)]
    n = int(x.size)
    if n < 3:
        raise ValueError("need at least 3 days of loss differentials")
    q = newey_west_lag(n) if lag is None else lag
    mean = float(x.mean())
    e = x - mean
    var = float(e @ e) / n
    for k in range(1, min(q, n - 1) + 1):
        var += 2.0 * (1.0 - k / (q + 1.0)) * float(e[k:] @ e[:-k]) / n
    se = math.sqrt(max(var, 0.0) / n)
    if se == 0.0:
        t_stat = 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
    else:
        # Harvey, Leybourne & Newbold (1997) correction for a one-step horizon.
        t_stat = mean / se * math.sqrt((n - 1) / n)
    p_value = 2.0 * _student_t_sf(abs(t_stat), n - 1)
    return DMResult(n=n, mean=mean, se=se, t_stat=t_stat, p_value=p_value, lag=q)


def stationary_bootstrap_ci(
    d: npt.ArrayLike,
    *,
    mean_block: float = 3.0,
    n_boot: int = 5_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile interval for the mean of ``d`` (Politis & Romano 1994)."""
    x = np.asarray(d, dtype=np.float64)
    x = x[~np.isnan(x)]
    n = x.size
    if n == 0:
        raise ValueError("empty series")
    if mean_block < 1.0:
        raise ValueError("mean_block must be >= 1")
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block
    starts = rng.integers(0, n, size=(n_boot, n))
    new_block = rng.random((n_boot, n)) < p
    new_block[:, 0] = True
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for j in range(1, n):
        idx[:, j] = np.where(new_block[:, j], starts[:, j], (idx[:, j - 1] + 1) % n)
    means = x[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(lo), float(hi)


def compare_rungs(
    days: Sequence[Any],
    y: npt.ArrayLike,
    p_base: npt.ArrayLike,
    p_challenger: npt.ArrayLike,
    *,
    loss: str = "brier",
    tau: float = 0.5,
    regimes: Mapping[str, npt.ArrayLike] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Day-level comparison overall and inside each regime mask."""
    fn = make_loss(loss, tau)
    day_arr = np.asarray(days)
    yy = np.asarray(y, dtype=np.float64)
    la = fn(yy, p_base)
    lb = fn(yy, p_challenger)
    masks: dict[str, npt.NDArray[np.bool_]] = {"all": np.ones(yy.size, dtype=bool)}
    for name, mask in (regimes or {}).items():
        masks[name] = np.asarray(mask, dtype=bool)
    out: dict[str, Any] = {"loss": loss, **({"tau": tau} if loss == "pinball" else {})}
    for name, mask in masks.items():
        if not mask.any():
            out[name] = {"rows": 0}
            continue
        keys, mean_a, counts = daily_means(la[mask], day_arr[mask])
        _keys, mean_b, _counts = daily_means(lb[mask], day_arr[mask])
        d = mean_a - mean_b
        entry: dict[str, Any] = {
            "rows": int(mask.sum()),
            "days": len(keys),
            "loss_base": float(la[mask].mean()),
            "loss_challenger": float(lb[mask].mean()),
            "mean_daily_improvement": float(d.mean()),
            "days_improved": int((d > 0).sum()),
            "per_day": [
                {"day": k, "rows": int(c), "improvement": float(v)}
                for k, c, v in zip(keys, counts.tolist(), d.tolist(), strict=True)
            ],
        }
        if len(keys) >= 3:
            entry["diebold_mariano"] = diebold_mariano(d).to_dict()
            lo, hi = stationary_bootstrap_ci(d, seed=seed)
            entry["bootstrap_ci_95"] = [lo, hi]
        out[name] = entry
    return out


def _student_t_sf(t: float, dof: int) -> float:
    """Survival function of Student's t (scipy when installed, else a normal tail)."""
    try:
        from scipy.stats import t as student_t  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - scipy ships with scikit-learn
        return 0.5 * math.erfc(t / math.sqrt(2.0))
    return float(student_t.sf(t, dof))
