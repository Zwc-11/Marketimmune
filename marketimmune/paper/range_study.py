"""Range trading on the recorded mids: is there mean reversion to harvest, and does a band maker
earn more than the fees?

Everything here works on the 1-second mid series of each coin built from the paper runs'
``mids.parquet`` (the last mid in each second, carried forward; a gap of more than 10 minutes
breaks the series).

* ``variance_ratios``: Var(q-minute return) / (q * Var(1-minute return)) per coin, pooled over
  the segments, with a permutation null (the 1-minute returns shuffled within each segment, the
  same shuffle for every coin). Below 1 means mean reversion at that horizon.
* ``band_maker``: one position per coin. Flat, it rests a buy at the centre minus the band and a
  sell at the centre plus the band (the centre an exponential average of the mid, the band ``k``
  times the 1-minute volatility times the square root of ``horizon_min``, both from completed
  minutes only); a buy only below the ask and a sell only above the bid, so it is always a maker.
  A resting order fills only when the whole book trades through it (the mid half a tick past it). In a position it rests the exit at the
  centre (maker), and leaves as a taker at ``stop`` bands against it or after ``max_min`` minutes.
* ``hour_shuffle``: the same 1-second moves in a random order within each hour, which keeps each
  hour's volatility and net move and removes any pattern inside the hour; the band maker's result
  on many such copies is the null for its result on the real path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd

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
GAP_MS = 600_000


def load_mids(paths: list[Path]) -> pd.DataFrame:
    parts = []
    for p in paths:
        d = pd.read_parquet(p)
        d["seg"] = p.parent.name
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


def second_series(mids: pd.DataFrame) -> dict[str, pd.Series]:
    """Per coin, the last mid in each second on one continuous index; NaN inside gaps > 10 min."""
    out: dict[str, pd.Series] = {}
    for coin, g in mids.groupby("coin"):
        g = g.sort_values("t_ms")
        s = pd.Series(g["mid"].to_numpy(float), index=g["t_ms"].to_numpy() // 1000 * 1000)
        s = s[~s.index.duplicated(keep="last")]
        idx = np.arange(s.index[0], s.index[-1] + 1000, 1000)
        s = s.reindex(idx)
        seen = pd.Series(np.where(s.notna().to_numpy(), idx, np.nan), index=idx).ffill().to_numpy()
        s = s.ffill()
        s[(idx - seen) > GAP_MS] = np.nan
        out[str(coin)] = s
    return out


def minute_returns(series: dict[str, pd.Series]) -> list[FloatArray]:
    """Unbroken runs of 1-minute log returns, coins as columns (aligned on the same minutes)."""
    coins = sorted(series)
    frame = pd.concat([series[c][series[c].index % 60_000 == 0] for c in coins], axis=1, join="inner")
    lx = np.log(frame.to_numpy(float))
    ok = ~np.isnan(lx).any(axis=1)
    runs: list[FloatArray] = []
    start = None
    for i, v in enumerate(np.append(ok, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > 40:
                runs.append(np.diff(lx[start:i], axis=0))
            start = None
    return runs


def _vr(runs: list[FloatArray], q: int) -> FloatArray:
    num = np.zeros(runs[0].shape[1])
    den = np.zeros(runs[0].shape[1])
    for r in runs:
        c = np.cumsum(np.vstack([np.zeros(r.shape[1]), r]), axis=0)
        rq = c[q:] - c[:-q]
        num += (rq**2).sum(0)
        den += q * (r**2).sum(0) * len(rq) / len(r)
    return num / den


def variance_ratios(
    series: dict[str, pd.Series], horizons: tuple[int, ...] = (5, 15, 30), draws: int = 2000, seed: int = 0
) -> pd.DataFrame:
    coins = sorted(series)
    runs = minute_returns(series)
    rng = np.random.default_rng(seed)
    rows = []
    for q in horizons:
        obs = _vr(runs, q)
        null = np.array([_vr([r[rng.permutation(len(r))] for r in runs], q) for _ in range(draws)])
        for j, c in enumerate(coins):
            rows.append({"horizon_min": q, "coin": c, "vr": obs[j], "null_mean": null[:, j].mean(), "p_low": (null[:, j] <= obs[j]).mean()})
        rows.append(
            {"horizon_min": q, "coin": "mean", "vr": obs.mean(), "null_mean": null.mean(), "p_low": (null.mean(1) <= obs.mean()).mean()}
        )
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class Band:
    k: float = 1.0
    horizon_min: float = 30.0
    centre_halflife_min: float = 60.0
    stop: float = 3.0
    max_min: float = 120.0
    maker_fee_bps: float = 1.5
    taker_fee_bps: float = 4.5
    quote_usd: float = 500.0
    target: float = 0.0  # exit at the centre plus this many bands (1: sell at the top of the range)

    def label(self) -> str:
        tail = f"/target={self.target:g}" if self.target else ""
        return f"band@k={self.k:g}/h={self.horizon_min:g}/c={self.centre_halflife_min:g}/stop={self.stop:g}/max={self.max_min:g}{tail}"


def _inputs(s: pd.Series, halflife_min: float) -> tuple[npt.NDArray[np.int64], FloatArray, FloatArray, FloatArray]:
    x = s.to_numpy(float)
    t = s.index.to_numpy()
    alpha = 1 - 0.5 ** (1 / (halflife_min * 60))
    centre = pd.Series(x).ewm(alpha=alpha, adjust=False, ignore_na=True).mean().to_numpy()
    lx = np.log(x)
    r1 = np.full(len(x), np.nan)
    r1[60:] = lx[60:] - lx[:-60]
    at_minute = np.zeros(len(x), bool)
    at_minute[::60] = True
    sq = pd.Series(np.where(at_minute, r1**2, np.nan))
    var = sq.ewm(halflife=30, ignore_na=True, adjust=False, min_periods=20).mean().shift(60).ffill().to_numpy()
    return t, x, centre, np.sqrt(var)


def band_maker(s: pd.Series, coin: str, p: Band, half_rel: float | None = None) -> pd.DataFrame:
    """Round trips of the band maker on one coin's 1-second mids (decisions at i use data to i-1).
    ``half_rel``: half a tick as a fraction of the price (for a synthetic pair price), instead of
    the coin's tick."""
    t, x, c, sig = _inputs(s, p.centre_halflife_min)
    half = TICK[coin] / 2 if half_rel is None else float(half_rel * np.nanmedian(x))
    trades: list[tuple[int, int, int, float, float, str]] = []
    pos, entry, t_in, band_in = 0, np.nan, 0, np.nan
    for i in range(1, len(x)):
        if np.isnan(x[i]) or np.isnan(sig[i - 1]) or np.isnan(c[i - 1]):
            if pos != 0 and not np.isnan(x[i - 1]):
                trades.append((t_in, int(t[i - 1]), pos, entry, x[i - 1] - pos * half, "break"))
                pos = 0
            continue
        band = p.k * sig[i - 1] * np.sqrt(p.horizon_min) * x[i - 1]
        bid, ask = x[i - 1] - half, x[i - 1] + half
        if pos == 0:
            lo, hi = c[i - 1] - band, c[i - 1] + band
            if lo < ask and x[i] <= lo - half:
                pos, entry, t_in, band_in = 1, lo, int(t[i]), band
            elif hi > bid and x[i] >= hi + half:
                pos, entry, t_in, band_in = -1, hi, int(t[i]), band
            continue
        target = max(c[i - 1] + p.target * band, ask) if pos == 1 else min(c[i - 1] - p.target * band, bid)
        if pos * (x[i] - target) >= half:
            trades.append((t_in, int(t[i]), pos, entry, target, "target"))
            pos = 0
        elif pos * (entry - x[i]) >= p.stop * band_in:
            trades.append((t_in, int(t[i]), pos, entry, x[i] - pos * half, "stop"))
            pos = 0
        elif t[i] - t_in >= p.max_min * 60_000:
            trades.append((t_in, int(t[i]), pos, entry, x[i] - pos * half, "time"))
            pos = 0
    df = pd.DataFrame(trades, columns=["t_in", "t_out", "side", "px_in", "px_out", "exit"])
    df["coin"] = coin
    df["gross_bps"] = df["side"] * (df["px_out"] / df["px_in"] - 1) * 1e4
    df["fee_bps"] = p.maker_fee_bps + np.where(df["exit"] == "target", p.maker_fee_bps, p.taker_fee_bps)
    df["net_bps"] = df["gross_bps"] - df["fee_bps"]
    df["usd"] = df["net_bps"] * p.quote_usd / 1e4
    return df


