"""Pure functions that derive market microstructure values.

Kept dependency-free so they can be unit-tested without Django, parquet,
or any IO. Anything that needs to compute a value from raw market state
goes here.
"""

from __future__ import annotations

from dataclasses import dataclass

from marketimmune.simulator.data_loader import DepthSnapshot


@dataclass(frozen=True, slots=True)
class DerivedQuote:
    """Approximation of bid/ask/spread from aggregated %-from-mid depth.

    Binance's aggregated `bookDepth` parquet does not expose a real L1
    quote. The most accurate honest approximation we can do is to take
    the *inside* aggregated band on each side of mid — typically ±1% —
    and report that as a wide spread. We expose this both as the bid /
    ask anchor for the UI and as the `band_percent` so the cockpit can
    label it correctly (rather than pretending it is L1).
    """

    bid: float
    ask: float
    spread: float
    band_percent: float


def derive_quote_from_depth(
    mid: float, snapshot: DepthSnapshot | None, fallback_band: float = 1.0
) -> DerivedQuote:
    """Derive a quote from the closest aggregated depth ladder.

    Args:
        mid: Mid price (we use kline close as the anchor).
        snapshot: Closest aggregated depth ladder, or `None` when no
            depth file was available for the replay date.
        fallback_band: Used when no snapshot is provided.

    Returns:
        DerivedQuote with bid/ask anchored at the inside band of the
        ladder.
    """
    if snapshot is None or mid <= 0:
        bid = mid * (1.0 - fallback_band / 100.0) if mid > 0 else mid
        ask = mid * (1.0 + fallback_band / 100.0) if mid > 0 else mid
        return DerivedQuote(bid=bid, ask=ask, spread=max(ask - bid, 0.0), band_percent=fallback_band)

    bid_pct = max(
        (lvl.percentage for lvl in snapshot.levels if lvl.percentage < 0),
        default=-fallback_band,
    )
    ask_pct = min(
        (lvl.percentage for lvl in snapshot.levels if lvl.percentage > 0),
        default=fallback_band,
    )
    bid = mid * (1.0 + bid_pct / 100.0)
    ask = mid * (1.0 + ask_pct / 100.0)
    band = max(abs(bid_pct), abs(ask_pct))
    return DerivedQuote(bid=bid, ask=ask, spread=max(ask - bid, 0.0), band_percent=band)
