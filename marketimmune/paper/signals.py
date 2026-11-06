"""Per-coin state the strategies read: Hyperliquid's top and depth as seen, the Coinbase reference, the
demeaned gap, taker flow, taker-wallet scores, and a walk-forward model of the next second's mid move.

**Gap.** ``ln(Coinbase mid) - ln(Hyperliquid mid)`` in bps, minus its EWMA (half-life 5 min). The
EWMA removes the perp-spot basis, so the gap is the part of the difference that has not had time to
close. Positive: Coinbase is above, so Hyperliquid's asks are at risk.

**Wallet scores.** For each taker wallet, the mean 10 s markout of its past trades on the
Hyperliquid mid (positive: the taker gained), shrunk to 0 with a prior weight of 20 trades.
Every coin feeds one table. Quote-time use only: ``tox_buy_5s`` / ``tox_sell_5s`` are the
notional-weighted scores of the takers that bought / sold in the last 5 s. The wallet of the next
taker is not known before its fill.

**Model.** Every 100 ms (``sample``) the features are stored with the seen mid. Every 10 min,
once 20 min of rows exist, a ridge regression of the next second's mid move (bps) on the
standardised features is refitted on all rows whose label is known. Each refit first scores the
previous fit on the rows it has not seen (out-of-sample R^2), so the log is a walk-forward record.

Times: ``local_ms`` is when a message arrived; ``t_ms`` is Hyperliquid's block time.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.paper.events import Depth, RefTop, Top, Trade

FloatArray = npt.NDArray[np.float64]
BPS = 1e4
GRID_MS = 100
HORIZON_MS = 1_000
BASIS_HALF_LIFE_MS = 300_000
WALLET_HORIZON_MS = 10_000
WALLET_PRIOR = 20.0
FLOW_MS = 5_000
WARMUP_ROWS = 12_000  # 20 min of 100 ms rows
REFIT_MS = 600_000
MAX_ROWS = 108_000  # 3 h
RIDGE_LAMBDA = 1.0
FEATURES = ("gap", "ref_ret_1s", "ref_ret_5s", "hl_ret_1s", "hl_ret_5s", "imb_1s", "imb_5s", "tox_buy_5s", "tox_sell_5s", "spread")


class Series:
    """Values in time order; ``at(t)`` is the last value at or before ``t``. Keeps ``keep_ms``."""

    def __init__(self, keep_ms: int) -> None:
        self.keep_ms = keep_ms
        self.t: list[int] = []
        self.v: list[float] = []

    def add(self, t: int, v: float) -> None:
        if self.t and t < self.t[-1]:
            t = self.t[-1]
        self.t.append(t)
        self.v.append(v)
        if len(self.t) > 4096 and t - self.t[0] > 2 * self.keep_ms:
            cut = bisect_right(self.t, t - self.keep_ms)
            del self.t[:cut], self.v[:cut]

    def at(self, t: int) -> float | None:
        i = bisect_right(self.t, t) - 1
        return self.v[i] if i >= 0 else None


def tick_size(px: float, sz_decimals: int) -> float:
    """Hyperliquid's perp price step at ``px``: 5 significant figures, at most ``6 - sz_decimals``
    decimals, and integers always allowed."""
    return min(1.0, max(10.0 ** (math.floor(math.log10(px)) - 4), 10.0 ** -(6 - sz_decimals)))


def on_tick(px: float, tick: float) -> float:
    """``px`` rounded to the decimals of ``tick``, so it compares equal to the feed's prices."""
    return round(px, max(0, -math.floor(math.log10(tick) + 1e-9)))


def log_bps(a: float | None, b: float | None) -> float:
    """``ln(a / b)`` in bps; 0 when either is missing."""
    return math.log(a / b) * BPS if a and b else 0.0


class Wallets:
    """Shrunk mean 10 s markout per taker wallet, from the taker's side (positive: the taker gained)."""

    def __init__(self) -> None:
        self.total: dict[str, float] = {}
        self.count: dict[str, int] = {}

    def score(self, wallet: str) -> float:
        return self.total.get(wallet, 0.0) / (self.count.get(wallet, 0) + WALLET_PRIOR)

    def add(self, wallet: str, markout_bps: float) -> None:
        self.total[wallet] = self.total.get(wallet, 0.0) + markout_bps
        self.count[wallet] = self.count.get(wallet, 0) + 1

    def state(self) -> dict[str, Any]:
        return {"total": self.total, "count": self.count}

    def load(self, state: dict[str, Any]) -> None:
        self.total, self.count = dict(state["total"]), {k: int(v) for k, v in state["count"].items()}


