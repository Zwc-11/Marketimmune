"""Rung L2: shrunk toxicity scores of the taker wallet (Zhai 2026's baseline).

Every Hyperliquid fill names both wallets. A taker whose past fills left makers
with negative markouts is likely informed. For a fill at ``t`` by taker ``w``:

    score_h(w, t) = (S_w + k * m) / (N_w + k)

where ``S_w`` and ``N_w`` are the sum and count of the maker markouts (horizon
``h``) of ``w``'s earlier fills whose label was already *known* at ``t``, i.e.
fills at ``s`` with ``s + h < t``; ``m`` is the mean over all such known labels
(every wallet), and ``k`` the prior weight. A new wallet scores ``m``. The
column ``taker_log_n`` is ``log1p(N_w)`` at the longest horizon.

The scores need history across days, so they are computed over a whole month of
Gold rows at once, in time order.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
DEFAULT_HORIZONS = ("1s", "10s")
DEFAULT_PRIOR_WEIGHT = 20.0


def wallet_feature_columns(horizons: Sequence[str] = DEFAULT_HORIZONS) -> tuple[str, ...]:
    return (*(f"taker_tox_{h}" for h in horizons), "taker_log_n")


WALLET_FEATURE_COLUMNS = wallet_feature_columns()


def _horizon_ms(h: str) -> float:
    if not h.endswith("s"):
        raise ValueError(f"horizon must look like '10s', got {h!r}")
    return float(h[:-1]) * 1000.0


def shrunk_wallet_scores(
    ts_ms: npt.ArrayLike,
    wallet: Sequence[str | None],
    markout_bps: npt.ArrayLike,
    horizon_ms: float,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
) -> tuple[FloatArray, FloatArray]:
    """Score and known-history count for every row (see the module docstring).

    A row's own label and every label that resolves at or after its time are
    excluded. NaN markouts (no label at that horizon) never enter the sums.
    Rows with no wallet get the running mean and count 0.
    """
    t = np.asarray(ts_ms, dtype=np.float64)
    y = np.asarray(markout_bps, dtype=np.float64)
    n = t.size
    if len(wallet) != n or y.size != n:
        raise ValueError("ts_ms, wallet and markout_bps must have the same length")
    if prior_weight <= 0.0:
        raise ValueError("prior_weight must be positive")
    query_order = np.argsort(t, kind="stable")
    known_at = t + horizon_ms
    resolvable = np.flatnonzero(~np.isnan(y))
    label_order = resolvable[np.argsort(known_at[resolvable], kind="stable")]
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    total = 0.0
    total_n = 0
    score = np.empty(n)
    seen = np.zeros(n)
    j = 0
    n_labels = label_order.size
    for i in query_order.tolist():
        ti = t[i]
        while j < n_labels and known_at[label_order[j]] < ti:
            k = int(label_order[j])
            w = wallet[k]
            if w is not None:
                sums[w] = sums.get(w, 0.0) + y[k]
                counts[w] = counts.get(w, 0) + 1
            total += y[k]
            total_n += 1
            j += 1
        prior = total / total_n if total_n else 0.0
        w = wallet[i]
        cnt = counts.get(w, 0) if w is not None else 0
        s = sums.get(w, 0.0) if w is not None else 0.0
        score[i] = (s + prior_weight * prior) / (cnt + prior_weight)
        seen[i] = cnt
    return score, seen


def wallet_toxicity_features(
    ts_ms: npt.ArrayLike,
    taker: Sequence[str | None],
    markouts: dict[str, npt.ArrayLike],
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
) -> dict[str, FloatArray]:
    """``taker_tox_<h>`` per horizon in ``markouts`` and ``taker_log_n`` (longest h)."""
    out: dict[str, FloatArray] = {}
    longest = max(markouts, key=_horizon_ms)
    for h, y in markouts.items():
        score, seen = shrunk_wallet_scores(
            ts_ms, taker, y, _horizon_ms(h), prior_weight=prior_weight
        )
        out[f"taker_tox_{h}"] = score
        if h == longest:
            out["taker_log_n"] = np.log1p(seen)
    return out


def verify_wallet_scores_no_lookahead(
    ts_ms: npt.ArrayLike,
    wallet: Sequence[str | None],
    markout_bps: npt.ArrayLike,
    horizon_ms: float,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    sample: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """Brute-force check: recompute sampled scores from only the labels known
    strictly before each row's time, and compare with the streaming result."""
    t = np.asarray(ts_ms, dtype=np.float64)
    y = np.asarray(markout_bps, dtype=np.float64)
    score, _seen = shrunk_wallet_scores(t, wallet, y, horizon_ms, prior_weight=prior_weight)
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(t.size), min(sample, t.size)))
    known = t + horizon_ms
    labelled = ~np.isnan(y)
    codes = _wallet_codes(wallet)
    mismatched = 0
    worst = 0.0
    for i in picks:
        ok = (known < t[i]) & labelled
        prior = float(y[ok].mean()) if ok.any() else 0.0
        mine = ok & (codes == codes[i]) & (codes >= 0)
        expect = (float(y[mine].sum()) + prior_weight * prior) / (int(mine.sum()) + prior_weight)
        diff = abs(expect - float(score[i]))
        worst = max(worst, diff)
        mismatched += int(not math.isclose(diff, 0.0, abs_tol=1e-9))
    return {"passed": bool(picks) and mismatched == 0, "n_checked": len(picks),
            "n_mismatched": mismatched, "max_abs_diff": worst, "horizon_ms": horizon_ms}


def _wallet_codes(wallet: Sequence[str | None]) -> npt.NDArray[np.int64]:
    """Integer code per wallet (-1 for none), for fast equality tests."""
    index: dict[str, int] = {}
    return np.fromiter(
        (-1 if w is None else index.setdefault(w, len(index)) for w in wallet),
        dtype=np.int64,
        count=len(wallet),
    )
