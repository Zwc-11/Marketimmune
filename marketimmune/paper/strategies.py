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
  ``stop``, ``hold``, ``dd`` and ``stale`` are ``paper.mm``'s exits; 0 turns one off. ``veto``: also
  pull a side whose fill ``paper.immune``'s 10 s model expects to lose more than ``-veto`` bps after
  the fee (MarketImmune's toxicity veto on top of the gap and wallet rules).

- ``Immune`` (``immune@h=<s>/t=<bps>/risk=<phi>``): MarketImmune's own question asked of every quote.
  ``paper.immune``'s model predicts the markout of a fill on each side over ``h`` seconds from the
  signals now (Coinbase gap, wallet factor, microprice, flow, bursts, spread, volatility); a side
  is quoted (at the touch, one tick inside wide spreads) only while

      predicted markout - fee - risk * sigma_h^2 * (2 * side * position + quote) / 1e4 >= t

  in bps: the last term is the mean-variance cost of the inventory the fill would add (position and
  quote in USD, ``sigma_h`` the coin's ``h``-second volatility in bps, ``risk`` per USD), so a
  long book needs a better bid and accepts a worse ask. The position and risk controls of
  ``Guard`` apply.

- ``Optimal`` (``optimal@phi=<phi>``): the policy of the market maker's optimal control problem,
  solved by value iteration on a model calibrated on the selection hours (``paper.optimal``,
  ``cli.paper_optimal_fit``): for the coin's position in quotes and its market state (the
  predicted next 10 s move), which sides to quote at the touch.

``GapTaker`` is the other side of the trade: when the gap reaches ``threshold_bps`` it buys (or
sells) ``qty`` at the touch, paying the taker fee, and closes ``hold_ms`` after the fill.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Protocol

from marketimmune.paper.immune import FillModel, features, model_for, side_features
from marketimmune.paper.mm import MarketMaking, parse
from marketimmune.paper.optimal import policies
from marketimmune.paper.signals import FORECAST_MS, CoinState, log_bps, on_tick

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
    veto: float = -math.inf  # pull a side whose fill's predicted 10 s markout after the fee is below this, bps
    lean: float = 1.0  # share of the coin's limit past which only the reducing side is quoted
    net: float = 0.0  # net USD over the coins past which the side adding to it stops (0: off)
    stop: float = 0.0  # bps against the average entry that closes a coin's position (0: off)
    hold: float = 0.0  # seconds a position may stay open (0: off)
    dd: float = 0.0  # USD below the equity peak that closes everything (0: off)
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0  # 0: a live order moves on any change of its price, as ZGap's


BPS = 1e4
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
    def __init__(self, params: GuardParams, model: FillModel | None = None) -> None:
        self.p = params
        self.why = "not started"
        self.model = model if model is not None or params.veto == -math.inf else model_for(10)

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
        if self.model is not None and (bid is not None or ask is not None):
            f = features(coin, local_ms)
            if f is not None:
                for side in (1, -1):
                    if (bid if side > 0 else ask) is None:
                        continue
                    after_fee = self.model.predict(coin.coin, side_features(f, side)) - 1.5
                    if after_fee < p.veto:
                        bid, ask = (None, ask) if side > 0 else (bid, None)
                        notes.append(f"{'bid' if side > 0 else 'ask'} fill {after_fee:+.2f} bp after fee < {p.veto:g}: vetoed")
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


@dataclass(frozen=True, slots=True)
class ImmuneParams:
    h: float = 30.0  # the fill-markout model's horizon, seconds (paper/models/immune_<h>s.json)
    t: float = 0.0  # bps a fill's predicted markout must clear after the fee and the inventory cost
    risk: float = 0.0  # mean-variance inventory aversion, per USD
    fee: float = 1.5  # maker fee, bps
    lean: float = 1.0
    net: float = 0.0
    stop: float = 0.0
    hold: float = 0.0
    dd: float = 0.0
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0


IMMUNE_KEYS = tuple(f.name for f in fields(ImmuneParams))


def parse_immune(arg: str) -> ImmuneParams:
    """``""`` -> defaults; ``"h=30/t=0.5/risk=0.02"`` -> those, the rest defaults."""
    values: dict[str, float] = {}
    for part in arg.split("/") if arg else ():
        key, _, value = part.partition("=")
        if key not in IMMUNE_KEYS:
            raise AssertionError(f"unknown immune parameter {key!r} (one of {', '.join(IMMUNE_KEYS)})")
        values[key] = float(value)
    return ImmuneParams(**values)


class Immune:
    def __init__(self, params: ImmuneParams, model: FillModel | None = None) -> None:
        self.p = params
        self.model = model if model is not None else model_for(int(params.h))
        self.why = "not started"
        self.qty = 0.0  # quote size in coins (set by engine.MarketMaker)

    def half_spread(self, coin: CoinState) -> float:
        return 0.0

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def value(self, coin: CoinState, f: dict[str, float], side: int, position: float) -> tuple[float, float]:
        """A fill's predicted markout on ``side`` and the inventory cost it would carry, bps."""
        top = coin.top
        assert top is not None
        pred = self.model.predict(coin.coin, side_features(f, side))
        sigma_h = f["sigma"] * math.sqrt(self.p.h)
        cost = self.p.risk * sigma_h**2 * (2 * side * position * top.mid + self.qty * top.mid) / BPS
        return pred, cost

    def targets(self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float) -> Quotes:
        p = self.p
        f = features(coin, local_ms)
        if f is None or coin.top is None:
            self.why = "signals not ready: no quotes"
            return None, None
        bid, ask = inside(coin, capped(coin, position, max_position))
        notes = []
        for side in (1, -1):
            pred, cost = self.value(coin, f, side, position)
            edge = pred - p.fee - cost
            name = "bid" if side > 0 else "ask"
            if edge < p.t:
                bid, ask = (None, ask) if side > 0 else (bid, None)
            notes.append(f"{name} {pred:+.2f} - fee {p.fee:g} - risk {cost:.2f} = {edge:+.2f} {'<' if edge < p.t else '>='} {p.t:g}")
        if p.lean < 1 and max_position > 0:
            if position >= p.lean * max_position:
                bid = None
            if position <= -p.lean * max_position:
                ask = None
        if p.net > 0:
            if net_usd >= p.net:
                bid = None
            if net_usd <= -p.net:
                ask = None
        self.why = "fill markout " + "; ".join(notes)
        return bid, ask


@dataclass(frozen=True, slots=True)
class OptimalParams:
    phi: float = 0.0  # inventory risk aversion the policy was solved with (one of the file's phis)
    lean: float = 1.0
    net: float = 0.0
    stop: float = 0.0
    hold: float = 0.0
    dd: float = 0.0
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0


def parse_optimal(arg: str) -> OptimalParams:
    values: dict[str, float] = {}
    keys = tuple(f.name for f in fields(OptimalParams))
    for part in arg.split("/") if arg else ():
        key, _, value = part.partition("=")
        if key not in keys:
            raise AssertionError(f"unknown optimal parameter {key!r} (one of {', '.join(keys)})")
        values[key] = float(value)
    return OptimalParams(**values)


class Optimal:
    def __init__(self, params: OptimalParams) -> None:
        self.p = params
        self.table = policies(str(params.phi))
        self.why = "not started"
        self.qty = 0.0  # quote size in coins (set by engine.MarketMaker)

    def half_spread(self, coin: CoinState) -> float:
        return 0.0

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def targets(self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float) -> Quotes:
        pol = self.table.get(coin.coin)
        f = features(coin, local_ms)
        if pol is None or f is None or self.qty <= 0:
            self.why = "no policy or signals yet: no quotes"
            return None, None
        state, pred = pol.state(f)
        units = round(position / self.qty)
        want_bid, want_ask = pol.action(units, state)
        bid, ask = inside(coin, capped(coin, position, max_position))
        bid, ask = (bid if want_bid else None), (ask if want_ask else None)
        if self.p.net > 0:
            if net_usd >= self.p.net:
                bid = None
            if net_usd <= -self.p.net:
                ask = None
        self.why = (
            f"state {state} (predicted 10 s move {pred:+.2f} bp), position {units:+d} quotes: {'bid ' if want_bid else ''}{'ask' if want_ask else ''}".rstrip()
            or "none"
        )
        if not (want_bid or want_ask):
            self.why = f"state {state} (predicted 10 s move {pred:+.2f} bp), position {units:+d} quotes: no quote is worth it"
        return bid, ask


@dataclass(frozen=True, slots=True)
class LeadParams:
    """The lead-lag quoters' settings (``disloc@``, ``lead@``, ``sweep@``) and the shared risk layer.

    ``d``: entry distance from the Coinbase fair price, bps. ``x``: exit distance past fair, bps
    (0: exit at fair). ``h0``, ``a``, ``skew``: ``lead@``'s half-width h = h0 + a * sigma_1s (bps)
    and its centre fair * (1 - skew * h * units / 1e4). ``move``, ``win``, ``wait``: ``sweep@``
    arms after Hyperliquid moved ``move`` bps in ``win`` s while the gap opened by half of that, for
    ``wait`` s."""

    d: float = 3.0
    x: float = 0.0
    h0: float = 2.0
    a: float = 0.0
    skew: float = 0.5
    move: float = 4.0
    win: float = 3.0
    wait: float = 5.0
    lean: float = 1.0
    net: float = 0.0
    stop: float = 0.0
    hold: float = 0.0
    dd: float = 0.0
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0


LEAD_KEYS = tuple(f.name for f in fields(LeadParams))


def parse_lead(arg: str) -> LeadParams:
    values: dict[str, float] = {}
    for part in arg.split("/") if arg else ():
        key, _, value = part.partition("=")
        if key not in LEAD_KEYS:
            raise AssertionError(f"unknown lead-lag parameter {key!r} (one of {', '.join(LEAD_KEYS)})")
        values[key] = float(value)
    return LeadParams(**values)


def fair_price(coin: CoinState) -> float | None:
    """Coinbase's mid carried to Hyperliquid's basis: Hyperliquid's mid moved by the demeaned gap."""
    gap, top = coin.gap(), coin.top
    if gap is None or top is None:
        return None
    return top.mid * math.exp(gap / BPS)


def _down(px: float, tick: float | None) -> float:
    return math.floor(px / tick + 1e-9) * tick if tick else px


def _up(px: float, tick: float | None) -> float:
    return math.ceil(px / tick - 1e-9) * tick if tick else px


class LeadLag:
    """Base of the lead-lag quoters: quotes are prices around the Coinbase fair price, always
    passive (a bid at most the best bid, an ask at least the best ask), with ``Guard``'s net cap."""

    kind = "lead"

    def __init__(self, params: LeadParams) -> None:
        self.p = params
        self.why = "not started"
        self.qty = 0.0  # quote size in coins (set by engine.MarketMaker)

    def half_spread(self, coin: CoinState) -> float:
        return self.p.d

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def raw(self, coin: CoinState, fair: float, local_ms: int, position: float, max_position: float) -> Quotes:
        raise NotImplementedError

    def targets(self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float) -> Quotes:
        fair, top, tick = fair_price(coin), coin.top, coin.tick
        if fair is None or top is None:
            self.why = "no Coinbase fair price yet: no quotes"
            return None, None
        bid, ask = self.raw(coin, fair, local_ms, position, max_position)
        if bid is not None:
            bid = min(_down(bid, tick), top.bid)
        if ask is not None:
            ask = max(_up(ask, tick), top.ask)
        if self.p.net > 0:
            if net_usd >= self.p.net:
                bid = None
            if net_usd <= -self.p.net:
                ask = None
        return bid, ask


class Dislocation(LeadLag):
    """``disloc@d=<bps>/x=<bps>/...``: rests a bid ``d`` bps under the Coinbase fair price and an ask
    ``d`` over it, so it is filled when Hyperliquid alone moves away from Coinbase; with a position it
    rests the exit ``x`` bps past fair on the other side (at the touch when that is better)."""

    kind = "disloc"

    def raw(self, coin: CoinState, fair: float, local_ms: int, position: float, max_position: float) -> Quotes:
        p, units = self.p, (position / self.qty if self.qty else 0.0)
        bid = fair * (1 - p.d / BPS) if position < max_position - 1e-9 * max(self.qty, 1e-12) else None
        ask = fair * (1 + p.d / BPS) if position > -max_position + 1e-9 * max(self.qty, 1e-12) else None
        if units > 1e-6:
            ask = fair * (1 + p.x / BPS)
        elif units < -1e-6:
            bid = fair * (1 - p.x / BPS)
        self.why = (
            f"fair {fair:.6g}; {units:+.1f} quotes: bid {'-' if bid is None else f'{bid:.6g}'}, ask {'-' if ask is None else f'{ask:.6g}'}"
        )
        return bid, ask


class LeadAS(LeadLag):
    """``lead@h0=<bps>/a=<x>/skew=<x>/...``: Avellaneda-Stoikov around the Coinbase fair price. Half-width
    h = h0 + a * sigma_1s; centre fair * (1 - skew * h * units / 1e4), skewed against the inventory."""

    kind = "lead"

    def half_spread(self, coin: CoinState) -> float:
        return self.p.h0 + self.p.a * (coin.sigma_1s or 0.0)

    def raw(self, coin: CoinState, fair: float, local_ms: int, position: float, max_position: float) -> Quotes:
        p = self.p
        units = position / self.qty if self.qty else 0.0
        h = self.half_spread(coin)
        r = fair * (1 - p.skew * h * units / BPS)
        bid = r * (1 - h / BPS) if position < max_position - 1e-9 * max(self.qty, 1e-12) else None
        ask = r * (1 + h / BPS) if position > -max_position + 1e-9 * max(self.qty, 1e-12) else None
        self.why = f"fair {fair:.6g}, half-width {h:.2f} bp, {units:+.1f} quotes"
        return bid, ask


class Sweep(LeadLag):
    """``sweep@move=<bps>/win=<s>/wait=<s>/x=<bps>/...``: after Hyperliquid alone moved ``move`` bps
    in ``win`` s (the gap to Coinbase opened by at least half of that), join the touch on the side
    that profits from the move coming back, for ``wait`` s; with a position, exit like ``disloc@``."""

    kind = "sweep"

    def __init__(self, params: LeadParams) -> None:
        super().__init__(params)
        self.armed = 0
        self.until = 0
        self.hist: list[tuple[int, float, float]] = []  # (ms, mid, gap)

    def raw(self, coin: CoinState, fair: float, local_ms: int, position: float, max_position: float) -> Quotes:
        p, top, gap = self.p, coin.top, coin.gap()
        assert top is not None and gap is not None
        self.hist.append((local_ms, top.mid, gap))
        horizon = local_ms - int(p.win * 1_000)
        while len(self.hist) > 1 and self.hist[1][0] <= horizon:
            self.hist.pop(0)
        units = position / self.qty if self.qty else 0.0
        if units > 1e-6:
            self.why = "long: exit at fair"
            return None, fair * (1 + p.x / BPS)
        if units < -1e-6:
            self.why = "short: exit at fair"
            return fair * (1 - p.x / BPS), None
        t0, m0, g0 = self.hist[0]
        if t0 <= horizon:
            move = (top.mid / m0 - 1) * BPS
            if move <= -p.move and gap - g0 >= p.move / 2:
                self.armed, self.until = 1, local_ms + int(p.wait * 1_000)
            elif move >= p.move and gap - g0 <= -p.move / 2:
                self.armed, self.until = -1, local_ms + int(p.wait * 1_000)
        if local_ms > self.until:
            self.armed = 0
        if self.armed == 1:
            self.why = "Hyperliquid fell alone: bid at the touch"
            return top.bid, None
        if self.armed == -1:
            self.why = "Hyperliquid rose alone: ask at the touch"
            return None, top.ask
        self.why = "no one-venue move: no quotes"
        return None, None


@dataclass(frozen=True, slots=True)
class HushParams:
    """``hush@``: the quiet-depth maker's settings and the shared risk layer.

    ``d``: entry quotes this many bps from Hyperliquid's mid. ``x``: the side that reduces a position
    quotes this many bps from the mid (default: as deep as ``d``). ``quiet``: seconds since the last
    take on the coin by a wallet scoring at least ``inf`` bps with ``n`` scored takes (A1's wallet
    score), below which nothing is quoted. ``z``: also pull the side the Coinbase gap says is at risk
    (``guard@``'s rule; 0 turns it off). ``k``: entry quotes are at least ``k`` times the mid's 1 s
    volatility from the mid (so the depth widens when the market does; 0: ``d`` only). ``jump`` and
    ``calm``: after the mid moves ``jump`` bps or more within a second, nothing is quoted for
    ``calm`` seconds (0: off)."""

    d: float = 1.0
    x: float = -1.0
    quiet: float = 5.0
    inf: float = 1.3
    n: float = 5.0
    z: float = 0.0
    k: float = 0.0
    jump: float = 0.0
    calm: float = 0.0
    lean: float = 1.0
    net: float = 0.0
    stop: float = 0.0
    hold: float = 0.0
    dd: float = 0.0
    pause: float = 600.0
    cool: float = 60.0
    stale: float = 3.0
    tol: float = 0.0

    def __post_init__(self) -> None:
        for setting in fields(self):
            if not math.isfinite(getattr(self, setting.name)):
                raise ValueError(f"hush {setting.name} must be finite")
        if self.d <= 0 or self.quiet < 0 or not 0 <= self.lean <= 1 or self.n < 1 or not float(self.n).is_integer():
            raise ValueError("hush requires d > 0, quiet >= 0, lean in [0, 1] and integer n >= 1")
        if self.k < 0 or self.jump < 0 or self.calm < 0:
            raise ValueError("hush k, jump and calm cannot be negative")
        if any(getattr(self, name) < 0 for name in ("net", "stop", "hold", "dd", "pause", "cool", "stale", "tol")):
            raise ValueError("hush risk limits cannot be negative")


def parse_hush(arg: str) -> HushParams:
    values: dict[str, float] = {}
    keys = tuple(f.name for f in fields(HushParams))
    for part in arg.split("/") if arg else ():
        key, _, value = part.partition("=")
        if key not in keys:
            raise AssertionError(f"unknown hush parameter {key!r} (one of {', '.join(keys)})")
        values[key] = float(value)
    return HushParams(**values)


class Hush:
    """``hush@d=<bps>/quiet=<s>/inf=<bps>/...``: the quiet-depth maker.

    It rests a bid and an ask ``d`` bps from Hyperliquid's mid, and only while the coin's informed
    wallets (A1's wallet score at least ``inf``) have not taken for ``quiet`` seconds. Otherwise it
    quotes nothing, on either side.

    From the 2026-11-07 check on 39.5 recorded hours: fills at least 1 bp from the mid earned +1.5 bp
    at 30 s when no such wallet had traded the coin for 5 s or more, and lost 0.35-1.6 bp when one
    had within the second. That edge is the size of the fee."""

    kind = "hush"

    def __init__(self, params: HushParams) -> None:
        self.p = params
        self.why = "not started"
        self.qty = 0.0
        self.calm_until = 0

    def half_spread(self, coin: CoinState) -> float:
        """The entry depth, bps: ``d``, or ``k`` times the 1 s volatility if that is more."""
        sigma = coin.sigma_1s if self.p.k > 0 else None
        return max(self.p.d, self.p.k * sigma) if sigma is not None else self.p.d

    def quotes(self, coin: CoinState, local_ms: int, position: float, max_position: float) -> Quotes:
        return self.targets(coin, local_ms, position, max_position, 0.0)

    def reason(self, coin: CoinState, local_ms: int) -> str:
        return self.why

    def targets(self, coin: CoinState, local_ms: int, position: float, max_position: float, net_usd: float) -> Quotes:
        p, top, tick = self.p, coin.top, coin.tick
        if top is None:
            self.why = "no book yet: no quotes"
            return None, None
        quiet_ms = coin.informed_quiet_ms(local_ms, p.inf, int(p.n))
        if quiet_ms < p.quiet * 1_000:
            self.why = f"an informed wallet took {quiet_ms / 1_000:.1f} s ago (< {p.quiet:g} s): no quotes"
            return None, None
        if p.jump > 0:
            move = abs(log_bps(coin.view.at(local_ms), coin.view.at(local_ms - 1_000)))
            if move >= p.jump:
                self.calm_until = local_ms + int(p.calm * 1_000)
            if local_ms < self.calm_until:
                self.why = f"the mid jumped {p.jump:g} bp or more in a second: no quotes for {(self.calm_until - local_ms) / 1_000:.0f} s"
                return None, None
        eps = 1e-9 * max(self.qty, 1e-12)
        units = position / self.qty if self.qty else 0.0
        d = self.half_spread(coin)
        x = d if p.x < 0 else p.x
        bid_bps = x if units < -1e-6 else d
        ask_bps = x if units > 1e-6 else d
        limit = p.lean * max_position
        bid = min(_down(top.mid * (1 - bid_bps / BPS), tick), top.bid) if position < limit - eps else None
        ask = max(_up(top.mid * (1 + ask_bps / BPS), tick), top.ask) if position > -limit + eps else None
        notes = [f"quiet {quiet_ms / 1_000:.0f} s: bid {bid_bps:g} bp, ask {ask_bps:g} bp from the mid"]
        if p.z > 0:
            gz = signal_z(coin.gap(), coin.gap_sigma)
            before = (bid, ask)
            bid, ask = pull((bid, ask), gz, p.z)
            if (bid, ask) != before:
                notes.append(said(gz, p.z, "gap z"))
        if p.net > 0:
            if net_usd >= p.net:
                bid = None
            if net_usd <= -p.net:
                ask = None
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
    ``mm@...`` (``paper.mm``), ``guard@...``, ``immune@...``, ``optimal@phi=<phi>``, or the lead-lag
    quoters ``disloc@...``, ``lead@...`` and ``sweep@...``, or the quiet-depth maker ``hush@...``."""
    kind, _, arg = name.partition("@")
    if kind == "mm":
        return MarketMaking(parse(arg))
    if kind == "guard":
        return Guard(parse_guard(arg))
    if kind == "immune":
        return Immune(parse_immune(arg))
    if kind == "optimal":
        return Optimal(parse_optimal(arg))
    if kind == "disloc":
        return Dislocation(parse_lead(arg))
    if kind == "lead":
        return LeadAS(parse_lead(arg))
    if kind == "sweep":
        return Sweep(parse_lead(arg))
    if kind == "hush":
        return Hush(parse_hush(arg))
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
