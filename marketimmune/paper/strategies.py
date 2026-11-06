"""The paper strategies: what each quotes, and why (``reason``, shown live in the web terminal).

Makers quote ``qty`` at the best bid and ask and stop quoting a side at ``max_position``.

From the December 2025 and A1 results:

- ``Touch`` (December's S1): always both sides. The control.
- ``GapPull`` (December's stale rule): pull the side the demeaned Coinbase gap says is about to be
  picked off: the asks when the gap is above ``threshold_bps`` (Coinbase higher), the bids below
  minus it.
- ``ModelPull`` (December's S2, live): pull the side the walk-forward model's next-second move
  points at, beyond ``threshold_bps``. Before the first fit it quotes like ``Touch``.
- ``Improve``: when the spread is at least 3 ticks, quote one tick inside it on both sides, a new
  price level with nothing ahead; otherwise like ``Touch``. With ``gap_bps`` it also pulls like
  ``GapPull``.

After the 2026-11-06 night (exploratory; estimators in ``paper.signals``):

- ``ZGap``: ``Improve`` that pulls on the gap in units of its own volatility, ``|gap| / sigma_gap >
  z``, so one threshold fits every coin.
- ``HawkesPull``: ``improve+gap@0.25`` that also pulls a side while the takers hitting it arrive
  in a burst: their Hawkes intensity above ``ratio`` times its 10-minute level.
- ``Kelly``: the night's winner made explicit as mean-variance sizing. The target position is
  ``max_position * clip(f / (z * sigma_10s), -1, 1)``, ``f`` the 10 s lead-lag forecast. It
  quotes only the side that moves the position toward the target, one tick inside wide spreads,
  and nothing within half a quote of it. The target is the mean-variance optimum ``f / (gamma *
  sigma^2)`` capped at the limit, with ``gamma`` set so a forecast of ``z`` sigmas fills the limit.
- ``Reservation``: Avellaneda-Stoikov's reservation price with the forecast as drift,
  ``r = f - skew_bps * position / max_position``. A side is quoted only when its quote is on the
  right side of ``r`` by the maker fee: the bid when ``bid <= mid * (1 + (r - fee) / 1e4)``. In AS
  terms, a side is skipped when the optimal quote would sit behind the touch: December's back-off
  run showed those fills lose more than not quoting.

After the market maker (``paper.mm``) lost in every replay, the research's own result as a quoter:

- ``Guard`` (``guard@z=<z>/w=<z>/...``): A1's two signals that held, live, with ``paper.mm``'s position
  and risk control. Quotes like ``ZGap`` (the touch, one tick inside wide spreads) and pulls the
  side the Coinbase gap says is at risk (``|gap z| > z``) and the side informed wallets are taking
  (``|wallet z| > w``: ``CoinState.informed_z`` over the last ``win`` seconds; positive, informed
  buyers, pulls the ask). Position control: no bid once the coin's position is ``lean`` of its limit (no ask
  at minus that), and no bid anywhere at ``+net`` net dollars over the coins (no ask at ``-net``).
  ``stop``, ``hold``, ``dd`` and ``stale`` are ``paper.mm``'s exits; 0 turns one off.

``GapTaker`` is the other side of the trade: when the gap reaches ``threshold_bps`` it buys (or
sells) ``qty`` at the touch, paying the taker fee, and closes ``hold_ms`` after the fill.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Protocol

from marketimmune.paper.mm import MarketMaking, parse
from marketimmune.paper.signals import FORECAST_MS, CoinState, on_tick

Quotes = tuple[float | None, float | None]


class Quoter(Protocol):
    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes: ...

    def reason(self, coin: CoinState, local_ms: int) -> str: ...


def capped(coin: CoinState, position: float, max_position: float) -> Quotes:
    if coin.top is None:
        return None, None
    return (coin.top.bid if position < max_position else None, coin.top.ask if position > -max_position else None)


def inside(coin: CoinState, quotes: Quotes) -> Quotes:
    """One tick inside the spread on each quoted side when the spread is at least 3 ticks."""
    bid, ask = quotes
    tick, top = coin.tick, coin.top
    if tick is not None and top is not None and top.ask - top.bid >= 2.5 * tick:
        bid = None if bid is None else on_tick(top.bid + tick, tick)
        ask = None if ask is None else on_tick(top.ask - tick, tick)
    return bid, ask


def pull(quotes: Quotes, signal: float | None, threshold: float) -> Quotes:
    """Pull the ask when ``signal`` is above ``threshold``, the bid when it is below minus it."""
    bid, ask = quotes
    if signal is not None and signal > threshold:
        ask = None
    if signal is not None and signal < -threshold:
        bid = None
    return bid, ask


def said(signal: float | None, threshold: float, what: str) -> str:
    if signal is None:
        return f"{what} not ready: both sides"
    if signal > threshold:
        return f"{what} {signal:+.2f} > {threshold:g}: ask pulled"
    if signal < -threshold:
        return f"{what} {signal:+.2f} < -{threshold:g}: bid pulled"
    return f"{what} {signal:+.2f} within ±{threshold:g}: both sides"


class Touch:
    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return capped(coin, position, max_position)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return "always both sides at the best price"


class GapPull(Touch):
    def __init__(self, threshold_bps: float) -> None:
        self.threshold_bps = threshold_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return pull(capped(coin, position, max_position), coin.gap(), self.threshold_bps)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return said(coin.gap(), self.threshold_bps, "gap")


class ModelPull(Touch):
    def __init__(self, threshold_bps: float) -> None:
        self.threshold_bps = threshold_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return pull(capped(coin, position, max_position), coin.predict(local_ms), self.threshold_bps)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return said(coin.predict(local_ms), self.threshold_bps, "model 1 s move")


class Improve(Touch):
    def __init__(self, gap_bps: float | None = None) -> None:
        self.gap_bps = gap_bps

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        bid, ask = inside(coin, capped(coin, position, max_position))
        if self.gap_bps is not None:
            bid, ask = pull((bid, ask), coin.gap(), self.gap_bps)
        return bid, ask

    def reason(self, coin: CoinState, local_ms: int) -> str:
        where = "one tick inside" if coin.tick and coin.top and coin.top.ask - coin.top.bid >= 2.5 * coin.tick else "at the touch"
        return where if self.gap_bps is None else f"{where}; {said(coin.gap(), self.gap_bps, 'gap')}"


class ZGap(Touch):
    def __init__(self, z: float) -> None:
        self.z = z

    def zscore(self, coin: CoinState) -> float | None:
        gap, sigma = coin.gap(), coin.gap_sigma
        return gap / sigma if gap is not None and sigma else None

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return pull(inside(coin, capped(coin, position, max_position)), self.zscore(coin), self.z)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return said(self.zscore(coin), self.z, "gap z")


class HawkesPull(Improve):
    def __init__(self, ratio: float) -> None:
        super().__init__(0.25)
        self.ratio = ratio

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        bid, ask = super().quotes(coin, local_ms, position, max_position)
        buys, sells = coin.intensity_ratio(1, local_ms), coin.intensity_ratio(-1, local_ms)
        if buys is not None and buys > self.ratio:
            ask = None
        if sells is not None and sells > self.ratio:
            bid = None
        return bid, ask

    def reason(self, coin: CoinState, local_ms: int) -> str:
        buys, sells = coin.intensity_ratio(1, local_ms), coin.intensity_ratio(-1, local_ms)
        burst = [f"{name} burst x{r:.1f}" for name, r in (("buy", buys), ("sell", sells)) if r is not None and r > self.ratio]
        return super().reason(coin, local_ms) + (f"; {', '.join(burst)}" if burst else "")


class Kelly(Touch):
    def __init__(self, z: float) -> None:
        self.z = z

    def target(self, coin: CoinState, max_position: float) -> float | None:
        f, sigma = coin.forecast(), coin.sigma_1s
        if f is None or not sigma:
            return None
        return max_position * max(-1.0, min(1.0, f / (self.z * sigma * math.sqrt(FORECAST_MS / 1_000))))

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        target = self.target(coin, max_position)
        if target is None or coin.top is None:
            return None, None
        band = 0.1 * max_position  # half a quote at the default 5-quote limit
        bid, ask = inside(coin, (coin.top.bid, coin.top.ask))
        return (bid if position < target - band else None, ask if position > target + band else None)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        f, sigma = coin.forecast(), coin.sigma_1s
        if f is None or not sigma:
            return "forecast not ready: no quotes"
        return f"10 s forecast {f:+.2f} bps, sigma {sigma * math.sqrt(FORECAST_MS / 1_000):.2f}: target {max(-1, min(1, f / (self.z * sigma * math.sqrt(10)))):+.0%} of the limit"


class Reservation(Touch):
    def __init__(self, skew_bps: float, fee_bps: float = 1.5) -> None:
        self.skew_bps = skew_bps
        self.fee_bps = fee_bps

    def price(self, coin: CoinState, position: float, max_position: float) -> float | None:
        f = coin.forecast()
        return None if f is None else f - self.skew_bps * position / max_position

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        r, top = self.price(coin, position, max_position), coin.top
        if r is None or top is None:
            return None, None
        bid, ask = inside(coin, capped(coin, position, max_position))
        mid = top.mid
        if bid is not None and bid > mid * (1 + (r - self.fee_bps) / 1e4):
            bid = None
        if ask is not None and ask < mid * (1 + (r + self.fee_bps) / 1e4):
            ask = None
        return bid, ask

    def reason(self, coin: CoinState, local_ms: int) -> str:
        f = coin.forecast()
        return (
            "forecast not ready: no quotes"
            if f is None
            else f"reservation = 10 s forecast {f:+.2f} bps less inventory skew; quote a side only if it clears the {self.fee_bps:g} bp fee"
        )


@dataclass(frozen=True, slots=True)
class GuardParams:
    z: float = 0.05  # |gap z| that pulls the side at risk
    w: float = 0.0  # |wallet z| that pulls the side informed wallets take (0: off)
    win: float = 1.0  # the wallet factor's window, seconds (1 or 5)
    lean: float = 1.0  # share of the coin's limit past which only the reducing side is quoted
    net: float = 0.0  # net USD over the coins past which the side adding to it stops (0: off)
    stop: float = 0.0  # bps against the average entry that closes a coin's position (0: off)
    hold: float = 0.0  # seconds a position may stay open (0: off)
    dd: float = 0.0  # USD below the equity peak that closes everything (0: off)
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0  # 0: a live order moves on any change of its price, as ZGap's


GUARD_KEYS = tuple(f.name for f in fields(GuardParams))


def parse_guard(arg: str) -> GuardParams:
    """``""`` -> defaults; ``"z=0.05/w=1/net=2000"`` -> those, the rest defaults."""
    values: dict[str, float] = {}
    for part in arg.split("/") if arg else ():
        key, _, value = part.partition("=")
        if key not in GUARD_KEYS:
            raise AssertionError(f"unknown guard parameter {key!r} (one of {', '.join(GUARD_KEYS)})")
        values[key] = float(value)
    return GuardParams(**values)


def signal_z(value: float | None, sigma: float | None) -> float | None:
    return value / sigma if value is not None and sigma else None


class Guard:
    def __init__(self, params: GuardParams) -> None:
        self.p = params
        self.why = "not started"

    def half_spread(self, coin: CoinState) -> float:
        return 0.0

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def targets(self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float) -> Quotes:
        p = self.p
        gz = signal_z(coin.gap(), coin.gap_sigma)
        wz = coin.informed_z(local_ms, int(p.win * 1_000))
        bid, ask = pull(inside(coin, capped(coin, position, max_position)), gz, p.z)
        notes = [said(gz, p.z, "gap z")]
        if p.w > 0:
            before = (bid, ask)
            bid, ask = pull((bid, ask), wz, p.w)
            if (bid, ask) != before:
                notes.append(f"wallets z {wz:+.2f}: {'ask' if before[1] is not None and ask is None else 'bid'} pulled")
        if p.lean < 1 and max_position > 0:
            if position >= p.lean * max_position and bid is not None:
                bid = None
                notes.append(f"position {position / max_position:+.0%}: no bid")
            if position <= -p.lean * max_position and ask is not None:
                ask = None
                notes.append(f"position {position / max_position:+.0%}: no ask")
        if p.net > 0:
            if net_usd >= p.net and bid is not None:
                bid = None
                notes.append(f"net +${net_usd:,.0f}: no bids")
            if net_usd <= -p.net and ask is not None:
                ask = None
                notes.append(f"net -${-net_usd:,.0f}: no asks")
        self.why = "; ".join(notes)
        return bid, ask


LIVE_STRATEGIES = (
    "touch",
    "gap@1",
    "gap@2",
    "model@0.5",
    "model@1",
    "improve",
    "improve+gap@2",
    "taker@6",
    "taker@10",
    "gap@0.25",
    "gap@0.5",
    "improve+gap@0.25",
    "improve+gap@0.5",
)  # the forward test's set (docs/preregistration/paper-forward-test-20261106.md)
ADVANCED_STRATEGIES = ("zgap@0.25", "zgap@0.5", "hawkes@2", "hawkes@3", "kelly@0.5", "kelly@1", "reservation@1", "reservation@3")


def quoter(name: str) -> Quoter:
    """A maker strategy from its name: ``touch``, ``gap@<bps>``, ``model@<bps>``, ``improve``,
    ``improve+gap@<bps>``, ``zgap@<z>``, ``hawkes@<ratio>``, ``kelly@<z>``, ``reservation@<skew bps>``,
    ``mm@...`` (``paper.mm``) or ``guard@...``."""
    kind, _, arg = name.partition("@")
    if kind == "mm":
        return MarketMaking(parse(arg))
    if kind == "guard":
        return Guard(parse_guard(arg))
    if name == "touch":
        return Touch()
    if name == "improve":
        return Improve()
    makers: dict[str, type[GapPull] | type[ModelPull] | type[ZGap] | type[HawkesPull] | type[Kelly] | type[Reservation]] = {
        "gap": GapPull,
        "model": ModelPull,
        "zgap": ZGap,
        "hawkes": HawkesPull,
        "kelly": Kelly,
        "reservation": Reservation,
    }
    if kind in makers:
        return makers[kind](float(arg))
    if kind == "improve+gap":
        return Improve(float(arg))
    raise AssertionError(f"unknown maker strategy {name!r}")


def taker_threshold(name: str) -> float | None:
    """``taker@<bps>`` -> its gap threshold; None for a maker."""
    kind, _, arg = name.partition("@")
    return float(arg) if kind == "taker" else None
