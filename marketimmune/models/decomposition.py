"""Decomposed reading of predicted adverse selection (plan, Integration).

With speed and forced-flow inputs in the model, each fill's predicted markout
splits into parts a maker treats differently:

* ``latency_arb``: the CEX gap and Binance returns, lost races and (later)
  priority-fee features. Response: cancel or widen for a few blocks.
* ``forced``: realised and forecast forced flow. Response: skew away from the
  side forced orders will hit.
* ``wallet``: shrunk taker-wallet scores (informed flow).
* ``state``: everything else (book, OFI, spread).

The plan's three-way split is latency-arb / forced / residual, with
``residual = wallet + state``.

Model-based shares come from LightGBM's per-feature contributions (TreeSHAP,
``pred_contrib=True``) of the tau = 0.5 model, summed by group: for a fill,
``prediction = bias + sum over groups``. Among fills predicted worse than the
model's baseline (``prediction < bias``), the share of group ``g`` is
``sum c_g / sum (prediction - bias)``. Contributions can have either sign, so a
share can fall outside [0, 1]; the shares add to 1. Intervals bootstrap days.

The realised reading needs no model: S1's maker fills split by regime (Binance
moved against the quote before the fill; forced flow in the previous 60 s; both;
quiet), with each regime's share of fills, of notional, of spread earned and of
adverse selection paid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.models.mcs import stationary_bootstrap_indices

FloatArray = npt.NDArray[np.float64]
GROUPS = ("latency_arb", "forced", "wallet", "state")
PLAN_GROUPS = {"latency_arb": ("latency_arb",), "forced": ("forced",),
               "residual": ("wallet", "state")}
_PREFIXES = {
    "latency_arb": ("cex_", "race_lost_", "fee_", "speed_"),
    "forced": ("forced_", "fc_"),
    "wallet": ("taker_tox", "taker_log_n"),
}


def feature_group(column: str) -> str:
    for group, prefixes in _PREFIXES.items():
        if column.startswith(prefixes):
            return group
    return "state"


def feature_groups(columns: Sequence[str]) -> dict[str, list[int]]:
    """Column indices per group (every group present, possibly empty)."""
    out: dict[str, list[int]] = {g: [] for g in GROUPS}
    for i, c in enumerate(columns):
        out[feature_group(c)].append(i)
    return out


def group_contributions(contrib: npt.ArrayLike, groups: Mapping[str, Sequence[int]]
                        ) -> dict[str, FloatArray]:
    """Sum a ``(rows, features + 1)`` contribution matrix by group; the last column
    is the bias (expected value)."""
    c = np.asarray(contrib, dtype=np.float64)
    out = {g: c[:, list(idx)].sum(axis=1) if idx else np.zeros(c.shape[0])
           for g, idx in groups.items()}
    out["bias"] = c[:, -1]
    return out


def _bootstrap_ratio(num: FloatArray, den: FloatArray, n_boot: int, seed: int
                     ) -> tuple[float, float]:
    idx = stationary_bootstrap_indices(num.size, n_boot, mean_block=3.0,
                                       rng=np.random.default_rng(seed))
    ratios = num[idx].sum(axis=1) / den[idx].sum(axis=1)
    lo, hi = np.nanquantile(ratios, [0.025, 0.975])
    return float(lo), float(hi)


def contribution_shares(
    contrib: Mapping[str, npt.ArrayLike],
    days: npt.ArrayLike,
    *,
    mask: npt.ArrayLike | None = None,
    n_boot: int = 2_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Shares of predicted adverse selection by group, over fills predicted worse
    than the baseline (and inside ``mask``), with day-bootstrap intervals."""
    parts = {g: np.asarray(contrib[g], dtype=np.float64) for g in GROUPS if g in contrib}
    total = np.sum(list(parts.values()), axis=0)
    day_arr = np.asarray(days)
    sel = total < 0.0
    if mask is not None:
        sel &= np.asarray(mask, dtype=bool)
    out: dict[str, Any] = {"fills": int(sel.sum()),
                           "mean_predicted_adverse_bps": float(total[sel].mean()) if sel.any()
                           else 0.0}
    if not sel.any():
        return out
    keys, inv = np.unique(day_arr[sel], return_inverse=True)
    den = np.bincount(inv, weights=total[sel], minlength=keys.size).astype(np.float64)
    combos: dict[str, tuple[str, ...]] = {g: (g,) for g in parts}
    combos.update({f"plan_{k}": v for k, v in PLAN_GROUPS.items()
                   if all(g in parts for g in v)})
    shares: dict[str, Any] = {}
    for name, members in combos.items():
        val = np.sum([parts[g][sel] for g in members], axis=0)
        num = np.bincount(inv, weights=val, minlength=keys.size).astype(np.float64)
        entry: dict[str, Any] = {"share": float(num.sum() / den.sum()),
                                 "mean_bps": float(val.mean())}
        if keys.size >= 3:
            entry["bootstrap_ci_95"] = list(_bootstrap_ratio(num, den, n_boot, seed))
        shares[name] = entry
    out["days"] = int(keys.size)
    out["shares"] = shares
    # mean absolute contribution share over every fill in the mask (sign-free reading)
    base = np.ones(total.size, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    absum = {g: float(np.abs(v[base]).sum()) for g, v in parts.items()}
    tot = sum(absum.values())
    out["abs_share_all_fills"] = {g: v / tot if tot > 0 else 0.0 for g, v in absum.items()}
    return out


def realised_regimes(frame: pd.DataFrame, horizon: str, *, cex_bps: float = 2.0
                     ) -> pd.Series:
    """Label each fill: ``stale`` (Binance moved at least ``cex_bps`` against the
    quoted side since the HL mid last changed), ``forced`` (forced flow on either side
    in the previous 60 s), ``stale+forced`` or ``quiet``."""
    gap = frame.get("cex_gap_maker_bps")
    stale = (gap.to_numpy(np.float64) <= -cex_bps) if gap is not None else np.zeros(len(frame), bool)
    f_cols = [c for c in ("forced_same_notional_60000ms", "forced_opp_notional_60000ms")
              if c in frame.columns]
    forced = (frame[f_cols].fillna(0.0).sum(axis=1).to_numpy() > 0.0 if f_cols
              else np.zeros(len(frame), bool))
    label = np.where(stale & forced, "stale+forced",
                     np.where(stale, "stale", np.where(forced, "forced", "quiet")))
    return pd.Series(label, index=frame.index, name="regime")


def realised_decomposition(frame: pd.DataFrame, horizon: str, *, cex_bps: float = 2.0
                           ) -> dict[str, Any]:
    """Where S1's maker PnL comes from, by regime, notional-weighted (USD)."""
    valid = frame[f"markout_bps_{horizon}"].notna() & frame["mid_before"].notna()
    fr = frame[valid]
    notional = (fr["px"] * fr["sz"]).to_numpy(np.float64)
    side = fr["maker_side"].to_numpy(np.float64)
    spread_bps = side * (fr["mid_before"] - fr["px"]).to_numpy(np.float64) / fr[
        "mid_before"].to_numpy(np.float64) * 1e4
    adverse_bps = fr[f"markout_bps_{horizon}"].to_numpy(np.float64)
    spread_usd = spread_bps * notional / 1e4
    adverse_usd = adverse_bps * notional / 1e4
    regime = realised_regimes(fr, horizon, cex_bps=cex_bps).to_numpy()
    tot = {"fills": len(fr), "notional": notional.sum(), "spread": spread_usd.sum(),
           "adverse": adverse_usd.sum()}
    out: dict[str, Any] = {"horizon": horizon, "fills": tot["fills"],
                           "notional_usd": float(tot["notional"]),
                           "spread_usd": float(tot["spread"]),
                           "adverse_usd": float(tot["adverse"]), "regimes": {}}
    for name in ("quiet", "stale", "forced", "stale+forced"):
        m = regime == name
        out["regimes"][name] = {
            "fill_share": float(m.mean()) if m.size else 0.0,
            "notional_share": float(notional[m].sum() / tot["notional"]) if tot["notional"] else 0.0,
            "adverse_share": float(adverse_usd[m].sum() / tot["adverse"]) if tot["adverse"] else 0.0,
            "spread_bps": float(spread_usd[m].sum() / notional[m].sum() * 1e4) if m.any() else 0.0,
            "adverse_bps": float(adverse_usd[m].sum() / notional[m].sum() * 1e4) if m.any() else 0.0,
            "net_usd": float(spread_usd[m].sum() + adverse_usd[m].sum()),
        }
    return out
