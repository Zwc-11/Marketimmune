"""Hyperliquid margin tiers and the liquidation price (plan B.1, B.3).

From the docs (margin tiers and liquidations pages, read 2026-10-30; tiers can
change, and the pages carry no history, so December 2025 values are assumed
equal to these):

* Maintenance margin rate is half the initial margin rate at the tier's maximum
  leverage ``L``: ``1 / (2 L)``, 2.5% at 20x. A higher tier's maintenance
  deduction accumulates the rate change at each tier's lower bound, so total
  maintenance margin is continuous in notional.
* ``liq_price = price - side * margin_available / position_size / (1 - l * side)``
  with ``side = +1`` long / ``-1`` short and ``l = 1 / maintenance leverage =
  1 / (2 L)``; ``margin_available`` is account value (cross) or isolated margin,
  minus maintenance margin required.
* Book liquidation sends market orders; above 100k USDC only 20% at a time. If
  equity falls below 2/3 of maintenance margin first, the liquidator vault (the
  backstop) takes the position off-book.

A position opened at the maximum leverage with no extra margin has
``margin_available = N / L - N / (2 L)`` at entry, so its liquidation sits a
fraction ``1 / (2 L - 1)`` below entry for a long and ``1 / (2 L + 1)`` above for a
short: 2.564% and 2.439% at 20x. SOL's observed liquidation distances in December
2025 (median 2.56%, IQR 2.46 to 2.68%) sit on these two values, which is why the
margin-free prior in ``forecaster`` works.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tier:
    lower_usd: float
    max_leverage: float

    @property
    def maintenance_rate(self) -> float:
        return 1.0 / (2.0 * self.max_leverage)


MAINNET_TIERS: dict[str, tuple[Tier, ...]] = {
    "BTC": (Tier(0.0, 40.0), Tier(150e6, 20.0)),
    "ETH": (Tier(0.0, 25.0), Tier(100e6, 15.0)),
    "SOL": (Tier(0.0, 20.0), Tier(70e6, 10.0)),
    "XRP": (Tier(0.0, 20.0), Tier(40e6, 10.0)),
}


def tiers_for(coin: str) -> tuple[Tier, ...]:
    assert coin.upper() in MAINNET_TIERS, f"no margin tiers recorded for {coin!r}; add them from the docs"
    return MAINNET_TIERS[coin.upper()]


def _tier_index(tiers: Sequence[Tier], notional: float) -> int:
    return max(i for i, t in enumerate(tiers) if notional > t.lower_usd or i == 0)


def maintenance_deduction(tiers: Sequence[Tier], k: int) -> float:
    """Sum over tier boundaries up to ``k`` of lower bound x rate increase."""
    return sum(tiers[i].lower_usd * (tiers[i].maintenance_rate - tiers[i - 1].maintenance_rate) for i in range(1, k + 1))


def maintenance_margin(coin: str, notional_usd: float) -> float:
    """``notional * rate - deduction`` for the tier the notional falls in."""
    tiers = tiers_for(coin)
    n = abs(notional_usd)
    k = _tier_index(tiers, n)
    return n * tiers[k].maintenance_rate - maintenance_deduction(tiers, k)


def liquidation_price(coin: str, size: float, price: float, margin_available: float) -> float:
    """The docs' formula; ``l`` from the tier of the position's notional at ``price``
    (the docs use the notional at the liquidation price; within one tier they agree)."""
    assert size != 0.0, "no position"
    side = 1.0 if size > 0 else -1.0
    tiers = tiers_for(coin)
    l_rate = tiers[_tier_index(tiers, abs(size) * price)].maintenance_rate
    return price - side * margin_available / abs(size) / (1.0 - l_rate * side)


def max_leverage_distance(coin: str, side: int, notional_usd: float = 0.0) -> float:
    """Liquidation distance, as a fraction of entry, of a position opened at the
    tier's maximum leverage with no spare margin: ``1/(2L-1)`` long, ``1/(2L+1)`` short."""
    tiers = tiers_for(coin)
    lev = tiers[_tier_index(tiers, notional_usd)].max_leverage
    return 1.0 / (2.0 * lev - 1.0) if side > 0 else 1.0 / (2.0 * lev + 1.0)
