"""Paper orders matched against Hyperliquid's real trades, on block time.

There is no L4 feed live, so the queue comes from the public book, as in hftbacktest's risk-averse
model:

- An order reaches the book ``latency_ms`` after the decision (``t_live``) and leaves it
  ``latency_ms`` after a cancel (``t_cancel``). Trades in between can fill it; a trade is placed
  by its block time.
- **Queue.** It joins behind the size the first book message at or after ``t_live`` shows at its
  price. Only eligible trade prints reduce that queue; disappearing displayed size gives
  no cancellation credit.
- **Fills.** A taker trade at the order's price uses up the queue ahead first and fills the order
  with the rest. A trade at a worse price for the taker than the order's means the order's level was
  emptied. Total simulated fills still cannot exceed that print's quantity.
- The order is not in the real book, so real takers never saw it. That flatters it a little: a
  sweep would have stopped one order sooner.

Sides are +1 for a bid (we buy) and -1 for an ask.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

NEVER = 1 << 62


@dataclass(slots=True)
class PaperOrder:
    side: int
    px: float
    qty: float
    t_live: int
    t_cancel: int = NEVER
    queue: float | None = None
    joined: float | None = None  # queue ahead when it joined (for the journal; the fill model uses ``queue``)
    placed: int = 0  # local ms of the decision that sent it
    ctx: dict[str, Any] | None = None  # the signals at that decision, when a journal is kept
    arrived: bool = False
    queue_time: int = -1

    def live_at(self, t_ms: int) -> bool:
        return self.qty > 0 and self.t_live <= t_ms < self.t_cancel

    def see_level(self, t_ms: int, size: float) -> None:
        """A book message at block time ``t_ms`` shows ``size`` at the order's price (0 when the
        price is better than the book's best on that side, so nothing is ahead)."""
        if t_ms < self.t_live:
            return
        if self.queue is None:
            self.joined = size
            self.queue = size
            self.queue_time = t_ms

    def match(self, t_ms: int, px: float, sz: float, taker_buy: bool, seen_size: float | None, max_fill: float = math.inf) -> float:
        """Quantity this order fills from one trade; ``seen_size`` is the latest seen size at the
        order's price, used if no book message has arrived since ``t_live``."""
        if not self.live_at(t_ms) or taker_buy == (self.side > 0):
            return 0.0
        if self.queue_time >= t_ms:
            return 0.0  # a book already reflecting this block cannot establish its earlier queue
        better = px < self.px if self.side > 0 else px > self.px
        if better:
            fill = min(self.qty, sz, max_fill)
            self.queue = 0.0
        elif px == self.px:
            ahead = seen_size if self.queue is None else self.queue
            if ahead is None:
                return 0.0
            if self.joined is None:
                self.joined = ahead
            fill = min(self.qty, max(0.0, sz - ahead), max_fill)
            self.queue = max(0.0, ahead - sz)
        else:
            return 0.0
        self.qty -= fill
        return fill


@dataclass(slots=True)
class Account:
    """Cash, position and fees of one paper strategy in one coin."""

    cash: float = 0.0
    position: float = 0.0
    fees: float = 0.0
    fills: int = 0
    notional: float = 0.0
    log: list[tuple[int, int, float, float, float]] = field(default_factory=list)  # t_ms, side, px, qty, fee rate

    def fill(self, t_ms: int, side: int, px: float, qty: float, fee_rate: float) -> None:
        self.cash -= side * px * qty
        self.position += side * qty
        self.fees += fee_rate * px * qty
        self.fills += 1
        self.notional += px * qty
        self.log.append((t_ms, side, px, qty, fee_rate))

    def equity(self, mid: float) -> float:
        return self.cash + self.position * mid - self.fees
