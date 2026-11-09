"""Wallet positions rolled forward from fills (v3 plan, B.3 step 2).

Every Hyperliquid fill states each wallet's position *before* it
(``start_pos``). So for any wallet that trades, its position after each fill is
exact without a snapshot: ``start_pos + delta``. Chaining a wallet's fills also
tests completeness: the next fill's ``start_pos`` must equal the previous fill's
``start_pos + delta``. A break means the position changed with no fill on this
coin's tape: an off-book backstop liquidation, auto-deleveraging, or a missing
trade. That rate is what the forecaster's position book will inherit.

Entry price is tracked as average cost: opening or flipping sets it to the fill
price, adding averages it, reducing leaves it. After a chain break the entry is
unknown (NaN) until the wallet is next flat, because the unseen change had an
unseen price. Liquidation prices need margin and leverage, which fills do not
carry; they come from position snapshots (Hydromancer) or ``clearinghouseState``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

TOLERANCE = 1e-6  # sizes are decimal strings with <= 8 decimals; float noise sits far below


@dataclass
class WalletState:
    position: float = 0.0
    entry_px: float = math.nan
    last_ts_ms: int = 0


@dataclass
class RollStats:
    events: int = 0
    wallets: int = 0
    chained: int = 0
    breaks: int = 0
    break_abs_sizes: list[float] = field(default_factory=list)
    liquidation_events: int = 0
    liquidation_reducing: int = 0
    unknown_entry_events: int = 0

    def to_dict(self) -> dict[str, Any]:
        sizes = np.asarray(self.break_abs_sizes) if self.break_abs_sizes else np.zeros(0)
        return {
            "events": self.events,
            "wallets": self.wallets,
            "chained_pairs": self.chained,
            "chain_breaks": self.breaks,
            "chain_break_share": self.breaks / self.chained if self.chained else None,
            "break_abs_size_p50": float(np.median(sizes)) if sizes.size else None,
            "break_abs_size_p95": float(np.quantile(sizes, 0.95)) if sizes.size else None,
            "liquidation_events": self.liquidation_events,
            "liquidation_reducing_share": (self.liquidation_reducing / self.liquidation_events if self.liquidation_events else None),
            "unknown_entry_share": self.unknown_entry_events / self.events if self.events else None,
        }


FILL_COLUMNS = (
    "ts_ms",
    "px",
    "sz",
    "taker_side",
    "maker_user",
    "taker_user",
    "maker_start_position",
    "taker_start_position",
    "liquidation",
)


def wallet_events(fills: pd.DataFrame) -> pd.DataFrame:
    """One row per (fill, wallet side) from Silver fills, in (time, fill, role) order.

    ``delta`` is the wallet's signed size change; ``forced`` marks the side the liquidation
    engine traded for (the taker of a liquidation fill)."""
    order = np.argsort(fills["ts_ms"].to_numpy(dtype=np.int64), kind="stable")
    rows = np.repeat(order, 2)  # maker, then taker ("maker" < "taker")
    taker = np.tile([False, True], len(fills))

    def pick(column: str, dtype: type) -> npt.NDArray[Any]:
        maker_col, taker_col = (fills[f"{role}_{column}"].to_numpy(dtype=dtype)[rows] for role in ("maker", "taker"))
        return np.asarray(np.where(taker, taker_col, maker_col), dtype=dtype)

    taker_sign = np.where(fills["taker_side"].to_numpy()[rows] == "B", 1.0, -1.0)
    events = pd.DataFrame(
        {
            "ts_ms": fills["ts_ms"].to_numpy(dtype=np.int64)[rows],
            "seq": rows.astype(np.int64),
            "wallet": pick("user", object),
            "start_pos": pick("start_position", np.float64),
            "delta": np.where(taker, taker_sign, -taker_sign) * fills["sz"].to_numpy(dtype=np.float64)[rows],
            "px": fills["px"].to_numpy(dtype=np.float64)[rows],
            "role": np.where(taker, "taker", "maker").astype(object),
            "forced": fills["liquidation"].fillna(False).to_numpy(dtype=bool)[rows] & taker,
        }
    )
    return events[events["wallet"].notna() & events["start_pos"].notna()].reset_index(drop=True)


def roll_positions(
    events: pd.DataFrame,
    state: dict[str, WalletState] | None = None,
) -> tuple[pd.DataFrame, dict[str, WalletState], RollStats]:
    """Roll positions forward through ``events`` (time-ordered), carrying ``state``
    across calls so a month can be processed a day at a time."""
    state = {} if state is None else state
    stats = RollStats()
    n = len(events)
    pos_after = np.empty(n)
    entry_after = np.empty(n)
    chain_ok = np.ones(n, dtype=bool)
    columns = (events[c].tolist() for c in ("wallet", "start_pos", "delta", "px", "ts_ms", "forced"))
    for i, (w, s0, d, px, ts, forced) in enumerate(zip(*columns, strict=True)):
        st = state.get(w)
        if st is None:
            # First sight of the wallet: the fill's start_pos is the truth, entry unknown
            # unless it opens from flat below.
            st = state[w] = WalletState(position=s0)
        else:
            stats.chained += 1
            if abs(st.position - s0) > TOLERANCE * max(1.0, abs(s0)):
                stats.breaks += 1
                stats.break_abs_sizes.append(abs(st.position - s0))
                chain_ok[i] = False
                st.entry_px = math.nan  # the unseen change had an unseen price
            st.position = s0
        new = s0 + d
        if abs(s0) <= TOLERANCE or ((s0 > 0) != (new > 0) and abs(new) > TOLERANCE):
            # opening from flat, or flipping through zero: the remainder is at this price
            st.entry_px = px if abs(new) > TOLERANCE else math.nan
        elif abs(new) > abs(s0):
            if not math.isnan(st.entry_px):
                st.entry_px = (st.entry_px * abs(s0) + px * abs(d)) / abs(new)
        elif abs(new) <= TOLERANCE:
            st.entry_px = math.nan
        if forced:
            stats.liquidation_events += 1
            stats.liquidation_reducing += int(abs(new) < abs(s0) - TOLERANCE)
        st.position = new
        st.last_ts_ms = ts
        pos_after[i] = new
        entry_after[i] = st.entry_px
        stats.unknown_entry_events += int(abs(new) > TOLERANCE and math.isnan(st.entry_px))
    stats.events = n
    stats.wallets = int(events["wallet"].nunique())
    out = events.assign(position_after=pos_after, entry_px_after=entry_after, chain_ok=chain_ok)
    return out, state, stats


def open_positions(state: Mapping[str, WalletState]) -> pd.DataFrame:
    """Non-flat wallets: position, average entry (NaN if unknown), last fill time."""
    rows = [
        {"wallet": w, "position": s.position, "entry_px": s.entry_px, "last_ts_ms": s.last_ts_ms}
        for w, s in state.items()
        if abs(s.position) > TOLERANCE
    ]
    return pd.DataFrame(rows, columns=["wallet", "position", "entry_px", "last_ts_ms"])


def long_short_open_interest(state: Mapping[str, WalletState]) -> dict[str, float]:
    """Sum of long and of short sizes over the wallets seen (a lower bound on OI)."""
    pos = np.fromiter((s.position for s in state.values()), dtype=np.float64)
    return {"long": float(pos[pos > 0].sum()), "short": float(-pos[pos < 0].sum())}
