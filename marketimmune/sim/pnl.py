"""Maker PnL attribution under a quote/skip policy (v3 plan, Integration: the economic test).

**Fill-filter approximation.** Every historical maker fill is an opportunity the
simulated maker could have taken at the same price; a policy decides, with
information strictly before the fill, whether to have been quoting. This ignores
queue position and the price impact of the maker's own quotes, so fill counts are
an upper bound; the block-accurate replay with injected quotes (``crates/``)
replaces it later. What it measures well is the *difference* between policies on
the same opportunities.

Per filled dollar, in bps, for horizon ``h`` (the maker hedges ``h`` seconds
after the fill at the then mid, paying ``hedge_cost_bps``):

    spread    = side * (mid_before - px) / mid_before        (half-spread earned)
    adverse   = side * (mid_{t+h} - mid_before) / mid_before (= Gold markout_bps_h)
    fee       = -maker_fee_bps
    hedge     = -hedge_cost_bps
    total     = spread + adverse + fee + hedge

Daily totals are notional-weighted (each fill is ``notional_usd``), so a day's
"bps per filled dollar" is the mean over the fills the policy took.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.models.compare import diebold_mariano, stationary_bootstrap_ci

BPS = 10_000.0
COMPONENTS = ("spread", "adverse", "fee", "hedge", "total")


@dataclass(frozen=True, slots=True)
class CostModel:
    maker_fee_bps: float = 0.0
    hedge_cost_bps: float = 0.0
    notional_usd: float = 1_000.0


def fill_components(frame: pd.DataFrame, horizon: str, costs: CostModel) -> pd.DataFrame:
    """Per-fill PnL components in bps from Gold training rows."""
    need = ["px", "maker_side", "mid_before", f"markout_bps_{horizon}"]
    missing = [c for c in need if c not in frame.columns]
    if missing:
        raise ValueError(f"Gold rows missing columns: {missing}")
    side = frame["maker_side"].to_numpy(dtype=np.float64)
    mid = frame["mid_before"].to_numpy(dtype=np.float64)
    px = frame["px"].to_numpy(dtype=np.float64)
    out = pd.DataFrame(index=frame.index)
    out["spread"] = side * (mid - px) / mid * BPS
    out["adverse"] = frame[f"markout_bps_{horizon}"].to_numpy(dtype=np.float64)
    out["fee"] = -costs.maker_fee_bps
    out["hedge"] = -costs.hedge_cost_bps
    out["total"] = out["spread"] + out["adverse"] + out["fee"] + out["hedge"]
    return out


def daily_policy_pnl(
    components: pd.DataFrame,
    days: npt.ArrayLike,
    take: npt.ArrayLike,
    costs: CostModel,
) -> pd.DataFrame:
    """Per day: fills taken, notional, bps per filled dollar by component, and USD."""
    taken = np.asarray(take, dtype=bool)
    frame = components.loc[taken].copy()
    frame["day"] = np.asarray(days)[taken]
    if frame.empty:
        return pd.DataFrame(columns=["day", "fills", "notional_usd", *COMPONENTS, "pnl_usd"])
    agg = frame.groupby("day", sort=True)[list(COMPONENTS)].mean()
    agg["fills"] = frame.groupby("day", sort=True).size()
    agg["notional_usd"] = agg["fills"] * costs.notional_usd
    agg["pnl_usd"] = agg["total"] * agg["notional_usd"] / BPS
    return agg.reset_index()[["day", "fills", "notional_usd", *COMPONENTS, "pnl_usd"]]


def summarise(daily: pd.DataFrame) -> dict[str, Any]:
    """Whole-period bps per filled dollar (fill-weighted) and daily spread of the total."""
    if daily.empty:
        return {"days": 0, "fills": 0}
    w = daily["fills"].to_numpy(dtype=np.float64)
    out: dict[str, Any] = {
        "days": len(daily),
        "fills": int(w.sum()),
        "notional_usd": float(daily["notional_usd"].sum()),
        "pnl_usd": float(daily["pnl_usd"].sum()),
    }
    for c in COMPONENTS:
        out[f"{c}_bps"] = float(np.average(daily[c], weights=w))
    totals = daily["total"].to_numpy(dtype=np.float64)
    out["total_bps_daily_min"] = float(totals.min())
    out["total_bps_daily_max"] = float(totals.max())
    if len(daily) >= 3:
        lo, hi = stationary_bootstrap_ci(totals)
        out["total_bps_daily_mean_ci95"] = [lo, hi]
    return out


def compare_policies(base: pd.DataFrame, challenger: pd.DataFrame) -> dict[str, Any]:
    """Daily difference in USD PnL (challenger minus base) on matching days."""
    merged = base[["day", "pnl_usd"]].merge(
        challenger[["day", "pnl_usd"]], on="day", suffixes=("_base", "_challenger")
    )
    d = (merged["pnl_usd_challenger"] - merged["pnl_usd_base"]).to_numpy(dtype=np.float64)
    out: dict[str, Any] = {"days": len(d), "mean_daily_usd": float(d.mean()) if d.size else None,
                           "days_better": int((d > 0).sum())}
    if d.size >= 3:
        out["diebold_mariano"] = diebold_mariano(-d).to_dict()  # loss = -PnL difference
        lo, hi = stationary_bootstrap_ci(d)
        out["bootstrap_ci_95_usd"] = [lo, hi]
    return out


def quantile_pull_policy(q_low: npt.ArrayLike, limit_bps: float) -> npt.NDArray[np.bool_]:
    """The plan's rule: quote unless the predicted low-quantile markout is below ``-limit``."""
    q = np.asarray(q_low, dtype=np.float64)
    out: npt.NDArray[np.bool_] = ~(q < -limit_bps)  # NaN (no prediction) keeps quoting
    return out


