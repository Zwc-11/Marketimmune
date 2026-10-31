"""Quoting strategies for the block-accurate simulator (``marketimmune.sim.engine``).

Every strategy decides on information known after a block: the book's top, our position, and
signals aligned to the Silver L2 rows and computed from data up to that block (Binance read with
its feed latency). The plan's model strategies (S2, S3) need quote-time models. Those are trained
without the fill-time columns (the trade's size and the taker's wallet score), which are not
known before a fill.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from marketimmune.sim.engine import NO_QUOTE

FloatArray = npt.NDArray[np.float64]


@dataclass(slots=True)
class TouchQuoter:
    """S1, inventory only: join the best bid and ask and stop adding to a position that has
    reached ``max_position`` (coin units)."""

    max_position: float

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        return (bid if position < self.max_position else NO_QUOTE, ask if position > -self.max_position else NO_QUOTE)


class StaleQuotePuller:
    """S1 plus the model-free rule: pull a side while Binance has moved ``threshold_bps`` against
    it since the Hyperliquid mid last changed (``cex_gap_maker_bps <= -threshold``).

    ``bid_gap`` and ``ask_gap`` are ``cex_gap_maker_bps`` per L2 row for a maker on that side; NaN
    (no Binance price yet) keeps quoting.
    """

    def __init__(self, base: TouchQuoter, bid_gap: FloatArray, ask_gap: FloatArray, threshold_bps: float) -> None:
        assert bid_gap.shape == ask_gap.shape, f"{bid_gap.shape=} {ask_gap.shape=}"
        self.base = base
        # NOTE: NaN compares False, so a missing signal never pulls
        self.pull_bid = (bid_gap <= -threshold_bps).tolist()
        self.pull_ask = (ask_gap <= -threshold_bps).tolist()

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        b, a = self.base.quotes(row, ts, bid, ask, position)
        return (NO_QUOTE if self.pull_bid[row] else b, NO_QUOTE if self.pull_ask[row] else a)
