"""Block-accurate maker simulation: our quotes injected into the rebuilt Hyperliquid book.

The historical book and taker flow replay as they happened: our orders move no one (no market
impact) and makers do not see each other. Each simulated order sits in its price level's queue
and is filled by the historical takers that would have reached it.

Inside a block HyperCore runs post-only (ALO) orders first, then cancels, then GTC and IOC orders
(Hyperliquid docs, order book: within-batch processing order). An action of ours that lands in
block ``b`` therefore takes effect before every taker of ``b``. Others' ALO orders added in the
same block are put ahead of ours (their order relative to ours is not recorded); GTC orders that
rest in that block are behind it.

Queue models, for our order at price ``P`` with ``ahead`` queued in front and ``remaining`` size:

* ``fifo`` (exact from the L4 data): ``ahead`` starts at the level's size before the block (Silver
  L2) plus the block's ALO adds at ``P``. Cancels and fills of orders that rested at ``P`` before
  ours lower it. A fill of an order behind ours means the takers got past our place, so it fills
  ours first.
* ``risk_averse`` (L2 only; hftbacktest's ``RiskAdverseQueueModel``): ``ahead`` falls only with
  volume traded at ``P`` and is capped by the level's size. Cancellations help only once the level
  is smaller than our place.

In both models:

* A trade beyond ``P`` (an ask filled above our ask, a bid below our bid) swept our level. It
  fills us up to its size there.
* A GTC order resting through ``P`` on the other side would have traded with us. Our order may sit
  where the historical level emptied. A post-only order there would have been rejected, so it
  does not fill us. An L2 backtester cannot tell the two apart and fills on both:
  ``l2_crossing_fills`` does the same, to reconcile with hftbacktest.
* An ALO of ours that would cross the book before its block is rejected, as HyperCore does.
* After a data gap (blocks more than ``GAP_NS`` apart, when the rebuilt book resets) every order is
  dropped and the strategy quotes again.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import numpy.typing as npt

from marketimmune.sources.albers_l4 import MBO_ADD, MBO_CANCEL, MBO_FILL

ADD, CANCEL, FILL = MBO_ADD, MBO_CANCEL, MBO_FILL  # near-touch L4 event kinds (``albers_l4.MBO_SCHEMA``)
FIFO, RISK_AVERSE = "fifo", "risk_averse"
QUEUE_MODELS = (FIFO, RISK_AVERSE)
BID, ASK = 1, -1  # also the sign of a fill for the maker's position
NO_QUOTE = -1
GAP_NS = 30_000_000_000  # the rebuild's gap rule: the book resets after a longer jump
CHUNK_EVENTS = 1 << 20  # events turned into Python lists at a time
_EPS = 1e-12
_NEVER = 1 << 62
IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class DayBook:
    """One day of the rebuilt book; prices are integer ticks of ``10**-PX_DECIMALS``.

    ``l2_*``: Silver L2 rows, one per block whose top levels changed. Level arrays are
    ``(rows, depth)``, best first, with 0 where a level is missing. ``ev_*``: the near-touch L4
    events in book order. ``ev_sz`` is the size added, cancelled or filled, ``ev_added`` the ns at
    which that order started resting at its price (its time priority), and ``ev_alo`` whether it
    was post-only.
    """

    l2_ts: IntArray
    bid_px: IntArray
    bid_sz: FloatArray
    ask_px: IntArray
    ask_sz: FloatArray
    ev_ts: IntArray
    ev_kind: npt.NDArray[np.int8]
    ev_ask: BoolArray
    ev_px: IntArray
    ev_sz: FloatArray
    ev_added: IntArray
    ev_alo: BoolArray

    def __post_init__(self) -> None:
        assert self.bid_px.shape == self.ask_px.shape == self.bid_sz.shape == (self.l2_ts.size, self.bid_px.shape[1]), "L2 shapes"
        assert np.all(np.diff(self.l2_ts) > 0), "L2 rows must be one per block, in time order"
        assert np.all(np.diff(self.ev_ts) >= 0), "L4 events must be in time order"


class Strategy(Protocol):
    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        """Target bid and ask prices in ticks (``NO_QUOTE`` for none), seen after the block of L2
        row ``row`` at ``ts`` ns with the best bid and ask ``bid``/``ask`` and our ``position``."""
        ...


@dataclass(frozen=True, slots=True)
class MakerSpec:
    name: str
    strategy: Strategy
    queue: str
    qty: float  # quote size in coin units

    def __post_init__(self) -> None:
        assert self.queue in QUEUE_MODELS, f"{self.queue=}"
        assert self.qty > 0.0, f"{self.qty=}"


@dataclass(slots=True)
class MakerResult:
    """A maker's fills (``side``: +1 bought on our bid, -1 sold on our ask) and order counts."""

    name: str
    ts: list[int] = field(default_factory=list)
    side: list[int] = field(default_factory=list)
    px: list[int] = field(default_factory=list)
    qty: list[float] = field(default_factory=list)
    placed: int = 0
    cancelled: int = 0
    rejected: int = 0


