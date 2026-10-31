"""Is rung B better than rung A? Day-level tests on out-of-fold predictions.

Fills within a day share news, volatility and wallets, so per-fill errors are far from
independent; the unit of evidence is the day. For each day the mean loss of each model is
taken and ``d_t = loss_A - loss_B`` (positive = B better).

* :func:`diebold_mariano`: mean of ``d_t`` over a Newey-West (Bartlett) HAC standard error,
  with the Harvey-Leybourne-Newbold small-sample factor and a Student-t p-value on ``n - 1``
  degrees of freedom.
* :func:`stationary_bootstrap_ci`: Politis-Romano stationary bootstrap of the mean of ``d_t``
  (geometric blocks, mean length ``mean_block`` days). The index paths
  (:func:`stationary_bootstrap_indices`) are shared with the MCS and the decomposition.

Losses: Brier and log loss on the toxic label; pinball at a chosen tau on the markout for the
v3 quantile ladder.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.stats import t as student_t  # type: ignore[import-untyped]

FloatArray = npt.NDArray[np.float64]
Loss = Callable[[npt.ArrayLike, npt.ArrayLike], FloatArray]
LOSSES = ("brier", "log", "pinball")


def brier_loss(y: npt.ArrayLike, p: npt.ArrayLike) -> FloatArray:
    out: FloatArray = (np.asarray(y, dtype=np.float64) - np.asarray(p, dtype=np.float64)) ** 2
    return out


def log_loss(y: npt.ArrayLike, p: npt.ArrayLike, eps: float = 1e-6) -> FloatArray:
    yy = np.asarray(y, dtype=np.float64)
    pp = np.clip(np.asarray(p, dtype=np.float64), eps, 1.0 - eps)
    out: FloatArray = -(yy * np.log(pp) + (1.0 - yy) * np.log(1.0 - pp))
    return out


def pinball_loss(y: npt.ArrayLike, q: npt.ArrayLike, tau: float) -> FloatArray:
    """Elementwise pinball (quantile) loss of prediction ``q`` at level ``tau``."""
    assert 0.0 < tau < 1.0, f"{tau=}"
    diff = np.asarray(y, dtype=np.float64) - np.asarray(q, dtype=np.float64)
    out: FloatArray = np.maximum(tau * diff, (tau - 1.0) * diff)
    return out


def make_loss(name: str, tau: float = 0.5) -> Loss:
    """Per-row loss ``f(y, prediction)``: Brier or log loss on the toxic label, or pinball at
    ``tau`` on the markout (the quantile ladder)."""
    assert name in LOSSES, f"{name=} not in {LOSSES}"
    if name == "pinball":
        return lambda y, q: pinball_loss(y, q, tau)
    return brier_loss if name == "brier" else log_loss


def daily_means(values: npt.ArrayLike, days: Sequence[Any] | npt.NDArray[Any]) -> tuple[list[Any], FloatArray, npt.NDArray[np.int64]]:
    """Mean of ``values`` per day, days in sorted order, with row counts."""
    keys, inverse = np.unique(np.asarray(days), return_inverse=True)
    counts = np.bincount(inverse, minlength=keys.size)
    sums = np.bincount(inverse, weights=np.asarray(values, dtype=np.float64), minlength=keys.size)
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
    n = int(x.size)
    assert n >= 3 and not np.isnan(x).any(), f"need at least 3 days without NaN, got {x=}"
    q = newey_west_lag(n) if lag is None else lag
    mean = float(x.mean())
    e = x - mean
    var = float(e @ e) / n
    for k in range(1, min(q, n - 1) + 1):
        var += 2.0 * (1.0 - k / (q + 1.0)) * float(e[k:] @ e[:-k]) / n
    se = math.sqrt(max(var, 0.0) / n)
    # Harvey, Leybourne & Newbold (1997) correction for a one-step horizon.
    t_stat = mean / se * math.sqrt((n - 1) / n) if se > 0.0 else (0.0 if mean == 0.0 else math.copysign(math.inf, mean))
    p_value = 2.0 * float(student_t.sf(abs(t_stat), n - 1))
    return DMResult(n=n, mean=mean, se=se, t_stat=t_stat, p_value=p_value, lag=q)


def stationary_bootstrap_indices(n: int, n_boot: int, mean_block: float, rng: np.random.Generator) -> npt.NDArray[np.int64]:
    """``(n_boot, n)`` index paths: geometric blocks with mean length ``mean_block``, wrapping."""
    assert n >= 1 and mean_block >= 1.0, f"{n=} {mean_block=}"
    starts = rng.integers(0, n, size=(n_boot, n))
    new_block = rng.random((n_boot, n)) < 1.0 / mean_block
    new_block[:, 0] = True
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for j in range(1, n):
        idx[:, j] = np.where(new_block[:, j], starts[:, j], (idx[:, j - 1] + 1) % n)
    return idx


def stationary_bootstrap_ci(
    d: npt.ArrayLike, *, mean_block: float = 3.0, n_boot: int = 5_000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    """Percentile interval for the mean of ``d`` (Politis & Romano 1994)."""
    x = np.asarray(d, dtype=np.float64)
    assert not np.isnan(x).any(), f"{x=}"
    idx = stationary_bootstrap_indices(x.size, n_boot, mean_block, np.random.default_rng(seed))
    lo, hi = np.quantile(x[idx].mean(axis=1), [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(lo), float(hi)


def compare_rungs(
    days: Sequence[Any] | npt.NDArray[Any],
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
    la, lb = fn(yy, p_base), fn(yy, p_challenger)
    masks = {"all": np.ones(yy.size, dtype=bool), **{name: np.asarray(m, dtype=bool) for name, m in (regimes or {}).items()}}
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
                {"day": k, "rows": int(c), "improvement": float(v)} for k, c, v in zip(keys, counts.tolist(), d.tolist(), strict=True)
            ],
        }
        if len(keys) >= 3:
            entry["diebold_mariano"] = diebold_mariano(d).to_dict()
            entry["bootstrap_ci_95"] = list(stationary_bootstrap_ci(d, seed=seed))
        out[name] = entry
    return out
