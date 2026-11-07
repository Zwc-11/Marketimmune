"""How much of a backtest's best result is luck from trying many settings.

- ``pbo_cscv``: the probability of backtest overfitting by combinatorially symmetric
  cross-validation (Bailey, Borwein, López de Prado and Zhu, 2017). The block-by-config PnL
  matrix is cut into ``groups`` time groups; for every way of taking half of them as in-sample,
  the config that is best in-sample is ranked among all configs on the other half. PBO is the
  share of splits where it ranks at or below the median out of sample (logit <= 0).
- ``deflated_sharpe``: the probability that the chosen config's true Sharpe ratio is above zero,
  after deflating for the number of configs tried and for non-normal returns (Bailey and López
  de Prado, 2014). The benchmark is the Sharpe ratio expected of the best of ``n_trials`` configs
  with no skill, from the variance of the trials' Sharpe ratios.
"""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
EULER_GAMMA = 0.5772156649015329
N01 = NormalDist()


def pbo_cscv(pnl: FloatArray, groups: int = 8) -> dict[str, float]:
    """``pnl``: blocks x configs. Returns PBO, the median logit, and the mean out-of-sample
    PnL per block of the in-sample best config against the mean over all configs."""
    t, n = pnl.shape
    if n < 2 or t < groups:
        raise ValueError(f"need at least 2 configs and {groups} blocks, got {n} and {t}")
    parts = np.array_split(np.arange(t), groups)
    logits, best_oos, all_oos = [], [], []
    for chosen in itertools.combinations(range(groups), groups // 2):
        ins = np.concatenate([parts[g] for g in chosen])
        oos = np.concatenate([parts[g] for g in range(groups) if g not in chosen])
        best = int(np.argmax(pnl[ins].mean(axis=0)))
        perf = pnl[oos].mean(axis=0)
        rank = (perf < perf[best]).sum() + 0.5 * ((perf == perf[best]).sum() - 1) + 1  # 1..n, ties halved
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
        best_oos.append(float(perf[best]))
        all_oos.append(float(perf.mean()))
    lg = np.asarray(logits)
    return {
        "pbo": float((lg <= 0).mean()),
        "median_logit": float(np.median(lg)),
        "splits": len(lg),
        "best_in_sample_mean_oos": float(np.mean(best_oos)),
        "all_configs_mean_oos": float(np.mean(all_oos)),
    }


def deflated_sharpe(returns: FloatArray, trial_sharpes: FloatArray) -> dict[str, float]:
    """``returns``: the chosen config's per-block PnL; ``trial_sharpes``: every config's per-block
    Sharpe ratio (the chosen one included)."""
    r = np.asarray(returns, np.float64)
    t = r.size
    sd = r.std(ddof=1)
    sr = float(r.mean() / sd) if sd > 0 else 0.0
    z = (r - r.mean()) / sd if sd > 0 else r * 0
    skew = float((z**3).mean())
    kurt = float((z**4).mean())
    n = len(trial_sharpes)
    var_sr = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    sr0 = (
        math.sqrt(var_sr) * ((1 - EULER_GAMMA) * N01.inv_cdf(1 - 1 / n) + EULER_GAMMA * N01.inv_cdf(1 - 1 / (n * math.e))) if n > 1 else 0.0
    )
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    dsr = N01.cdf((sr - sr0) * math.sqrt(t - 1) / denom)
    psr = N01.cdf(sr * math.sqrt(t - 1) / denom)
    return {
        "sharpe_per_block": sr,
        "expected_max_sharpe_of_trials": sr0,
        "trials": n,
        "blocks": t,
        "deflated_sharpe": dsr,
        "probabilistic_sharpe": psr,
    }
