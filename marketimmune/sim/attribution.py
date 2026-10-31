"""Maker PnL attribution for simulated fills: spread, fees, adverse selection, inventory, hedge.

For a fill of ``qty`` at ``px`` on side ``s`` (+1 bought on our bid, -1 sold on our ask), with
``m0`` the mid before the fill's block, ``m_h`` the mid ``h`` later and ``m_T`` the day's last
mid, in USD:

    spread    = s * (m0 - px) * qty            the half-spread earned
    adverse   = s * (m_h - m0) * qty           the markout at the horizon
    inventory = s * (m_T - m_h) * qty          holding the position after the horizon
    fee       = -maker_fee_bps * px * qty      negative fee = rebate
    hedge     = -|position_T| * (half spread_T + taker_fee_bps * m_T)   flatten at the day's end

The first three sum to ``s * (m_T - px) * qty``, the fill's mark-to-market at the day's last mid,
so the five components add up to the day's PnL after flattening. Per filled dollar they are
divided by the day's traded notional (bps).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.sim.engine import MakerResult
from marketimmune.sources.albers_l4 import PX_DECIMALS

BPS = 10_000.0
COMPONENTS = ("spread", "adverse", "inventory", "fee", "hedge", "total")
PX_SCALE = float(10**PX_DECIMALS)
IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Costs:
    maker_fee_bps: float = 1.5  # Hyperliquid perps, base tier
    taker_fee_bps: float = 4.5
    horizon_ns: int = 1_000_000_000  # the adverse-selection window (the ladder's 1 s label)


def attribute_day(result: MakerResult, l2_ts: IntArray, bid_px: IntArray, ask_px: IntArray, costs: Costs) -> dict[str, Any]:
    """One maker-day: USD and per-filled-dollar bps for each component, plus fill counts.

    ``bid_px``/``ask_px`` are the best prices (ticks) of the day's L2 rows at ``l2_ts``.
    """
    mid = (bid_px + ask_px) / 2.0 / PX_SCALE
    ts = np.asarray(result.ts, dtype=np.int64)
    side = np.asarray(result.side, dtype=np.float64)
    px = np.asarray(result.px, dtype=np.float64) / PX_SCALE
    qty = np.asarray(result.qty, dtype=np.float64)
    before = np.searchsorted(l2_ts, ts, side="left") - 1
    assert ts.size == 0 or before.min() >= 0, "a fill before the first L2 row"
    m0 = mid[before]
    m_h = mid[np.searchsorted(l2_ts, ts + costs.horizon_ns, side="right") - 1]
    m_t = float(mid[-1])
    notional = float(np.sum(px * qty))
    position = float(np.sum(side * qty))
    half_spread = (ask_px[-1] - bid_px[-1]) / 2.0 / PX_SCALE
    usd = {
        "spread": float(np.sum(side * (m0 - px) * qty)),
        "adverse": float(np.sum(side * (m_h - m0) * qty)),
        "inventory": float(np.sum(side * (m_t - m_h) * qty)),
        "fee": -costs.maker_fee_bps / BPS * notional,
        "hedge": -abs(position) * (half_spread + costs.taker_fee_bps / BPS * m_t),
    }
    usd["total"] = sum(usd.values())
    out: dict[str, Any] = {
        "fills": int(ts.size),
        "buys": int(np.count_nonzero(side > 0)),
        "notional_usd": notional,
        "end_position": position,
        "placed": result.placed,
        "cancelled": result.cancelled,
        "rejected": result.rejected,
        "pnl_usd": usd["total"],
    }
    for name, value in usd.items():
        out[f"{name}_usd"] = value
        out[f"{name}_bps"] = value / notional * BPS if notional > 0 else 0.0
    return out
