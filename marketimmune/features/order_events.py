"""Rung L3a (fee-free) and a realised forced-flow input from order events.

Built from the Silver order events the Albers rebuild writes
(``marketimmune.sources.albers_l4``):

* **Lost races** (``kind == "ioc_unfilled"`` and ``marketable_at_block_start``): an
  IOC whose limit crossed the opposite best when its block began, yet went
  unfilled, so the quote it aimed at was cancelled or taken first inside the
  block. A burst of lost races aimed at one side says quotes there are being
  sniped. It is the pre-fee analogue of v3's missed-race count: the same race,
  without the priority fee that later prices it.
* **Forced flow** (``kind == "liquidation"``): liquidation-engine market orders,
  as notional per side in recent windows. This is the realised version of
  Workstream B's input; the forecast from the position book comes later.

Sides are from the maker's view. A maker filled on its bid (``maker_side = +1``)
is hit by sells, so "same side" means IOC sells aimed at bids and forced sells
into bids; "opp" is the other side and serves as the placebo.

Every window is ``[t - w, t)`` on event time: an event in the fill's own block
(same timestamp) is excluded, which is the plan's one-block lag.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
RACE_WINDOWS_MS = (250.0, 1_000.0, 5_000.0)
FORCED_WINDOWS_MS = (1_000.0, 5_000.0, 60_000.0)


def race_feature_columns(windows_ms: Sequence[float] = RACE_WINDOWS_MS) -> tuple[str, ...]:
    return tuple(
        f"race_lost_{side}_{kind}_{int(w)}ms"
        for w in windows_ms
        for side in ("same", "opp")
        for kind in ("n", "notional")
    )


def forced_feature_columns(windows_ms: Sequence[float] = FORCED_WINDOWS_MS) -> tuple[str, ...]:
    return tuple(
        f"forced_{side}_notional_{int(w)}ms" for w in windows_ms for side in ("same", "opp")
    )


RACE_FEATURE_COLUMNS = race_feature_columns()
FORCED_FEATURE_COLUMNS = forced_feature_columns()


@dataclass(frozen=True, slots=True)
class _Stream:
    """Event times (ms, sorted) with prefix sums of counts and notional."""

    ts: FloatArray
    cum_n: FloatArray
    cum_notional: FloatArray

    @classmethod
    def build(cls, ts_ms: FloatArray, notional: FloatArray) -> _Stream:
        order = np.argsort(ts_ms, kind="stable")
        ts = ts_ms[order]
        return cls(
            ts=ts,
            cum_n=np.concatenate(([0.0], np.arange(1, ts.size + 1, dtype=np.float64))),
            cum_notional=np.concatenate(([0.0], np.cumsum(notional[order]))),
        )

    def window(self, t: FloatArray, w: float) -> tuple[FloatArray, FloatArray]:
        """Count and notional of events with ``t - w <= ts < t``."""
        hi = np.searchsorted(self.ts, t, side="left")
        lo = np.searchsorted(self.ts, t - w, side="left")
        return self.cum_n[hi] - self.cum_n[lo], self.cum_notional[hi] - self.cum_notional[lo]


def _streams(events: Mapping[str, npt.ArrayLike], kind: str) -> dict[str, _Stream]:
    """Two streams for ``kind``: events aimed at bids (sells) and at asks (buys)."""
    ts = np.asarray(events["ts_ms"], dtype=np.float64)
    kinds = np.asarray(events["kind"], dtype=object)
    is_ask = np.asarray(events["is_ask"], dtype=bool)
    px = np.asarray(events["opposite_best_px"], dtype=np.float64)
    if kind == "race":
        mask = (kinds == "ioc_unfilled") & np.asarray(
            events["marketable_at_block_start"], dtype=bool
        )
        qty = np.asarray(events["sz"], dtype=np.float64)  # the unfilled remainder
    else:
        mask = kinds == "liquidation"
        qty = np.asarray(events["orig_sz"], dtype=np.float64) - np.asarray(
            events["sz"], dtype=np.float64
        )
    notional = np.nan_to_num(qty * px, nan=0.0)
    return {
        "bid": _Stream.build(ts[mask & is_ask], notional[mask & is_ask]),
        "ask": _Stream.build(ts[mask & ~is_ask], notional[mask & ~is_ask]),
    }


def order_event_features(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    events: Mapping[str, npt.ArrayLike],
    *,
    race_windows_ms: Sequence[float] = RACE_WINDOWS_MS,
    forced_windows_ms: Sequence[float] = FORCED_WINDOWS_MS,
) -> dict[str, FloatArray]:
    """Lost-race and forced-flow features for each fill.

    ``events`` holds columns ``ts_ms``, ``kind``, ``is_ask``, ``sz``, ``orig_sz``,
    ``opposite_best_px`` and ``marketable_at_block_start`` (Silver order events).
    """
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    bid_side = np.asarray(maker_side, dtype=np.float64) > 0  # maker's bid was hit
    out: dict[str, FloatArray] = {}
    for prefix, kind, windows in (
        ("race_lost", "race", race_windows_ms),
        ("forced", "forced", forced_windows_ms),
    ):
        streams = _streams(events, kind)
        for w in windows:
            at_bid = streams["bid"].window(t, w)
            at_ask = streams["ask"].window(t, w)
            same = [np.where(bid_side, b, a) for b, a in zip(at_bid, at_ask, strict=True)]
            opp = [np.where(bid_side, a, b) for b, a in zip(at_bid, at_ask, strict=True)]
            if prefix == "race_lost":
                out[f"race_lost_same_n_{int(w)}ms"] = same[0]
                out[f"race_lost_same_notional_{int(w)}ms"] = same[1]
                out[f"race_lost_opp_n_{int(w)}ms"] = opp[0]
                out[f"race_lost_opp_notional_{int(w)}ms"] = opp[1]
            else:
                out[f"forced_same_notional_{int(w)}ms"] = same[1]
                out[f"forced_opp_notional_{int(w)}ms"] = opp[1]
    return out


def verify_order_event_features_no_lookahead(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    events: Mapping[str, npt.ArrayLike],
    *,
    sample: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """Recompute sampled fills with every event at or after the fill deleted."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    cols = {k: np.asarray(v) for k, v in events.items()}
    full = order_event_features(t, side, cols)
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(t.size), min(sample, t.size)))
    ev_ts = cols["ts_ms"].astype(np.float64)
    mismatched = 0
    worst = 0.0
    for i in picks:
        keep = ev_ts < t[i]
        cut = order_event_features(t[i : i + 1], side[i : i + 1], {k: v[keep] for k, v in cols.items()})
        diff = max(abs(float(full[c][i]) - float(cut[c][0])) for c in full)
        worst = max(worst, diff)
        mismatched += int(not math.isclose(diff, 0.0, abs_tol=1e-6))
    return {"passed": bool(picks) and mismatched == 0, "n_checked": len(picks),
            "n_mismatched": mismatched, "max_abs_diff": worst}
