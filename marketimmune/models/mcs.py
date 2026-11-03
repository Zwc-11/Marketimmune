"""Model Confidence Set over the ladder (Hansen, Lunde & Nason, 2011).

Pairwise Diebold-Mariano tests answer "is B better than A"; with five rungs and
a placebo, running them all inflates false positives. The MCS answers the
plan's final question instead: which rungs cannot be distinguished from the
best, at level alpha. It starts from all rungs and repeatedly tests equal
predictive ability; while that is rejected, it drops the rung with the largest
loss relative to the set's average, and stops when the survivors are
statistically indistinguishable.

Inputs are daily mean losses (days x models), the same day-level evidence as
``marketimmune.models.compare``. The statistic is T_max with the stationary
bootstrap for its distribution; each model gets an MCS p-value (the largest
elimination p-value up to its own removal; 1.0 for the last survivor).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.models.compare import stationary_bootstrap_indices

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class MCSResult:
    names: tuple[str, ...]
    mean_loss: tuple[float, ...]
    p_values: tuple[float, ...]
    elimination_order: tuple[str, ...]
    alpha: float

    @property
    def included(self) -> tuple[str, ...]:
        return tuple(n for n, p in zip(self.names, self.p_values, strict=True) if p > self.alpha)

    def to_dict(self) -> dict[str, Any]:
        rows = sorted(zip(self.names, self.mean_loss, self.p_values, strict=True), key=lambda r: r[1])
        return {
            "alpha": self.alpha,
            "included": list(self.included),
            "elimination_order": list(self.elimination_order),
            "models": [{"name": n, "mean_loss": m, "mcs_p_value": p, "in_mcs": p > self.alpha} for n, m, p in rows],
        }


def model_confidence_set(
    losses: npt.ArrayLike,
    names: Sequence[str],
    *,
    alpha: float = 0.10,
    n_boot: int = 5_000,
    mean_block: float = 3.0,
    seed: int = 0,
) -> MCSResult:
    """MCS with the T_max statistic on a ``(days, models)`` loss matrix."""
    loss = np.asarray(losses, dtype=np.float64)
    assert loss.ndim == 2 and loss.shape[1] == len(names) >= 2, f"losses must be (days, models >= 2), one name per column: {loss.shape=}"
    assert loss.shape[0] >= 3 and not np.isnan(loss).any(), f"need at least 3 common days without NaN: {loss.shape=}"
    assert 0.0 < alpha < 1.0, f"{alpha=}"
    idx = stationary_bootstrap_indices(loss.shape[0], n_boot, mean_block, np.random.default_rng(seed))
    boot_means = loss[idx].mean(axis=1)  # (n_boot, models): one draw reused across steps
    full_means = loss.mean(axis=0)

    alive = list(range(loss.shape[1]))
    p_values = np.ones(loss.shape[1])
    order: list[str] = []
    running = 0.0
    while len(alive) > 1:
        cols = np.asarray(alive)
        d_bar = full_means[cols] - full_means[cols].mean()
        d_boot = boot_means[:, cols] - boot_means[:, cols].mean(axis=1, keepdims=True)
        if np.allclose(d_bar, 0.0, atol=1e-12) and np.allclose(d_boot, 0.0, atol=1e-12):
            break  # identical losses: nothing distinguishes the survivors
        centred = d_boot - d_bar
        var = (centred**2).mean(axis=0)
        se = np.sqrt(np.where(var > 0.0, var, np.nan))
        t = d_bar / se
        if np.all(np.isnan(t)):
            break  # no bootstrap variation left (constant differences)
        t_max = np.nanmax(t)
        t_boot = np.nanmax(centred / se, axis=1)
        p = float(np.mean(t_boot >= t_max))
        worst = int(cols[int(np.nanargmax(t))])
        running = max(running, p)
        p_values[worst] = running
        order.append(names[worst])
        alive.remove(worst)
    return MCSResult(
        names=tuple(names),
        mean_loss=tuple(float(v) for v in full_means),
        p_values=tuple(float(v) for v in p_values),
        elimination_order=tuple(order),
        alpha=alpha,
    )