def hour_shuffle(s: pd.Series, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    x = s.to_numpy(float)
    lx = np.log(x)
    r = np.diff(lx)
    ok = ~np.isnan(r)
    r = np.where(ok, r, 0.0)
    hour = np.arange(len(r)) // 3600
    for h in np.unique(hour):
        idx = np.where((hour == h) & ok)[0]
        r[idx] = r[rng.permutation(idx)]
    first = int(np.argmax(~np.isnan(lx)))
    path = np.full(len(x), np.nan)
    path[first:] = lx[first] + np.concatenate([[0.0], np.cumsum(r[first:])])
    y = np.exp(path)
    y[np.isnan(x)] = np.nan
    return pd.Series(y, index=s.index)


def run_all(series: dict[str, pd.Series], p: Band, from_ms: int | None = None) -> pd.DataFrame:
    parts = [band_maker(s, c, p) for c, s in series.items()]
    df = pd.concat([d for d in parts if len(d)], ignore_index=True) if any(len(d) for d in parts) else pd.DataFrame()
    if from_ms is not None and len(df):
        df = df[df["t_in"] >= from_ms]
    return df


def pair_series(coin: pd.Series, hedge: pd.Series, beta: float) -> pd.Series:
    """The price of $1 of the coin hedged with ``beta`` dollars of the other coin, as a level near
    the coin's price: exp(log coin - beta * (log hedge - log hedge at its first value))."""
    both = pd.concat([coin, hedge], axis=1, join="inner")
    lc, lh = np.log(both.iloc[:, 0]), np.log(both.iloc[:, 1])
    h0 = lh.dropna().iloc[0]
    return pd.Series(np.exp(lc - beta * (lh - h0)).to_numpy(), index=both.index)