@dataclass(frozen=True, slots=True)
class Ridge:
    mean: FloatArray
    scale: FloatArray
    coef: FloatArray
    intercept: float

    @classmethod
    def fit(cls, x: FloatArray, y: FloatArray, lam: float = RIDGE_LAMBDA) -> Ridge:
        assert x.ndim == 2 and x.shape[0] == y.size > x.shape[1], f"{x.shape=} {y.shape=}"
        mean, scale = x.mean(axis=0), x.std(axis=0)
        scale[scale == 0] = 1.0
        z = (x - mean) / scale
        y0 = float(y.mean())
        coef = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - y0))
        return cls(mean, scale, coef, y0)

    def predict(self, x: FloatArray) -> FloatArray:
        out: FloatArray = ((x - self.mean) / self.scale) @ self.coef + self.intercept
        return out


def r2(y: FloatArray, pred: FloatArray) -> float:
    ss = float(((y - y.mean()) ** 2).sum())
    return 1.0 - float(((y - pred) ** 2).sum()) / ss if ss > 0 else 0.0


class CoinState:
    def __init__(self, coin: str, wallets: Wallets, sz_decimals: int | None = None) -> None:
        self.coin = coin
        self.wallets = wallets
        self.sz_decimals = sz_decimals
        self.top: Top | None = None
        self.depth: Depth | None = None
        self.ref: RefTop | None = None
        self.view = Series(120_000)  # local ms -> Hyperliquid mid as seen
        self.exch = Series(120_000)  # block ms -> Hyperliquid mid
        self.ref_view = Series(120_000)  # local ms -> Coinbase mid
        self.flow: deque[tuple[int, float, float, float]] = deque()  # local ms, signed notional, notional, taker score
        self.pending: deque[tuple[int, str, int, float]] = deque()  # due block ms, taker, +1 buy / -1 sell, mid
        self.basis: float | None = None
        self.basis_ms = 0
        self.mids: list[tuple[int, float]] = []  # block ms, mid: saved for the markouts
        self.rows: list[list[float]] = []
        self.row_ms: list[int] = []
        self.row_mid: list[float] = []
        self.model: Ridge | None = None
        self.fitted_ms = 0
        self.fit_log: list[dict[str, Any]] = []
        self._fit_upto = 0  # rows the current model was fitted on

    # --- events
    def on_top(self, ev: Top, local_ms: int) -> None:
        self.top = ev
        self.view.add(local_ms, ev.mid)
        self.exch.add(ev.t_ms, ev.mid)
        self.mids.append((ev.t_ms, ev.mid))
        while self.pending and self.pending[0][0] <= ev.t_ms:
            due, wallet, sign, mid0 = self.pending.popleft()
            mid1 = self.exch.at(due)
            if mid1 is not None:
                self.wallets.add(wallet, sign * (mid1 - mid0) / mid0 * BPS)

    def on_depth(self, ev: Depth) -> None:
        self.depth = ev

    def on_trade(self, ev: Trade, local_ms: int) -> None:
        notional = ev.px * ev.sz
        self.flow.append((local_ms, notional if ev.taker_buy else -notional, notional, self.wallets.score(ev.taker)))
        mid = self.exch.at(ev.t_ms)
        if mid is not None:
            self.pending.append((ev.t_ms + WALLET_HORIZON_MS, ev.taker, 1 if ev.taker_buy else -1, mid))

    def on_ref(self, ev: RefTop, local_ms: int) -> None:
        self.ref = ev
        self.ref_view.add(local_ms, ev.mid)

    @property
    def tick(self) -> float | None:
        if self.top is None or self.sz_decimals is None:
            return None
        return tick_size(self.top.mid, self.sz_decimals)

    # --- features
    def raw_gap(self) -> float | None:
        if self.top is None or self.ref is None:
            return None
        return log_bps(self.ref.mid, self.top.mid)

    def gap(self) -> float | None:
        raw = self.raw_gap()
        return None if raw is None or self.basis is None else raw - self.basis

    def features(self, local_ms: int) -> list[float] | None:
        gap = self.gap()
        if gap is None or self.top is None:
            return None
        while self.flow and self.flow[0][0] < local_ms - FLOW_MS:
            self.flow.popleft()
        signed = [0.0, 0.0]
        total = [0.0, 0.0]
        tox = [0.0, 0.0, 0.0, 0.0]  # buy score*notional, buy notional, sell score*notional, sell notional
        for t, s, n, score in self.flow:
            total[1] += n
            signed[1] += s
            if t >= local_ms - 1_000:
                total[0] += n
                signed[0] += s
            k = 0 if s > 0 else 2
            tox[k] += score * n
            tox[k + 1] += n
        ref_now, hl_now = self.ref_view.at(local_ms), self.view.at(local_ms)
        return [
            gap,
            log_bps(ref_now, self.ref_view.at(local_ms - 1_000)),
            log_bps(ref_now, self.ref_view.at(local_ms - 5_000)),
            log_bps(hl_now, self.view.at(local_ms - 1_000)),
            log_bps(hl_now, self.view.at(local_ms - 5_000)),
            signed[0] / total[0] if total[0] else 0.0,
            signed[1] / total[1] if total[1] else 0.0,
            tox[0] / tox[1] if tox[1] else 0.0,
            tox[2] / tox[3] if tox[3] else 0.0,
            (self.top.ask - self.top.bid) / self.top.mid * BPS,
        ]

    def predict(self, local_ms: int) -> float | None:
        if self.model is None:
            return None
        x = self.features(local_ms)
        return None if x is None else float(self.model.predict(np.asarray([x]))[0])

    # --- the 100 ms grid
    def sample(self, local_ms: int) -> None:
        raw = self.raw_gap()
        if raw is None or self.top is None:
            return
        if self.basis is None:
            self.basis = raw
        else:
            alpha = 1.0 - math.exp(-math.log(2) * (local_ms - self.basis_ms) / BASIS_HALF_LIFE_MS)
            self.basis += alpha * (raw - self.basis)
        self.basis_ms = local_ms
        x = self.features(local_ms)
        if x is None:
            return
        self.rows.append(x)
        self.row_ms.append(local_ms)
        self.row_mid.append(self.top.mid)
        if len(self.rows) > MAX_ROWS + 12_000:
            cut = len(self.rows) - MAX_ROWS
            del self.rows[:cut], self.row_ms[:cut], self.row_mid[:cut]
            self._fit_upto = max(0, self._fit_upto - cut)
        if local_ms - self.fitted_ms >= REFIT_MS and len(self.rows) >= WARMUP_ROWS:
            self.refit(local_ms)

    def labelled(self) -> tuple[FloatArray, FloatArray]:
        """Rows whose seen mid 1 s later is known, with that move in bps. A row whose next row 1 s on is
        missing (a reconnect, or the end of an earlier run) has no label."""
        t = np.asarray(self.row_ms, dtype=np.int64)
        mid = np.asarray(self.row_mid)
        j = np.searchsorted(t, t + HORIZON_MS, side="left")
        ok = j < t.size
        ok[ok] = t[j[ok]] - t[ok] <= HORIZON_MS + 2 * GRID_MS
        y = np.log(mid[j[ok]] / mid[ok]) * BPS
        return np.asarray(self.rows, dtype=np.float64)[ok], y

    def refit(self, local_ms: int) -> None:
        x, y = self.labelled()
        entry: dict[str, Any] = {"t_ms": local_ms, "rows": int(y.size)}
        if self.model is not None and y.size > self._fit_upto + 100:
            new = slice(self._fit_upto, y.size)
            entry["oos_rows"] = int(y.size - self._fit_upto)
            entry["oos_r2"] = r2(y[new], self.model.predict(x[new]))
        self.model = Ridge.fit(x, y)
        entry["in_r2"] = r2(y, self.model.predict(x))
        entry["coef"] = dict(zip(FEATURES, (round(float(c), 4) for c in self.model.coef), strict=True))
        self._fit_upto = int(y.size)
        self.fitted_ms = local_ms
        self.fit_log.append(entry)

    # --- carried across runs
    def state(self) -> dict[str, Any]:
        return {"rows": self.rows[-MAX_ROWS:], "row_ms": self.row_ms[-MAX_ROWS:], "row_mid": self.row_mid[-MAX_ROWS:], "basis": self.basis}

    def load(self, state: dict[str, Any], now_ms: int) -> None:
        """Rows and basis from an earlier run; the model is refitted at the first sample."""
        self.rows = [list(map(float, r)) for r in state["rows"]]
        self.row_ms = [int(t) for t in state["row_ms"]]
        self.row_mid = [float(m) for m in state["row_mid"]]
        self.basis = state["basis"]
        self.basis_ms = now_ms
        self.fitted_ms = now_ms - REFIT_MS
