"""Rung L3a (fee-free) and a realised forced-flow input from Silver order events.

* **Lost races** (``kind == "ioc_unfilled"`` and ``marketable_at_block_start``): an IOC whose
  limit crossed the opposite best when its block began, yet went unfilled, so the quote it aimed
  at was cancelled or taken first inside the block. A burst of lost races aimed at one side says
  quotes there are being sniped; it is the pre-fee analogue of v3's missed-race count.
* **Forced flow** (``kind == "liquidation"``): liquidation-engine market orders, as notional per
  side in recent windows (the realised version of Workstream B's input).

Sides are from the maker's view. A maker filled on its bid (``maker_side = +1``) is hit by sells,
so "same side" means IOC sells aimed at bids and forced sells into bids; "opp" is the other side
and serves as the placebo. Every window is ``[t - w, t)`` on event time: an event in the fill's
own block (same timestamp) is excluded, which is the plan's one-block lag.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
RACE_WINDOWS_MS = (250, 1_000, 5_000)
FORCED_WINDOWS_MS = (1_000, 5_000, 60_000)
RACE_FEATURE_COLUMNS = tuple(
    f"race_lost_{side}_{kind}_{w}ms" for w in RACE_WINDOWS_MS for side in ("same", "opp") for kind in ("n", "notional")
)
FORCED_FEATURE_COLUMNS = tuple(f"forced_{side}_notional_{w}ms" for w in FORCED_WINDOWS_MS for side in ("same", "opp"))


@dataclass(frozen=True, slots=True)
class _Stream:
    """Event times (ms, sorted) with prefix sums of counts and notional."""

    ts: FloatArray
    cum_n: FloatArray
    cum_notional: FloatArray

    @classmethod
    def build(cls, ts_ms: FloatArray, notional: FloatArray) -> _Stream:
        order = np.argsort(ts_ms, kind="stable")
        return cls(
            ts=ts_ms[order],
            cum_n=np.arange(ts_ms.size + 1, dtype=np.float64),
            cum_notional=np.concatenate(([0.0], np.cumsum(notional[order]))),
        )

    def window(self, t: FloatArray, w: float) -> tuple[FloatArray, FloatArray]:
        """Count and notional of events with ``t - w <= ts < t``."""
        hi = np.searchsorted(self.ts, t, side="left")
        lo = np.searchsorted(self.ts, t - w, side="left")
        return self.cum_n[hi] - self.cum_n[lo], self.cum_notional[hi] - self.cum_notional[lo]


def order_event_features(
    fill_ts_ms: npt.ArrayLike, maker_side: npt.ArrayLike, events: Mapping[str, npt.ArrayLike]
) -> dict[str, FloatArray]:
    """Lost-race and forced-flow features for each fill.

    ``events`` holds the Silver columns ``ts_ms``, ``kind``, ``is_ask``, ``sz``, ``orig_sz``,
    ``opposite_best_px`` and ``marketable_at_block_start``."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    bid_side = np.asarray(maker_side, dtype=np.float64) > 0  # the maker's bid was hit
    ts = np.asarray(events["ts_ms"], dtype=np.float64)
    kind = np.asarray(events["kind"])
    is_ask = np.asarray(events["is_ask"], dtype=bool)  # sells, aimed at bids
    px = np.asarray(events["opposite_best_px"], dtype=np.float64)
    sz = np.asarray(events["sz"], dtype=np.float64)
    race = (kind == "ioc_unfilled") & np.asarray(events["marketable_at_block_start"], dtype=bool)
    forced = kind == "liquidation"
    # a lost race's size is the unfilled remainder; a liquidation's is what filled
    families = (
        ("race_lost", race, sz, RACE_WINDOWS_MS),
        ("forced", forced, np.asarray(events["orig_sz"], dtype=np.float64) - sz, FORCED_WINDOWS_MS),
    )
    out: dict[str, FloatArray] = {}
    for prefix, mask, qty, windows in families:
        notional = np.nan_to_num(qty * px, nan=0.0)
        at_bid = _Stream.build(ts[mask & is_ask], notional[mask & is_ask])
        at_ask = _Stream.build(ts[mask & ~is_ask], notional[mask & ~is_ask])
        for w in windows:
            (bid_n, bid_usd), (ask_n, ask_usd) = at_bid.window(t, w), at_ask.window(t, w)
            if prefix == "race_lost":
                out[f"race_lost_same_n_{w}ms"] = np.where(bid_side, bid_n, ask_n)
                out[f"race_lost_same_notional_{w}ms"] = np.where(bid_side, bid_usd, ask_usd)
                out[f"race_lost_opp_n_{w}ms"] = np.where(bid_side, ask_n, bid_n)
                out[f"race_lost_opp_notional_{w}ms"] = np.where(bid_side, ask_usd, bid_usd)
            else:
                out[f"forced_same_notional_{w}ms"] = np.where(bid_side, bid_usd, ask_usd)
                out[f"forced_opp_notional_{w}ms"] = np.where(bid_side, ask_usd, bid_usd)
    return out


def verify_order_event_features_no_lookahead(
    fill_ts_ms: npt.ArrayLike, maker_side: npt.ArrayLike, events: Mapping[str, npt.ArrayLike], *, sample: int = 200, seed: int = 0
) -> dict[str, Any]:
    """Recompute sampled fills with every event at or after the fill deleted."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    order = np.argsort(np.asarray(events["ts_ms"], dtype=np.float64), kind="stable")
    cols = {k: np.asarray(v)[order] for k, v in events.items()}  # time order: "before t" is a prefix
    cols["kind"] = cols["kind"].astype(str)  # fixed-width strings compare far faster than objects
    ev_ts = cols["ts_ms"].astype(np.float64)
    full = order_event_features(t, side, cols)
    picks = sorted(random.Random(seed).sample(range(t.size), min(sample, t.size)))
    mismatched = 0
    worst = 0.0
    for i in picks:
        k = int(np.searchsorted(ev_ts, t[i], side="left"))
        cut = order_event_features(t[i : i + 1], side[i : i + 1], {c: v[:k] for c, v in cols.items()})
        diff = max(abs(float(full[c][i]) - float(cut[c][0])) for c in full)
        worst = max(worst, diff)
        mismatched += int(not math.isclose(diff, 0.0, abs_tol=1e-6))
    return {"passed": bool(picks) and mismatched == 0, "n_checked": len(picks), "n_mismatched": mismatched, "max_abs_diff": worst}