@dataclass(slots=True)
class _Order:
    side: int
    px: int
    remaining: float
    placed: int  # ns of the block in which it joined the queue
    ahead: float
    level: float  # risk_averse: the level's size besides ours


class _Maker:
    def __init__(self, spec: MakerSpec, delay_ns: int) -> None:
        self.spec, self.delay = spec, delay_ns
        self.fifo = spec.queue == FIFO
        self.position = 0.0
        self.live: dict[int, _Order | None] = {BID: None, ASK: None}
        self.target = {BID: NO_QUOTE, ASK: NO_QUOTE}  # price live or on its way
        self.pending: deque[tuple[int, int, int]] = deque()  # (arrival ns, side, price or NO_QUOTE)
        self.result = MakerResult(spec.name)


class _Sim:
    def __init__(self, book: DayBook, specs: Sequence[MakerSpec], delay_ns: int, l2_crossing_fills: bool) -> None:
        assert delay_ns > 0, f"{delay_ns=}: an action cannot land in the block it was decided on"
        self.book = book
        self.l2_crossing_fills = l2_crossing_fills
        self.makers = [_Maker(s, delay_ns) for s in specs]
        self.watch: dict[int, dict[int, list[tuple[_Maker, _Order]]]] = {BID: {}, ASK: {}}  # side -> px -> orders
        self.live: dict[int, list[tuple[_Maker, _Order]]] = {BID: [], ASK: []}

    def run(self) -> list[MakerResult]:
        b = self.book
        l2_ts = b.l2_ts.tolist()
        best = {BID: b.bid_px[:, 0].tolist(), ASK: b.ask_px[:, 0].tolist()}
        n_ev, n_rows = b.ev_ts.size, len(l2_ts)
        watch_bid, watch_ask, live_bid, live_ask = self.watch[BID], self.watch[ASK], self.live[BID], self.live[ASK]
        crossing_alo = self.l2_crossing_fills
        i = r = 0
        row, last_t = -1, None
        lo = hi = 0  # events [lo, hi) are held as lists; a day of them as lists would take gigabytes
        ev_ts: list[int] = []
        while i < n_ev or r < n_rows:
            if i == hi and i < n_ev:
                lo, hi = i, _chunk_end(b.ev_ts, i)
                ev_ts, kinds, asks = b.ev_ts[lo:hi].tolist(), b.ev_kind[lo:hi].tolist(), b.ev_ask[lo:hi].tolist()
                pxs, szs, added, alos = (
                    b.ev_px[lo:hi].tolist(),
                    b.ev_sz[lo:hi].tolist(),
                    b.ev_added[lo:hi].tolist(),
                    b.ev_alo[lo:hi].tolist(),
                )
            t = min(ev_ts[i - lo] if i < n_ev else _NEVER, l2_ts[r] if r < n_rows else _NEVER)
            if last_t is not None and t - last_t > GAP_NS:
                self._drop_all()
            last_t = t
            end = i
            while end < hi and ev_ts[end - lo] == t:
                end += 1
            if row >= 0:
                for m in self.makers:
                    while m.pending and m.pending[0][0] <= t:
                        _, side, px = m.pending.popleft()
                        self._act(m, side, px, t, row, i, end, best)
            for e in range(i - lo, end - lo):
                kind, ask, px, sz = kinds[e], asks[e], pxs[e], szs[e]
                hits = (watch_ask if ask else watch_bid).get(px)
                if hits:
                    for m, o in list(hits):
                        self._level_event(m, o, kind, sz, added[e], alos[e], t)
                if kind == FILL:  # a taker that traded beyond our price swept our level first
                    for m, o in list(live_ask if ask else live_bid):
                        if o.px < px if ask else o.px > px:
                            self._fill(m, o, min(o.remaining, sz), t)
                elif kind == ADD and (crossing_alo or not alos[e]):  # a GTC resting through our quote traded with it
                    for m, o in list(live_bid if ask else live_ask):
                        if px <= o.px if ask else px >= o.px:
                            self._fill(m, o, min(o.remaining, sz), t)
            i = end
            if r < n_rows and l2_ts[r] == t:
                row = r
                r += 1
                bid, ask_ = best[BID][row], best[ASK][row]
                for m in self.makers:
                    want_bid, want_ask = m.spec.strategy.quotes(row, t, bid, ask_, m.position)
                    for side, want in ((BID, want_bid), (ASK, want_ask)):
                        if want != m.target[side]:
                            m.target[side] = want
                            m.pending.append((t + m.delay, side, want))
        return [m.result for m in self.makers]

    def _act(self, m: _Maker, side: int, px: int, t: int, row: int, first: int, end: int, best: dict[int, list[int]]) -> None:
        """Our action lands before every taker of block ``t``: cancel the side's order, rest a new one."""
        old = m.live[side]
        if old is not None:
            self._remove(m, old)
            m.result.cancelled += 1
        if px == NO_QUOTE:
            return
        if px >= best[ASK][row] if side == BID else px <= best[BID][row]:
            m.result.rejected += 1  # ALO through the book
            if not any(p[1] == side for p in m.pending):
                m.target[side] = NO_QUOTE
            return
        b = self.book
        prices, sizes = (b.bid_px, b.bid_sz) if side == BID else (b.ask_px, b.ask_sz)
        levels = prices[row].tolist()
        deepest = levels[-1]  # 0 when the side has fewer levels than the depth, so all are shown
        if px in levels:
            level = float(sizes[row, levels.index(px)])
        elif deepest == 0 or (px > deepest if side == BID else px < deepest):
            level = 0.0  # a new level inside the visible depth
        else:
            level = float("inf")  # deeper than Silver shows: only a sweep reaches it
        same_block_alo = sum(
            s
            for s, k, a, p, alo in zip(
                b.ev_sz[first:end].tolist(),
                b.ev_kind[first:end].tolist(),
                b.ev_ask[first:end].tolist(),
                b.ev_px[first:end].tolist(),
                b.ev_alo[first:end].tolist(),
                strict=True,
            )
            if k == ADD and alo and p == px and a == (side == ASK)
        )
        o = _Order(side, px, m.spec.qty, t, level + same_block_alo, level)
        m.live[side] = o
        self.watch[side].setdefault(px, []).append((m, o))
        self.live[side].append((m, o))
        m.result.placed += 1

    def _level_event(self, m: _Maker, o: _Order, kind: int, sz: float, added: int, alo: bool, t: int) -> None:
        if m.fifo:
            in_front = added < o.placed or (added == o.placed and alo)
            if kind == FILL:
                if in_front:
                    o.ahead = max(o.ahead - sz, 0.0)
                else:
                    o.ahead = 0.0
                    self._fill(m, o, min(o.remaining, sz), t)
            elif kind == CANCEL and in_front:
                o.ahead = max(o.ahead - sz, 0.0)
            return
        if kind == ADD:
            o.level += sz
            return
        o.level -= sz
        if kind == FILL:
            o.ahead -= sz
            if o.ahead < 0.0:
                self._fill(m, o, min(o.remaining, -o.ahead), t)
                o.ahead = 0.0
        o.ahead = min(o.ahead, max(o.level, 0.0))

    def _fill(self, m: _Maker, o: _Order, qty: float, t: int) -> None:
        if qty <= _EPS or m.live[o.side] is not o:
            return
        res = m.result
        res.ts.append(t)
        res.side.append(o.side)
        res.px.append(o.px)
        res.qty.append(qty)
        m.position += o.side * qty
        o.remaining -= qty
        if o.remaining <= _EPS:
            self._remove(m, o)
            if not any(p[1] == o.side for p in m.pending):
                m.target[o.side] = NO_QUOTE  # quote again at the next decision

    def _remove(self, m: _Maker, o: _Order) -> None:
        m.live[o.side] = None
        level = self.watch[o.side][o.px]
        level.remove((m, o))
        if not level:
            del self.watch[o.side][o.px]
        self.live[o.side].remove((m, o))

    def _drop_all(self) -> None:
        for m in self.makers:
            for side in (BID, ASK):
                o = m.live[side]
                if o is not None:
                    self._remove(m, o)
                m.target[side] = NO_QUOTE
            m.pending.clear()


def _chunk_end(ts: IntArray, start: int) -> int:
    """End of a run of about ``CHUNK_EVENTS`` events from ``start`` that does not split a block."""
    end = min(start + CHUNK_EVENTS, ts.size)
    return ts.size if end == ts.size else int(np.searchsorted(ts, ts[end - 1], side="right"))


def simulate_day(book: DayBook, makers: Sequence[MakerSpec], *, delay_ns: int, l2_crossing_fills: bool = False) -> list[MakerResult]:
    """Run every maker through one day. Makers are independent: each sees only the history.

    ``delay_ns`` is the time from a block to our action reaching the book: the feed of that block
    plus the order's trip. A decision on L2 row ``r`` lands in the first block at or after
    ``ts[r] + delay_ns``.
    """
    return _Sim(book, makers, delay_ns, l2_crossing_fills).run()
