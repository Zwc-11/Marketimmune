"""Market making with inventory and risk control: ``mm@<h>`` or ``mm@h=<bps>/skew=<bps>/...``.

The gap quoters (``paper.strategies``) sit at the touch and stop a side only at the coin's position
limit, so their PnL is mostly the inventory they happen to hold times the market's move. This one
quotes around a fair price, leans its quotes to work the position back to zero, and has a risk layer
that closes positions with a taker order when they go wrong.

**Quotes.** Each evaluation (``EVAL_MS``, on a new Hyperliquid or Coinbase top):

- fair, in bps from the seen mid: ``alpha * forecast + micro``, the 10 s lead-lag forecast
  (``CoinState.forecast``) plus the microprice's offset ``(bid * ask_sz + ask * bid_sz) / (bid_sz +
  ask_sz)``.
- centre ``r = fair - skew * q - nskew * n``: ``q`` the coin's position over its limit, ``n`` the
  strategy's net dollars over ``net``, each in [-1, 1]. Long, the centre drops: the ask moves to the
  market and the bid away from it (Avellaneda-Stoikov's reservation price, with the drift and the
  inventory term set in bps rather than from a utility).
- half-spread ``max(h, vol * sigma_1s)``; bid ``r - h`` rounded down to the tick, ask ``r + h`` up,
  never crossing the book (post-only). Inside a wide spread that is a new level with nothing ahead;
  behind the touch it rests in the book's queue at that price.
- a live order stays while it is within ``tol * h`` (at least a tick) of its target, so it keeps its
  place in the queue and the cancels stay under Hyperliquid's rate limit.

**Limits.** No bid at the coin's position limit or with net dollars at ``+net``; no ask at the
opposites. A side is pulled while takers hit it in a burst (Hawkes ratio over ``burst``). The
engine's per-strategy gross budget applies as for every maker.

**Exits, with a taker order** (taker fee, through the seen book): ``stop`` when the mid has moved
``stop`` bps against the position's average entry (then no quotes in that coin for ``cool`` s);
``hold`` when a position has been open ``hold`` s (0: off); ``kill`` when the strategy's equity over
all coins falls ``dd`` USD below its peak: every coin is closed and nothing is quoted for ``pause``
s. ``stale``: when either feed has been silent ``stale`` s the quotes are cancelled at once, as
Hyperliquid's ``scheduleCancel`` dead man's switch would.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Protocol

from marketimmune.paper.events import Depth, Top
from marketimmune.paper.signals import CoinState, on_tick

BPS = 1e4


@dataclass(frozen=True, slots=True)
class MMParams:
    h: float = 1.5  # half-spread around the centre, bps
    skew: float | None = None  # centre shift at the coin's position limit, bps (None: max(h, 1))
    nskew: float | None = None  # centre shift at the net limit, bps (None: as skew)
    net: float = 2_000.0  # net USD over all coins at which the side adding to it stops
    stop: float = 30.0  # bps against the average entry that closes a coin's position (0: off)
    hold: float = 0.0  # seconds a position may stay open before it is closed (0: off)
    dd: float = 50.0  # USD below the equity peak that closes everything (0: off)
    pause: float = 600.0  # seconds without quotes after the kill switch
    burst: float = 3.0  # Hawkes ratio of one side's takers that pulls the quote they hit (0: off)
    alpha: float = 1.0  # weight on the 10 s forecast in fair
    vol: float = 0.0  # half-spread at least vol * sigma_1s
    tol: float = 0.25  # a live order stays within tol * h (at least a tick) of its target
    cool: float = 60.0  # seconds without quotes in a coin after its stop
    stale: float = 3.0  # seconds of silence on either feed that cancels every quote

    @property
    def skew_bps(self) -> float:
        return self.skew if self.skew is not None else max(self.h, 1.0)

    @property
    def nskew_bps(self) -> float:
        return self.nskew if self.nskew is not None else self.skew_bps


KEYS = tuple(f.name for f in fields(MMParams))


def parse(arg: str) -> MMParams:
    """``""`` -> defaults; ``"2"`` -> h=2; ``"h=2/skew=3/stop=0"`` -> those, the rest defaults."""
    if not arg:
        return MMParams()
    if "=" not in arg:
        return MMParams(h=float(arg))
    values: dict[str, float] = {}
    for part in arg.split("/"):
        key, _, value = part.partition("=")
        if key not in KEYS:
            raise AssertionError(f"unknown mm parameter {key!r} (one of {', '.join(KEYS)})")
        values[key] = float(value)
    return MMParams(**values)


def is_mm(name: str) -> bool:
    """Strategies run by ``engine.MarketMaker`` (position tracking and the risk layer)."""
    return name.partition("@")[0] in ("mm", "guard", "immune", "optimal", "disloc", "lead", "sweep")


def clip1(x: float) -> float:
    return max(-1.0, min(1.0, x))


def floor_tick(px: float, tick: float) -> float:
    return on_tick(math.floor(px / tick + 1e-9) * tick, tick)


def ceil_tick(px: float, tick: float) -> float:
    return on_tick(math.ceil(px / tick - 1e-9) * tick, tick)


def micro_bps(top: Top) -> float:
    """The microprice's offset from the mid, bps: towards the side with less size."""
    size = top.bid_sz + top.ask_sz
    if size <= 0:
        return 0.0
    return ((top.bid * top.ask_sz + top.ask * top.bid_sz) / size / top.mid - 1.0) * BPS


