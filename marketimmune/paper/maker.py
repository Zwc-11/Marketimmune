"""Maker order lifecycle, queue accounting and per-position risk controls."""

from __future__ import annotations

import math
from collections import deque
from typing import Any

from marketimmune.paper.events import Depth, Top, Trade
from marketimmune.paper.journal import SIDES, Journal, num
from marketimmune.paper.mm import MarketMaking, Portfolio, entry_after, sweep_fill
from marketimmune.paper.orders import Account, PaperOrder
from marketimmune.paper.signals import CoinState
from marketimmune.paper.strategies import Guard, Hush, Immune, LeadLag, Optimal, Quoter, quoter

BPS = 1e4


def new_minute() -> dict[str, Any]:
    return {"orders": 0, "cancels": 0, "fills": 0, "budget": 0, "changes": 0, "ms": dict.fromkeys(SIDES, 0)}


def mid_before(coin: CoinState, t_ms: int) -> float | None:
    """The last Hyperliquid mid of a block before ``t_ms``."""
    for t, mid in reversed(coin.mids):
        if t < t_ms:
            return mid
    return None


class Maker:
    def __init__(
        self,
        name: str,
        quoter: Quoter,
        qty: float,
        max_position: float,
        latency_ms: int,
        fee_rate: float,
        coin: str = "",
        journal: Journal | None = None,
    ) -> None:
        self.name = name
        self.coin = coin
        self.journal = journal
        self.minute = new_minute()
        self.since: int | None = None  # local ms the current sides began
        self.quoter = quoter
        self.qty = qty
        self.max_position = max_position
        self.latency_ms = latency_ms
        self.fee_rate = fee_rate
        self.orders: list[PaperOrder] = []
        self.current: dict[int, PaperOrder | None] = {1: None, -1: None}
        self.account = Account()
        self.actions = 0  # orders sent plus cancels sent: what the venue's rate limit counts
        self.rejects = 0
        self.sides = ""
        self.events: deque[tuple[int, str, str]] = deque(maxlen=50)  # local ms, sides quoted, reason

    def decide(self, coin: CoinState, local_ms: int, room: float = math.inf, ctx: dict[str, Any] | None = None) -> None:
        """``room``: the most of this coin, in coins, the strategy's budget lets it hold. A side that would
        take the position past it is dropped; a side that reduces the position never is. ``ctx``: the
        signals now, kept with each order sent for the journal."""
        bid, ask = self.quoter.quotes(coin, local_ms, self.account.position, self.max_position)
        self.place(coin, local_ms, bid, ask, room, ctx)

    def keep(self, coin: CoinState, side: int, live_px: float, px: float) -> bool:
        """Whether a live order at ``live_px`` may stay when the strategy now wants ``px`` (same side).
        The gap quoters move an order on any change; ``paper.mm`` keeps it within a tolerance."""
        return live_px == px

    def exposure(self) -> float:
        """Worst absolute position if outstanding orders fill before cancellation."""
        pos = self.account.position
        return max(abs(pos + sum(o.side * o.qty for o in self.orders if o.side == side)) for side in (1, -1))

    def place(self, coin: CoinState, local_ms: int, bid: float | None, ask: float | None, room: float, ctx: dict[str, Any] | None) -> None:
        """Send the orders and cancels that turn the live quotes into ``bid`` / ``ask`` (None: no quote)."""
        want = sides_of(bid, ask)
        pos, slack = self.account.position, min(room, self.max_position) + 1e-9 * self.qty
        buys = sum(o.qty for o in self.orders if o.side == 1)
        sells = sum(o.qty for o in self.orders if o.side == -1)
        if bid is not None and self.current[1] is None and pos + buys + self.qty > max(slack, pos):
            bid = None
        if ask is not None and self.current[-1] is None and pos - sells - self.qty < min(-slack, pos):
            ask = None
        sides = sides_of(bid, ask)
        if sides != want:
            self.minute["budget"] += 1
        if sides != self.sides:
            self.time_in_state(local_ms)
            self.sides = sides
            why = self.quoter.reason(coin, local_ms)
            self.events.append((local_ms, sides, why))
            self.minute["changes"] += 1
            if self.journal is not None:
                top = coin.top
                self.journal.write(
                    "decisions",
                    {
                        "t": local_ms,
                        "s": self.name,
                        "c": self.coin,
                        "want": want,
                        "sides": sides,
                        "why": why,
                        "pos": num(pos, 8),
                        "pos_usd": num(pos * top.mid, 2) if top else None,
                        "ctx": ctx,
                    },
                )
        for side, px in ((1, bid), (-1, ask)):
            cur = self.current[side]
            if cur is not None and (px is None or cur.qty <= 0 or not self.keep(coin, side, cur.px, px)):
                if cur.qty > 0:  # a filled order needs no cancel
                    cur.t_cancel = min(cur.t_cancel, local_ms + self.latency_ms)
                    self.actions += 1
                    self.minute["cancels"] += 1
                cur = self.current[side] = None
            if px is not None and cur is None:
                pending = sum(o.qty for o in self.orders if o.side == side)
                worst = pos + side * (pending + self.qty)
                if (side > 0 and worst > max(slack, pos)) or (side < 0 and worst < min(-slack, pos)):
                    continue
                order = PaperOrder(side, px, self.qty, local_ms + self.latency_ms, placed=local_ms, ctx=ctx)
                self.orders.append(order)
                self.current[side] = order
                self.actions += 1
                self.minute["orders"] += 1

    def time_in_state(self, local_ms: int) -> None:
        """Add the time since the last change (or minute) to the current sides."""
        if self.sides and self.since is not None:
            self.minute["ms"][self.sides] += max(0, local_ms - self.since)
        self.since = local_ms

    def close_minute(self, local_ms: int) -> dict[str, Any]:
        self.time_in_state(local_ms)
        out, self.minute = self.minute, new_minute()
        return out

    def on_top(self, ev: Top, local_ms: int | None = None) -> None:
        self.orders = [o for o in self.orders if o.qty > 0 and o.t_cancel > ev.t_ms]
        for o in self.orders:
            if local_ms is not None and local_ms < o.t_live:
                continue
            if not o.arrived and ev.t_ms >= o.t_live:
                o.arrived = True
                if (o.px >= ev.ask) if o.side > 0 else (o.px <= ev.bid):
                    o.qty = 0.0
                    self.rejects += 1
                    continue
            if o.side > 0 and o.px >= ev.bid:
                o.see_level(ev.t_ms, ev.bid_sz if o.px == ev.bid else 0.0)
            elif o.side < 0 and o.px <= ev.ask:
                o.see_level(ev.t_ms, ev.ask_sz if o.px == ev.ask else 0.0)

    def on_depth(self, ev: Depth, local_ms: int | None = None) -> None:
        self.orders = [o for o in self.orders if o.qty > 0 and o.t_cancel > ev.t_ms]
        for o in self.orders:
            if local_ms is not None and local_ms < o.t_live:
                continue
            if not o.arrived and ev.t_ms >= o.t_live:
                o.arrived = True
                if (o.px >= min(ev.asks)) if o.side > 0 else (o.px <= max(ev.bids)):
                    o.qty = 0.0
                    self.rejects += 1
                    continue
            levels = ev.bids if o.side > 0 else ev.asks
            if not levels:
                continue
            best = max(levels) if o.side > 0 else min(levels)
            if (o.px > best) if o.side > 0 else (o.px < best):
                o.see_level(ev.t_ms, 0.0)
            elif o.px in levels:
                o.see_level(ev.t_ms, levels[o.px])

    def on_trade(self, ev: Trade, coin: CoinState, local_ms: int = 0) -> None:
        remaining = ev.sz
        at_price: float | None = None
        for o in sorted(self.orders, key=lambda order: (-order.side * order.px, order.t_live)):
            if local_ms and local_ms < o.t_live:
                continue
            seen = seen_size(coin, o, ev.t_ms)
            ahead = seen if o.queue is None else o.queue
            if ev.px == o.px and o.live_at(ev.t_ms) and ev.taker_buy != (o.side > 0) and at_price is None:
                at_price = max(0.0, ev.sz - ahead) if ahead is not None else 0.0
            cap = min(remaining, at_price) if ev.px == o.px and at_price is not None else remaining
            q = o.match(ev.t_ms, ev.px, ev.sz, ev.taker_buy, seen, max_fill=cap)
            if q > 0:
                remaining -= q
                if ev.px == o.px and at_price is not None:
                    at_price -= q
                self.account.fill(ev.t_ms, o.side, o.px, q, self.fee_rate)
                self.minute["fills"] += 1
                if self.journal is not None:
                    self.journal.write(
                        "fills",
                        {
                            "t": local_ms,
                            "blk": ev.t_ms,
                            "s": self.name,
                            "c": self.coin,
                            "kind": "maker",
                            "side": o.side,
                            "px": o.px,
                            "qty": num(q, 8),
                            "fee": num(self.fee_rate * o.px * q, 6),
                            "pos": num(self.account.position, 8),
                            "placed": o.placed,
                            "live": o.t_live,
                            "q0": num(o.joined, 8),
                            "ahead": num(ahead, 8),
                            "through": ev.px < o.px if o.side > 0 else ev.px > o.px,
                            "mid0": mid_before(coin, ev.t_ms),
                            "ctx": o.ctx,
                        },
                    )
        self.orders = [o for o in self.orders if o.qty > 0 and o.t_cancel > ev.t_ms]


