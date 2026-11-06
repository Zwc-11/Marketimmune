"""The paper strategies: what each quotes, from what the December 2025 and A1 results suggested.

Makers quote ``qty`` at the best bid and ask and stop quoting a side at ``max_position``:

- ``Touch`` (December's S1): always both sides. The control.
- ``GapPull`` (December's stale rule): pull the side the demeaned Coinbase gap says is about to be
  picked off: the asks when the gap is above ``threshold_bps`` (Coinbase higher), the bids below
  minus it.
- ``ModelPull`` (December's S2, live): pull the side the walk-forward model's next-second move
  points at, beyond ``threshold_bps``. Before the first fit it quotes like ``Touch``.

- ``Improve``: when the spread is at least 3 ticks, quote one tick inside it on both sides, a new
  price level with nothing ahead; otherwise like ``Touch``. With ``gap_bps`` it also pulls like
  ``GapPull``. For the coins whose spread is several ticks wide (BCH, LTC, DOGE).

``GapTaker`` is the other side of the trade: when the gap reaches ``threshold_bps`` it buys (or
sells) ``qty`` at the touch, paying the taker fee, and closes ``hold_ms`` after the fill.
"""

from __future__ import annotations

from typing import Protocol

from marketimmune.paper.signals import CoinState, on_tick


class Quoter(Protocol):
    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]: ...


class Touch:
    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]:
        if coin.top is None:
            return None, None
        return (coin.top.bid if position < max_position else None, coin.top.ask if position > -max_position else None)


class GapPull(Touch):
    def __init__(self, threshold_bps: float) -> None:
        self.threshold_bps = threshold_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]:
        bid, ask = super().quotes(coin, local_ms, position, max_position)
        gap = coin.gap()
        if gap is not None and gap > self.threshold_bps:
            ask = None
        if gap is not None and gap < -self.threshold_bps:
            bid = None
        return bid, ask


class ModelPull(Touch):
    def __init__(self, threshold_bps: float) -> None:
        self.threshold_bps = threshold_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]:
        bid, ask = super().quotes(coin, local_ms, position, max_position)
        move = coin.predict(local_ms)
        if move is not None and move > self.threshold_bps:
            ask = None
        if move is not None and move < -self.threshold_bps:
            bid = None
        return bid, ask


class Improve(Touch):
    def __init__(self, gap_bps: float | None = None) -> None:
        self.gap_bps = gap_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]:
        bid, ask = super().quotes(coin, local_ms, position, max_position)
        tick, top = coin.tick, coin.top
        if tick is not None and top is not None and top.ask - top.bid >= 2.5 * tick:
            bid = None if bid is None else on_tick(top.bid + tick, tick)
            ask = None if ask is None else on_tick(top.ask - tick, tick)
        gap = coin.gap() if self.gap_bps is not None else None
        if gap is not None and self.gap_bps is not None:
            if gap > self.gap_bps:
                ask = None
            if gap < -self.gap_bps:
                bid = None
        return bid, ask


LIVE_STRATEGIES = ("touch", "gap@1", "gap@2", "model@0.5", "model@1", "improve", "improve+gap@2", "taker@6", "taker@10")


def quoter(name: str) -> Quoter:
    """A maker strategy from its name: ``touch``, ``gap@<bps>``, ``model@<bps>``, ``improve`` or
    ``improve+gap@<bps>``."""
    kind, _, arg = name.partition("@")
    if name == "touch":
        return Touch()
    if name == "improve":
        return Improve()
    if kind == "gap":
        return GapPull(float(arg))
    if kind == "model":
        return ModelPull(float(arg))
    if kind == "improve+gap":
        return Improve(float(arg))
    raise AssertionError(f"unknown maker strategy {name!r}")


def taker_threshold(name: str) -> float | None:
    """``taker@<bps>`` -> its gap threshold; None for a maker."""
    kind, _, arg = name.partition("@")
    return float(arg) if kind == "taker" else None