def sweep(top: Top, depth: Depth | None, side: int, qty: float) -> float:
    """Average price of a taker order of ``qty`` (``side`` +1 buys) through the seen book: the top's
    size first, then the depth's levels beyond it; any rest at the last level seen."""
    best, size = (top.ask, top.ask_sz) if side > 0 else (top.bid, top.bid_sz)
    levels = [(best, size)]
    if depth is not None:
        book = depth.asks if side > 0 else depth.bids
        beyond = [(p, s) for p, s in book.items() if (p > best if side > 0 else p < best)]
        levels += sorted(beyond, key=lambda x: x[0], reverse=side < 0)
    left, cost = qty, 0.0
    for px, sz in levels:
        take = min(left, sz)
        cost += take * px
        left -= take
        if left <= 0:
            break
    if left > 0:
        cost += left * levels[-1][0]
    return cost / qty


class MarketMaking:
    """The quotes of one ``mm`` instance in one coin, and why (``reason`` for the live view)."""

    def __init__(self, params: MMParams) -> None:
        self.p = params
        self.why = "not started"

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> tuple[float | None, float | None]:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def half_spread(self, coin: CoinState) -> float:
        return max(self.p.h, self.p.vol * (coin.sigma_1s or 0.0))

    def targets(
        self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float
    ) -> tuple[float | None, float | None]:
        p, top, tick = self.p, coin.top, coin.tick
        if top is None or tick is None:
            self.why = "no book yet: no quotes"
            return None, None
        f = coin.forecast()
        if f is None:
            self.why = "forecast not ready: no quotes"
            return None, None
        micro = micro_bps(top)
        fair = p.alpha * f + micro
        h = self.half_spread(coin)
        q = clip1(position / max_position) if max_position > 0 else 0.0
        n = clip1(net_usd / p.net) if p.net > 0 else 0.0
        r = fair - p.skew_bps * q - p.nskew_bps * n
        mid = top.mid
        low = min(floor_tick(mid * (1 + (r - h) / BPS), tick), on_tick(top.ask - tick, tick))
        high = max(ceil_tick(mid * (1 + (r + h) / BPS), tick), on_tick(top.bid + tick, tick), on_tick(low + tick, tick))
        bid: float | None = low
        ask: float | None = high
        off: list[str] = []
        if position >= max_position:
            bid = None
            off.append("coin limit: no bid")
        if position <= -max_position:
            ask = None
            off.append("coin limit: no ask")
        if p.net > 0 and net_usd >= p.net and bid is not None:
            bid = None
            off.append(f"net +${net_usd:,.0f} at the limit: no bids")
        if p.net > 0 and net_usd <= -p.net and ask is not None:
            ask = None
            off.append(f"net -${-net_usd:,.0f} at the limit: no asks")
        if p.burst > 0:
            buys, sells = coin.intensity_ratio(1, local_ms), coin.intensity_ratio(-1, local_ms)
            if buys is not None and buys > p.burst and ask is not None:
                ask = None
                off.append(f"buy burst x{buys:.1f}: ask pulled")
            if sells is not None and sells > p.burst and bid is not None:
                bid = None
                off.append(f"sell burst x{sells:.1f}: bid pulled")
        self.why = (
            f"fair {fair:+.2f} bp (forecast {f:+.2f}, book {micro:+.2f}); position {q:+.0%}, net {n:+.0%} -> centre {r:+.2f}; "
            f"quotes {r - h:+.2f} / {r + h:+.2f} bp" + (f"; {'; '.join(off)}" if off else "")
        )
        return bid, ask


class RiskParams(Protocol):
    """What ``Portfolio`` reads of a strategy's parameters."""

    @property
    def dd(self) -> float: ...

    @property
    def pause(self) -> float: ...

    @property
    def stale(self) -> float: ...


class Portfolio:
    """One ``mm`` strategy over all its coins: net dollars, equity peak and kill switch, and whether
    both feeds are alive (``seen``: the engine's last receive ms per venue)."""

    def __init__(self, params: RiskParams, seen: dict[str, int]) -> None:
        self.p = params
        self.seen = seen
        self.net_usd = 0.0
        self.peak: float | None = None
        self.paused_until = 0
        self.kills = 0

    def paused(self, local_ms: int) -> bool:
        return local_ms < self.paused_until

    def fresh(self, local_ms: int) -> bool:
        limit = self.p.stale * 1_000
        return len(self.seen) == 2 and all(local_ms - t <= limit for t in self.seen.values())

    def mark(self, local_ms: int, equity: float, net_usd: float) -> bool:
        """The strategy's equity and net dollars now; True when this trips the kill switch."""
        self.net_usd = net_usd
        if self.peak is None or equity > self.peak:
            self.peak = equity
        if self.p.dd > 0 and not self.paused(local_ms) and equity < self.peak - self.p.dd:
            self.paused_until = local_ms + int(self.p.pause * 1_000)
            self.kills += 1
            self.peak = equity
            return True
        return False


def entry_after(entry: float | None, pos: float, side: int, px: float, qty: float, eps: float) -> tuple[float | None, float, bool]:
    """Average entry price and position after a fill; the bool says a new position opened (from flat,
    or through zero)."""
    new = pos + side * qty
    if abs(new) <= eps:
        return None, 0.0, False
    if abs(pos) <= eps or entry is None:
        return px, new, True
    if (pos > 0) == (side > 0):
        return (entry * abs(pos) + px * qty) / abs(new), new, False
    if (new > 0) != (pos > 0):
        return px, new, True
    return entry, new, False


def info(p: Any) -> dict[str, Any]:
    """A strategy's parameters for the run's summary (``MMParams`` or ``strategies.GuardParams``)."""
    out: dict[str, Any] = {}
    for f in fields(p):
        v = getattr(p, f.name)
        out[f.name] = None if isinstance(v, float) and not math.isfinite(v) else v  # JSON has no infinity
    return out | ({"skew_bps": p.skew_bps, "nskew_bps": p.nskew_bps} if isinstance(p, MMParams) else {})
