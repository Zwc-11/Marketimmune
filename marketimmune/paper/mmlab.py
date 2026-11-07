"""Market-making candidates on one-second bars (the lead-lag dislocation maker, a lead-lag
Avellaneda-Stoikov quoter and a sweep catcher), with a conservative fill rule.

Data per coin and second (``cli.paper_bars`` plus the trade extremes built by ``cli.paper_mmlab``):
the Hyperliquid best bid and ask at the end of the second, the Coinbase mid, the lowest price a
taker sold at and the highest a taker bought at during the second, and taker volume by side.

* **Fair price:** the Coinbase mid times the Hyperliquid/Coinbase basis (a 5-minute exponential
  average of the log ratio, from earlier seconds only). Coinbase leads Hyperliquid (IC 0.5 at 1 s),
  so a Hyperliquid price far from it is more likely to come back than to continue.
* **Timing:** quotes for second t are set from data to the end of second t-1. They are always
  passive: a bid below the previous ask, an ask above the previous bid, on the tick grid.
* **Fill rule (trade-through):** a resting bid at B fills in second t only if a taker sold below B
  during t, or the ask closed below B. A price that only touched B does not fill it (the queue
  ahead is unknown). Ask fills are symmetric.
* **Fees:** maker 1.5 bp, taker 4.5 bp. One unit is ``quote_usd`` of notional.

``dislocation``: one unit per coin. Flat, it rests a bid at fair x (1 - d) and an ask at
fair x (1 + d). In a position it rests the exit at fair x (1 +- x_exit) and leaves as a taker
after ``max_s`` seconds or ``stop`` bp against the entry.

``llas``: continuous two-sided quoting with an inventory of up to ``n_max`` units.
* **Half-width:** h = h0 + a * sigma, where sigma is the 1-minute volatility in bp (from earlier minutes).
* **Centre:** fair x (1 - s * h * q), skewed against the inventory q.
* **Positions:** marked to the mid at the end of each recording.

``sweep``: when Hyperliquid has moved at least ``move`` bp over the last ``w`` seconds, the gap to
fair has opened by at least half of that, and taker flow in that direction has been at least
``flow_usd``, it joins the touch on the other side for ``wait_s`` seconds. It exits at fair as a
maker, or as a taker after ``max_s`` or ``stop``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

try:
    from numba import njit
except ImportError:  # pragma: no cover - the simulators also run (slowly) without numba

    def njit(*a: Any, **k: Any) -> Any:  # type: ignore[no-redef]
        def wrap(f: Any) -> Any:
            return f

        return wrap if not a or not callable(a[0]) else a[0]


FloatArray = npt.NDArray[np.float64]

TICK = {
    "BTC": 1.0,
    "ETH": 0.1,
    "SOL": 0.001,
    "XRP": 0.0001,
    "LTC": 0.01,
    "BCH": 0.01,
    "LINK": 0.001,
    "AVAX": 0.001,
    "DOGE": 0.00001,
}


@dataclass
class Coin:
    coin: str
    t: npt.NDArray[np.int64]
    bid: FloatArray
    ask: FloatArray
    fair: FloatArray
    sell_min: FloatArray
    buy_max: FloatArray
    buy_usd: FloatArray
    sell_usd: FloatArray
    sigma: FloatArray  # 1-minute volatility in bp, from completed earlier minutes
    brk: npt.NDArray[np.bool_]  # True on the first second of each recording
    extra: dict[str, FloatArray] = field(default_factory=dict)


def load(bars: list[Path], extremes: Path, until_ms: int | None = None, from_ms: int | None = None) -> dict[str, Coin]:
    parts = []
    for b in bars:
        d = pd.read_parquet(b)
        x = extremes / b.name
        if x.exists():
            d = d.merge(pd.read_parquet(x), on=["coin", "t"], how="left")
        else:
            d["sell_min"] = np.nan
            d["buy_max"] = np.nan
        d["seg"] = b.stem
        parts.append(d)
    df = pd.concat(parts, ignore_index=True).sort_values(["coin", "t"])
    if until_ms is not None:
        df = df[df["t"] < until_ms]
    out: dict[str, Coin] = {}
    for coin, g in df.groupby("coin"):
        g = g.drop_duplicates("t", keep="last").reset_index(drop=True)
        brk = (g["seg"] != g["seg"].shift()).to_numpy() | (g["t"].diff().fillna(10**9).to_numpy() > 60_000)
        hl_mid = (g["hl_bid"] + g["hl_ask"]).to_numpy() / 2
        cb_mid = (g["cb_bid"] + g["cb_ask"]).to_numpy() / 2
        raw = np.log(hl_mid) - np.log(cb_mid)
        seg_id = np.cumsum(brk)
        basis = (
            pd.Series(raw).groupby(seg_id).transform(lambda s: s.ewm(halflife=300, ignore_na=True, adjust=False).mean().shift(1)).to_numpy()
        )
        fair = cb_mid * np.exp(basis)
        lm = pd.Series(np.log(hl_mid))
        r60 = (lm - lm.groupby(seg_id).shift(60)) * 1e4
        sq = pd.Series(np.where(np.arange(len(g)) % 60 == 0, r60**2, np.nan))
        var = sq.groupby(seg_id).transform(
            lambda s: s.ewm(halflife=30, ignore_na=True, adjust=False, min_periods=10).mean().shift(60).ffill()
        )
        sigma = np.sqrt(var.to_numpy())
        c = Coin(
            coin=str(coin),
            t=g["t"].to_numpy(np.int64),
            bid=g["hl_bid"].to_numpy(float),
            ask=g["hl_ask"].to_numpy(float),
            fair=fair,
            sell_min=g["sell_min"].to_numpy(float),
            buy_max=g["buy_max"].to_numpy(float),
            buy_usd=g["buy_usd"].to_numpy(float),
            sell_usd=g["sell_usd"].to_numpy(float),
            sigma=sigma,
            brk=brk,
        )
        if from_ms is not None:
            c.extra["score"] = (c.t >= from_ms).astype(float)
        out[str(coin)] = c
    return out


@njit(cache=True)
def _floor(p: float, tick: float) -> float:
    return float(np.floor(p / tick + 1e-9) * tick)


@njit(cache=True)
def _ceil(p: float, tick: float) -> float:
    return float(np.ceil(p / tick - 1e-9) * tick)


@njit(cache=True)
def _bid_fills(b: float, t: int, sell_min: FloatArray, ask: FloatArray, tick: float) -> bool:
    return bool((sell_min[t] == sell_min[t] and sell_min[t] < b - 1e-12) or ask[t] <= b - tick + 1e-12)


@njit(cache=True)
def _ask_fills(a: float, t: int, buy_max: FloatArray, bid: FloatArray, tick: float) -> bool:
    return bool((buy_max[t] == buy_max[t] and buy_max[t] > a + 1e-12) or bid[t] >= a + tick - 1e-12)


@njit(cache=True)
def _put(out: FloatArray, k: int, a: float, b: float, c: float, d: float, e: float, f: float, g: float) -> None:
    out[k, 0] = a
    out[k, 1] = b
    out[k, 2] = c
    out[k, 3] = d
    out[k, 4] = e
    out[k, 5] = f
    out[k, 6] = g


@njit(cache=True)
def _dislocation(
    bid: FloatArray,
    ask: FloatArray,
    fair: FloatArray,
    sell_min: FloatArray,
    buy_max: FloatArray,
    brk: npt.NDArray[np.bool_],
    gate_b: FloatArray,
    gate_a: FloatArray,
    tick: float,
    d: float,
    x_exit: float,
    max_s: int,
    stop: float,
    maker: float,
    taker: float,
) -> FloatArray:
    """Round trips as rows: entry index, exit index, side, entry px, exit px, net bp, exit kind."""
    n = len(bid)
    out = np.full((n // 2 + 1, 7), np.nan)
    k = 0
    pos = 0
    entry = 0.0
    i_in = 0
    for t in range(1, n):
        p = t - 1
        if brk[t] or fair[p] != fair[p] or bid[p] != bid[p]:
            if pos != 0 and bid[p] == bid[p]:
                px = bid[p] if pos == 1 else ask[p]
                _put(out, k, i_in, p, pos, entry, px, pos * (px / entry - 1) * 1e4 - maker - taker, 3)
                k += 1
                pos = 0
            continue
        if pos == 0:
            b = min(_floor(fair[p] * (1 - d * 1e-4), tick), ask[p] - tick)
            a = max(_ceil(fair[p] * (1 + d * 1e-4), tick), bid[p] + tick)
            fb = gate_b[p] > 0 and _bid_fills(b, t, sell_min, ask, tick)
            fa = gate_a[p] > 0 and _ask_fills(a, t, buy_max, bid, tick)
            if fb and not fa:
                pos, entry, i_in = 1, b, t
            elif fa and not fb:
                pos, entry, i_in = -1, a, t
            continue
        mid = (bid[p] + ask[p]) / 2
        if pos == 1:
            tgt = max(_ceil(fair[p] * (1 + x_exit * 1e-4), tick), bid[p] + tick)
            if _ask_fills(tgt, t, buy_max, bid, tick):
                _put(out, k, i_in, t, 1, entry, tgt, (tgt / entry - 1) * 1e4 - 2 * maker, 0)
                k += 1
                pos = 0
            elif (entry - mid) / entry * 1e4 >= stop or t - i_in >= max_s:
                _put(out, k, i_in, t, 1, entry, bid[t], (bid[t] / entry - 1) * 1e4 - maker - taker, 1 if t - i_in < max_s else 2)
                k += 1
                pos = 0
        else:
            tgt = min(_floor(fair[p] * (1 - x_exit * 1e-4), tick), ask[p] - tick)
            if _bid_fills(tgt, t, sell_min, ask, tick):
                _put(out, k, i_in, t, -1, entry, tgt, -(tgt / entry - 1) * 1e4 - 2 * maker, 0)
                k += 1
                pos = 0
            elif (mid - entry) / entry * 1e4 >= stop or t - i_in >= max_s:
                _put(out, k, i_in, t, -1, entry, ask[t], -(ask[t] / entry - 1) * 1e4 - maker - taker, 1 if t - i_in < max_s else 2)
                k += 1
                pos = 0
    return out[:k]


@njit(cache=True)
def _llas(
    bid: FloatArray,
    ask: FloatArray,
    fair: FloatArray,
    sigma: FloatArray,
    sell_min: FloatArray,
    buy_max: FloatArray,
    brk: npt.NDArray[np.bool_],
    tick: float,
    h0: float,
    a_sig: float,
    skew: float,
    n_max: int,
    maker: float,
) -> FloatArray:
    """Per second: the change in value marked to the mid (bp of one unit), the inventory after, and
    the number of fills. A recording's open inventory is marked, not closed, at its end."""
    n = len(bid)
    out = np.zeros((n, 3))
    q = 0
    cash = 0.0
    u = 0.0  # coins per unit: $1 of notional at the start of the recording
    last_val = 0.0
    for t in range(1, n):
        p = t - 1
        if brk[t] or fair[p] != fair[p] or bid[p] != bid[p] or sigma[p] != sigma[p]:
            q = 0
            cash = 0.0
            u = 0.0
            last_val = 0.0
            continue
        if u == 0.0:
            u = 1.0 / fair[p]
        h = (h0 + a_sig * sigma[p]) * 1e-4
        r = fair[p] * (1 - skew * h * q)
        nf = 0
        if q < n_max:
            b = min(_floor(r * (1 - h), tick), ask[p] - tick)
            if _bid_fills(b, t, sell_min, ask, tick):
                q += 1
                cash -= b * u * (1 + maker * 1e-4)
                nf += 1
        if q > -n_max:
            a = max(_ceil(r * (1 + h), tick), bid[p] + tick)
            if _ask_fills(a, t, buy_max, bid, tick):
                q -= 1
                cash += a * u * (1 - maker * 1e-4)
                nf += 1
        mid = (bid[t] + ask[t]) / 2
        val = cash + q * u * mid
        out[t, 0] = (val - last_val) * 1e4
        out[t, 1] = q
        out[t, 2] = nf
        last_val = val
    return out


