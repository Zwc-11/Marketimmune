"""Quoting strategies for the block-accurate simulator (``marketimmune.sim.engine``).

Every strategy decides on information known after a block: the book's top, our position, and
signals aligned to the Silver L2 rows and computed from data up to that block (Binance read with
its feed latency). The plan's model strategies (S2, S3) pull on quote-time models
(``marketimmune.sim.signals``), trained without the fill-time columns (the trade's size and the
taker's wallet score), which are not known before a fill.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from marketimmune.sim.engine import NO_QUOTE, Strategy

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]
IntArray = npt.NDArray[np.int64]


@dataclass(slots=True)
class TouchQuoter:
    """S1, inventory only: join the best bid and ask and stop adding to a position that has
    reached ``max_position`` (coin units)."""

    max_position: float

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        return (bid if position < self.max_position else NO_QUOTE, ask if position > -self.max_position else NO_QUOTE)


class SidePuller:
    """A base strategy with a side pulled on the L2 rows where ``pull_bid`` / ``pull_ask`` is set."""

    def __init__(self, base: Strategy, pull_bid: BoolArray, pull_ask: BoolArray) -> None:
        assert pull_bid.shape == pull_ask.shape, f"{pull_bid.shape=} {pull_ask.shape=}"
        self.base = base
        self.pull_bid = pull_bid.tolist()
        self.pull_ask = pull_ask.tolist()

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        b, a = self.base.quotes(row, ts, bid, ask, position)
        return (NO_QUOTE if self.pull_bid[row] else b, NO_QUOTE if self.pull_ask[row] else a)


class StaleQuotePuller(SidePuller):
    """S1 plus the model-free rule: pull a side while Binance has moved ``threshold_bps`` against
    it since the Hyperliquid mid last changed (``cex_gap_maker_bps <= -threshold``).

    ``bid_gap`` and ``ask_gap`` are ``cex_gap_maker_bps`` per L2 row for a maker on that side; NaN
    (no Binance price yet) keeps quoting.
    """

    def __init__(self, base: Strategy, bid_gap: FloatArray, ask_gap: FloatArray, threshold_bps: float) -> None:
        # NOTE: NaN compares False, so a missing signal never pulls
        super().__init__(base, bid_gap <= -threshold_bps, ask_gap <= -threshold_bps)


class QuantilePuller(SidePuller):
    """S2/S3: pull a side while the quote-time model's 10th-percentile markout of that side's next
    fill is below ``-limit_bps`` (``simulate_policy``'s quantile rule). NaN keeps quoting."""

    def __init__(self, base: Strategy, bid_q10: FloatArray, ask_q10: FloatArray, limit_bps: float) -> None:
        super().__init__(base, bid_q10 < -limit_bps, ask_q10 < -limit_bps)


class QuantileBacker:
    """S2/S3 that steps back instead of pulling: while the quote-time q10 of a side's next fill is
    below ``-limit_bps``, that side quotes at the book's second-best price, behind the touch's
    queue, and stops quoting only when the side shows a single level. ``bid2``/``ask2`` are the
    second-best prices (ticks, 0 when missing) of each L2 row. NaN keeps quoting at the touch."""

    def __init__(self, base: Strategy, bid_q10: FloatArray, ask_q10: FloatArray, limit_bps: float, bid2: IntArray, ask2: IntArray) -> None:
        assert bid_q10.shape == ask_q10.shape == bid2.shape == ask2.shape, f"{bid_q10.shape=} {ask_q10.shape=} {bid2.shape=} {ask2.shape=}"
        self.base = base
        # The price each side steps back to, -1 where it stays at the touch. array("q") indexes at list
        # speed in 8 bytes a row; lists of ints cost ~36 a row and ran the large ETH days out of 4 GB.
        self.back_bid = array("q", np.where(bid_q10 < -limit_bps, bid2, -1).astype(np.int64).tobytes())
        self.back_ask = array("q", np.where(ask_q10 < -limit_bps, ask2, -1).astype(np.int64).tobytes())

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        b, a = self.base.quotes(row, ts, bid, ask, position)
        back_bid, back_ask = self.back_bid[row], self.back_ask[row]
        if back_bid >= 0 and b != NO_QUOTE:
            b = back_bid or NO_QUOTE
        if back_ask >= 0 and a != NO_QUOTE:
            a = back_ask or NO_QUOTE
        return b, a