def probability_skip_policy(prob: npt.ArrayLike, threshold: float) -> npt.NDArray[np.bool_]:
    """Quote unless the classifier's toxic probability is at or above ``threshold``."""
    p = np.asarray(prob, dtype=np.float64)
    out: npt.NDArray[np.bool_] = ~(p >= threshold)
    return out


def rule_pull_policy(values: npt.ArrayLike, op: str, threshold: float) -> npt.NDArray[np.bool_]:
    """Model-free rule on one pre-trade column: pull when ``value <op> threshold``
    (``le``: at or below, ``ge``: at or above). Missing values keep quoting.

    For example ``cex_gap_maker_bps le -2``: Binance has already moved 2 bps
    against the side being quoted since the Hyperliquid mid last changed (read with
    the 300 ms feed latency), so cancel. Hyperliquid runs cancels before takers
    inside a block, so a cancel sent on that information wins the race unless the
    taker's order is in an earlier block; the fill filter assumes it wins."""
    v = np.asarray(values, dtype=np.float64)
    if op == "le":
        pull = v <= threshold
    elif op == "ge":
        pull = v >= threshold
    else:
        raise ValueError(f"op must be 'le' or 'ge', not {op!r}")
    out: npt.NDArray[np.bool_] = ~pull
    return out


def policy_mask(frame: pd.DataFrame, spec: Mapping[str, Any]) -> npt.NDArray[np.bool_]:
    """``{"kind": "all"}``, ``{"kind": "quantile", "column": "q10", "limit_bps": 2}``,
    ``{"kind": "prob", "column": "prob", "threshold": 0.6}`` or
    ``{"kind": "rule", "column": "cex_gap_maker_bps", "op": "le", "threshold": -2}``."""
    kind = spec.get("kind", "all")
    if kind == "all":
        return np.ones(len(frame), dtype=bool)
    if kind == "quantile":
        return quantile_pull_policy(frame[spec["column"]], float(spec["limit_bps"]))
    if kind == "prob":
        return probability_skip_policy(frame[spec["column"]], float(spec["threshold"]))
    if kind == "rule":
        return rule_pull_policy(frame[spec["column"]], str(spec["op"]), float(spec["threshold"]))
    raise ValueError(f"unknown policy kind {kind!r}")