@njit(cache=True)
def _sweep(
    bid: FloatArray,
    ask: FloatArray,
    fair: FloatArray,
    sell_min: FloatArray,
    buy_max: FloatArray,
    buy_usd: FloatArray,
    sell_usd: FloatArray,
    brk: npt.NDArray[np.bool_],
    tick: float,
    w: int,
    move: float,
    flow_usd: float,
    wait_s: int,
    max_s: int,
    stop: float,
    maker: float,
    taker: float,
    touch_fills: bool,
) -> FloatArray:
    n = len(bid)
    out = np.full((n // 2 + 1, 7), np.nan)
    k = 0
    pos = 0
    entry = 0.0
    i_in = 0
    armed = 0  # +1: bid armed (after a sell sweep), -1: ask armed
    until = 0
    seg_start = 0
    for t in range(1, n):
        p = t - 1
        if brk[t]:
            seg_start = t
        if brk[t] or fair[p] != fair[p] or bid[p] != bid[p]:
            if pos != 0 and bid[p] == bid[p]:
                px = bid[p] if pos == 1 else ask[p]
                _put(out, k, i_in, p, pos, entry, px, pos * (px / entry - 1) * 1e4 - maker - taker, 3)
                k += 1
                pos = 0
            armed = 0
            continue
        if pos == 0:
            if armed == 0 and p - w >= seg_start and fair[p - w] == fair[p - w]:
                m0 = (bid[p - w] + ask[p - w]) / 2
                m1 = (bid[p] + ask[p]) / 2
                mv = (m1 / m0 - 1) * 1e4
                g0 = (m0 / fair[p - w] - 1) * 1e4
                g1 = (m1 / fair[p] - 1) * 1e4
                fs = 0.0
                fb = 0.0
                for j in range(p - w + 1, p + 1):
                    fs += sell_usd[j]
                    fb += buy_usd[j]
                if mv <= -move and g1 - g0 <= -move / 2 and fs - fb >= flow_usd:
                    armed, until = 1, t + wait_s
                elif mv >= move and g1 - g0 >= move / 2 and fb - fs >= flow_usd:
                    armed, until = -1, t + wait_s
            if armed != 0 and t > until:
                armed = 0
            if armed == 1:
                b = bid[p]
                if _bid_fills(b, t, sell_min, ask, tick) or (touch_fills and sell_min[t] == sell_min[t] and sell_min[t] <= b):
                    pos, entry, i_in, armed = 1, b, t, 0
            elif armed == -1:
                a = ask[p]
                if _ask_fills(a, t, buy_max, bid, tick) or (touch_fills and buy_max[t] == buy_max[t] and buy_max[t] >= a):
                    pos, entry, i_in, armed = -1, a, t, 0
            continue
        mid = (bid[p] + ask[p]) / 2
        if pos == 1:
            tgt = max(_ceil(fair[p], tick), bid[p] + tick)
            if _ask_fills(tgt, t, buy_max, bid, tick):
                _put(out, k, i_in, t, 1, entry, tgt, (tgt / entry - 1) * 1e4 - 2 * maker, 0)
                k += 1
                pos = 0
            elif (entry - mid) / entry * 1e4 >= stop or t - i_in >= max_s:
                _put(out, k, i_in, t, 1, entry, bid[t], (bid[t] / entry - 1) * 1e4 - maker - taker, 1 if t - i_in < max_s else 2)
                k += 1
                pos = 0
        else:
            tgt = min(_floor(fair[p], tick), ask[p] - tick)
            if _bid_fills(tgt, t, sell_min, ask, tick):
                _put(out, k, i_in, t, -1, entry, tgt, -(tgt / entry - 1) * 1e4 - 2 * maker, 0)
                k += 1
                pos = 0
            elif (mid - entry) / entry * 1e4 >= stop or t - i_in >= max_s:
                _put(out, k, i_in, t, -1, entry, ask[t], -(ask[t] / entry - 1) * 1e4 - maker - taker, 1 if t - i_in < max_s else 2)
                k += 1
                pos = 0
    return out[:k]


EXITS = {0: "target", 1: "stop", 2: "time", 3: "break"}


def round_trips(c: Coin, rows: FloatArray, quote_usd: float) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["i_in", "i_out", "side", "px_in", "px_out", "net_bps", "exit"])
    df["coin"] = c.coin
    df["t_in"] = c.t[df["i_in"].astype(int)]
    df["t_out"] = c.t[df["i_out"].astype(int)]
    df["exit"] = df["exit"].map(EXITS)
    df["usd"] = df["net_bps"] * quote_usd / 1e4
    return df


@dataclass(frozen=True)
class Dislocation:
    d: float = 3.0
    x_exit: float = 0.0
    max_s: int = 120
    stop: float = 15.0
    maker: float = 1.5
    taker: float = 4.5
    quote_usd: float = 500.0

    def label(self) -> str:
        return f"disloc@d={self.d:g}/x={self.x_exit:g}/max={self.max_s}/stop={self.stop:g}"

    def run(self, c: Coin, gate_b: FloatArray | None = None, gate_a: FloatArray | None = None) -> pd.DataFrame:
        one = np.ones(len(c.t))
        rows = _dislocation(
            c.bid, c.ask, c.fair, c.sell_min, c.buy_max, c.brk,
            one if gate_b is None else gate_b, one if gate_a is None else gate_a,
            TICK.get(c.coin, 0.0), self.d, self.x_exit, self.max_s, self.stop, self.maker, self.taker,
        )  # fmt: skip
        return round_trips(c, rows, self.quote_usd)


@dataclass(frozen=True)
class Sweep:
    w: int = 3
    move: float = 4.0
    flow_usd: float = 5000.0
    wait_s: int = 5
    max_s: int = 60
    stop: float = 15.0
    maker: float = 1.5
    taker: float = 4.5
    quote_usd: float = 500.0
    touch_fills: bool = False  # True: a print at the joined price fills it (optimistic about the queue)

    def label(self) -> str:
        return f"sweep@w={self.w}/move={self.move:g}/flow={self.flow_usd:g}/max={self.max_s}"

    def run(self, c: Coin) -> pd.DataFrame:
        rows = _sweep(
            c.bid, c.ask, c.fair, c.sell_min, c.buy_max, c.buy_usd, c.sell_usd, c.brk,
            TICK.get(c.coin, 0.0), self.w, self.move, self.flow_usd, self.wait_s, self.max_s, self.stop, self.maker, self.taker, self.touch_fills,
        )  # fmt: skip
        return round_trips(c, rows, self.quote_usd)


@dataclass(frozen=True)
class LLAS:
    h0: float = 2.0
    a_sig: float = 0.5
    skew: float = 0.5
    n_max: int = 4
    maker: float = 1.5
    quote_usd: float = 250.0

    def label(self) -> str:
        return f"llas@h0={self.h0:g}/a={self.a_sig:g}/skew={self.skew:g}/n={self.n_max}"

    def run(self, c: Coin) -> pd.DataFrame:
        rows = _llas(
            c.bid, c.ask, c.fair, c.sigma, c.sell_min, c.buy_max, c.brk,
            TICK.get(c.coin, 0.0), self.h0, self.a_sig, self.skew, self.n_max, self.maker,
        )  # fmt: skip
        df = pd.DataFrame({"t": c.t, "pnl_bps": rows[:, 0], "inv": rows[:, 1], "fills": rows[:, 2]})
        df["usd"] = df["pnl_bps"] * self.quote_usd / 1e4
        df["coin"] = c.coin
        return df
