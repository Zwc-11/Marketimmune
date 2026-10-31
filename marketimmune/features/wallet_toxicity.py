"""Rung L2: shrunk toxicity scores of the taker wallet (Zhai 2026's baseline).

Every Hyperliquid fill names both wallets. A taker whose past fills left makers with negative
markouts is likely informed. For a fill at ``t`` by taker ``w``:

    score_h(w, t) = (S_w + k * m) / (N_w + k)

where ``S_w`` and ``N_w`` are the sum and count of the maker markouts (horizon ``h``) of ``w``'s
earlier fills whose label was already *known* at ``t``, i.e. fills at ``s`` with ``s + h < t``;
``m`` is the mean over all such known labels (every wallet), and ``k`` the prior weight. A new
wallet scores ``m``. ``taker_log_n`` is ``log1p(N_w)`` at the longest horizon.

The scores need history across days, so a whole month of Gold rows is scored at once.
"""

from __future__ import annotations

import itertools
import math
import random
from collections.abc import Mapping
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
DEFAULT_HORIZONS = ("1s", "10s")
DEFAULT_PRIOR_WEIGHT = 20.0
WALLET_FEATURE_COLUMNS = (*(f"taker_tox_{h}" for h in DEFAULT_HORIZONS), "taker_log_n")


def _horizon_ms(h: str) -> float:
    assert h.endswith("s"), f"horizon must look like '10s', got {h!r}"
    return float(h[:-1]) * 1000.0


def _wallet_codes(wallet: npt.ArrayLike) -> IntArray:
    """Integer code per wallet, -1 for none."""
    codes: IntArray = pd.factorize(np.asarray(wallet, dtype=object))[0].astype(np.int64)
    return codes


def _scores(t: FloatArray, codes: IntArray, y: FloatArray, horizon_ms: float, prior_weight: float) -> tuple[FloatArray, FloatArray]:
    assert t.size == codes.size == y.size and prior_weight > 0.0, f"{t.size=} {codes.size=} {y.size=} {prior_weight=}"
    known_at = t + horizon_ms
    labels = np.flatnonzero(~np.isnan(y))
    labels = labels[np.argsort(known_at[labels], kind="stable")]  # the order labels resolve in
    j = np.searchsorted(known_at[labels], t, side="left")  # labels known strictly before each row
    prior = np.concatenate(([0.0], np.cumsum(y[labels])))[j] / np.maximum(j, 1)
    mine = labels[codes[labels] >= 0]
    mine = mine[np.argsort(codes[mine], kind="stable")]  # by wallet, then in resolve order
    mine_codes = codes[mine]
    # NOTE: one cumsum per wallet keeps the float summation order of a running per-wallet sum.
    cum = np.zeros(mine.size + 1)
    for a, b in itertools.pairwise((0, *(np.flatnonzero(np.diff(mine_codes)) + 1).tolist(), mine.size)):
        cum[a + 1 : b + 1] = np.cumsum(y[mine[a:b]])
    # rank times so (wallet, time) packs into one sortable integer key
    times = np.unique(np.concatenate((known_at[mine], t)))
    span = times.size + 1
    mine_key = mine_codes * span + np.searchsorted(times, known_at[mine])
    pos = np.searchsorted(mine_key, codes * span + np.searchsorted(times, t), side="left")
    count = pos - np.searchsorted(mine_key, codes * span, side="left")
    s = np.where(count > 0, cum[pos], 0.0)
    score: FloatArray = (s + prior_weight * prior) / (count + prior_weight)
    return score, count.astype(np.float64)


def shrunk_wallet_scores(
    ts_ms: npt.ArrayLike,
    wallet: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    horizon_ms: float,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
) -> tuple[FloatArray, FloatArray]:
    """Score and known-history count for every row (see the module docstring).

    A row's own label and every label that resolves at or after its time are excluded. NaN
    markouts (no label at that horizon) never enter the sums. Rows with no wallet get the
    running mean and count 0."""
    t = np.asarray(ts_ms, dtype=np.float64)
    return _scores(t, _wallet_codes(wallet), np.asarray(markout_bps, dtype=np.float64), horizon_ms, prior_weight)


def wallet_toxicity_features(
    ts_ms: npt.ArrayLike, taker: npt.ArrayLike, markouts: Mapping[str, npt.ArrayLike], *, prior_weight: float = DEFAULT_PRIOR_WEIGHT
) -> dict[str, FloatArray]:
    """``taker_tox_<h>`` per horizon in ``markouts`` and ``taker_log_n`` (longest h)."""
    t = np.asarray(ts_ms, dtype=np.float64)
    codes = _wallet_codes(taker)
    longest = max(markouts, key=_horizon_ms)
    out: dict[str, FloatArray] = {}
    for h, y in markouts.items():
        out[f"taker_tox_{h}"], seen = _scores(t, codes, np.asarray(y, dtype=np.float64), _horizon_ms(h), prior_weight)
        if h == longest:
            out["taker_log_n"] = np.log1p(seen)
    return out


def verify_wallet_scores_no_lookahead(
    ts_ms: npt.ArrayLike,
    wallet: npt.ArrayLike,
    markout_bps: npt.ArrayLike,
    horizon_ms: float,
    *,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    sample: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """Brute-force check: recompute sampled scores from only the labels known strictly before
    each row's time, and compare with the vectorised result."""
    t = np.asarray(ts_ms, dtype=np.float64)
    y = np.asarray(markout_bps, dtype=np.float64)
    codes = _wallet_codes(wallet)
    score, _seen = _scores(t, codes, y, horizon_ms, prior_weight)
    picks = sorted(random.Random(seed).sample(range(t.size), min(sample, t.size)))
    known = t + horizon_ms
    labelled = ~np.isnan(y)
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
    return {
        "passed": bool(picks) and mismatched == 0,
        "n_checked": len(picks),
        "n_mismatched": mismatched,
        "max_abs_diff": worst,
        "horizon_ms": horizon_ms,
    }