def risky(name: str) -> MarketMaking | Guard | Immune | Optimal | LeadLag | Hush:
    """The quoter of a strategy ``MarketMaker`` runs (``paper.mm.is_mm``)."""
    q = quoter(name)
    assert isinstance(q, (MarketMaking, Guard, Immune, Optimal, LeadLag, Hush)), name
    return q


class MarketMaker(Maker):
    """``mm@...`` in one coin (``paper.mm``): quotes from ``MarketMaking.targets``, live orders kept
    within a tolerance, and the exits a taker order closes (stop, hold, kill switch)."""

    def __init__(
        self,
        name: str,
        quoter: MarketMaking | Guard | Immune | Optimal | LeadLag | Hush,
        qty: float,
        max_position: float,
        latency_ms: int,
        fee_rate: float,
        taker_fee_rate: float,
        portfolio: Portfolio,
        coin: str = "",
        journal: Journal | None = None,
    ) -> None:
        super().__init__(name, quoter, qty, max_position, latency_ms, fee_rate, coin=coin, journal=journal)
        self.mm = quoter
        self.params = quoter.p
        if isinstance(quoter, (Immune, Optimal, LeadLag, Hush)):
            quoter.qty = qty
        self.taker_fee = taker_fee_rate
        self.portfolio = portfolio
        self.state: CoinState | None = None
        self.entry: float | None = None  # average entry price of the open position
        self.opened_ms: int | None = None  # block ms the open position began
        self.tracked = 0.0  # position as of the fills folded into ``entry``
        self.absorbed = 0
        self.pending: tuple[int, int, str] | None = None  # taker exit: side, ms it reaches the book, why
        self.exit_qty = 0.0
        self.exit_used: dict[tuple[int, int, float], float] = {}
        self.pending_ctx: dict[str, Any] | None = None
        self.cool_until = 0
        self.exits: dict[str, int] = {"stop": 0, "hold": 0, "kill": 0}
        self.last_ms = 0

    def absorb(self) -> None:
        """Fold new fills into the average entry, the open time and the strategy's net dollars."""
        log, eps = self.account.log, 1e-9 * self.qty
        for t, side, px, qty, _ in log[self.absorbed :]:
            self.entry, self.tracked, opened = entry_after(self.entry, self.tracked, side, px, qty, eps)
            if opened:
                self.opened_ms = t
            elif self.entry is None:
                self.opened_ms = None
            self.portfolio.net_usd += side * px * qty
        self.absorbed = len(log)

    def keep(self, coin: CoinState, side: int, live_px: float, px: float) -> bool:
        if self.params.tol <= 0:
            return live_px == px
        tick = coin.tick or 0.0
        top = coin.top
        tol = max(tick, self.params.tol * self.mm.half_spread(coin) / BPS * (top.mid if top else live_px))
        return abs(live_px - px) <= tol + 1e-12

    def blocked(self, local_ms: int) -> str | None:
        port = self.portfolio
        if self.pending is not None:
            return f"closing the position with a taker order ({self.pending[2]})"
        if port.paused(local_ms):
            return (
                f"kill switch: equity fell ${self.params.dd:g} from its peak; no quotes for {(port.paused_until - local_ms) / 1_000:.0f} s"
            )
        if local_ms < self.cool_until:
            return f"stopped out: no quotes for {(self.cool_until - local_ms) / 1_000:.0f} s"
        if self.state is None or not self.fresh(self.state, local_ms):
            if len(port.seen) < 2:
                return "waiting for both feeds: no quotes"
            return f"a feed has been silent over {self.params.stale:g} s: no quotes"
        return None

    def fresh(self, coin: CoinState, local_ms: int) -> bool:
        return all(t is not None and 0 <= local_ms - t <= self.params.stale * 1000 for t in (coin.book_received_ms, coin.ref_received_ms))

    def decide(self, coin: CoinState, local_ms: int, room: float = math.inf, ctx: dict[str, Any] | None = None) -> None:
        self.state, self.last_ms = coin, local_ms
        self.absorb()
        p, pos, top = self.params, self.account.position, coin.top
        if self.pending is None and abs(pos) > 1e-9 * self.qty and top is not None:
            why = None
            if self.portfolio.paused(local_ms):
                why = "kill"
            elif p.stop > 0 and self.entry is not None and (top.mid / self.entry - 1.0) * BPS * (1 if pos > 0 else -1) <= -p.stop:
                why = "stop"
            elif p.hold > 0 and self.opened_ms is not None and local_ms - self.opened_ms >= p.hold * 1_000:
                why = "hold"
            if why is not None:
                self.exit(local_ms, why, ctx)
        blocked = self.blocked(local_ms)
        if blocked is not None:
            self.mm.why = blocked
            bid, ask = None, None
        else:
            bid, ask = self.mm.targets(coin, local_ms, pos, self.max_position, self.portfolio.net_usd)
        self.place(coin, local_ms, bid, ask, room, ctx)

    def exit(self, local_ms: int, why: str, ctx: dict[str, Any] | None) -> None:
        side = -1 if self.account.position > 0 else 1
        self.pending = (side, local_ms + self.latency_ms, why)
        self.exit_qty = abs(self.account.position)
        self.pending_ctx = ctx
        self.exits[why] += 1
        self.actions += 1
        self.minute["orders"] += 1
        if why == "stop":
            self.cool_until = local_ms + int(self.params.cool * 1_000)
        if self.journal is not None:
            self.journal.write("taker", {"t": local_ms, "s": self.name, "c": self.coin, "leg": why, "side": side, "ctx": ctx})

    def pull(self, deadline_ms: int) -> None:
        """Cancel every live order by ``deadline_ms`` (block time), with no message: the venue's dead
        man's switch."""
        for side in (1, -1):
            cur = self.current[side]
            if cur is not None:
                cur.t_cancel = min(cur.t_cancel, deadline_ms)
                self.current[side] = None
        if self.sides not in ("", "none"):
            self.time_in_state(self.last_ms)
            self.sides = "none"

    def on_trade(self, ev: Trade, coin: CoinState, local_ms: int = 0) -> None:
        super().on_trade(ev, coin, local_ms)
        self.absorb()

    def on_top(self, ev: Top, local_ms: int | None = None) -> None:
        super().on_top(ev, local_ms)
        if (
            self.pending is None
            or ev.t_ms < self.pending[1]
            or (self.state is not None and self.state.book_received_ms is not None and self.state.book_received_ms < self.pending[1])
        ):
            return
        side, _, why = self.pending
        self.pending = None
        pos = self.account.position
        if abs(pos) <= 1e-9 * self.qty or (pos > 0) == (side > 0):  # already closed by a maker fill
            return
        qty = min(abs(pos), self.exit_qty)
        depth = self.state.depth if self.state is not None else None
        oldest = min(ev.t_ms, depth.t_ms) if depth is not None and ev.t_ms - depth.t_ms <= 3000 else ev.t_ms
        self.exit_used = {key: value for key, value in self.exit_used.items() if key[0] >= oldest}
        px, qty = sweep_fill(ev, depth, side, qty, self.exit_used)
        if qty <= 0:
            return
        self.account.fill(ev.t_ms, side, px, qty, self.taker_fee)
        if abs(self.account.position) < 1e-9 * self.qty:
            self.account.position = 0.0
        self.minute["fills"] += 1
        self.absorb()
        if self.journal is not None:
            self.journal.write(
                "fills",
                {
                    "t": local_ms if local_ms is not None else self.last_ms,
                    "blk": ev.t_ms,
                    "s": self.name,
                    "c": self.coin,
                    "kind": "taker",
                    "leg": why,
                    "side": side,
                    "px": num(px, 8),
                    "qty": num(qty, 8),
                    "fee": num(self.taker_fee * px * qty, 6),
                    "pos": num(self.account.position, 8),
                    "mid0": ev.mid,
                    "ctx": self.pending_ctx,
                },
            )


def sides_of(bid: float | None, ask: float | None) -> str:
    return "both" if bid is not None and ask is not None else "bid" if bid is not None else "ask" if ask is not None else "none"


def seen_size(coin: CoinState, o: PaperOrder, at_ms: int = 1 << 62) -> float | None:
    """Known queue after arrival and before this print; unseen deep queues stay unknown."""
    if not o.arrived:
        return None
    top = coin.top
    if top is not None and o.t_live <= top.t_ms < at_ms:
        if o.side > 0 and o.px >= top.bid:
            return top.bid_sz if o.px == top.bid else 0.0
        if o.side < 0 and o.px <= top.ask:
            return top.ask_sz if o.px == top.ask else 0.0
    depth = coin.depth
    if depth is not None and o.t_live <= depth.t_ms < at_ms:
        levels = depth.bids if o.side > 0 else depth.asks
        if levels and min(levels) <= o.px <= max(levels):
            return levels.get(o.px, 0.0)
    return None
