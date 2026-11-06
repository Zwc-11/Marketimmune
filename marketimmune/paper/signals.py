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

**Online estimators** (on the 100 ms grid, for the strategies in ``paper.strategies``):

- ``sigma_1s``: the EWMA (half-life 5 min) standard deviation of the seen mid's 1 s log return, bps.
- ``gap_sigma``: the same for the gap itself.
- ``forecast``: the expected seen-mid move over the next 10 s, ``b * gap``. ``b`` is a
  recursive least-squares slope with exponential forgetting (half-life 30 min) and a ridge
  prior toward 0, fitted on each grid row's realised 10 s move. If the gap closes like an
  Ornstein-Uhlenbeck process and Hyperliquid does a share ``beta`` of the closing, ``b`` estimates
  ``beta * (1 - exp(-theta * 10 s))``.
- ``intensity_ratio``: each side's taker-arrival intensity with an exponential (Hawkes) kernel,
  ``lambda(t) = sum exp(-(t - t_i) / 2 s)`` over that side's trades, divided by its own 10-minute
  EWMA. Above 1, trades are arriving in a burst.

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
VOL_HALF_LIFE_MS = 300_000  # 1 s return variance and gap variance
FORECAST_MS = 10_000  # the lead-lag forecast's horizon
FORECAST_HALF_LIFE_MS = 1_800_000
FORECAST_PRIOR = 2_000.0  # ridge prior on the forecast's slope, in gap bps^2 of grid rows
HAWKES_DECAY_MS = 2_000
HAWKES_BASE_HALF_LIFE_MS = 600_000
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
        self.var_1s: float | None = None
        self.gap_var: float | None = None
        self.fc_pending: deque[tuple[int, float, float]] = deque()  # grid ms, gap, seen mid
        self.fc_sxx = 0.0
        self.fc_sxy = 0.0
        self.fc_ms = 0
        self.hawkes: dict[int, tuple[float, int]] = {1: (0.0, 0), -1: (0.0, 0)}  # side -> intensity, local ms
        self.hawkes_base: dict[int, float | None] = {1: None, -1: None}

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
        side = 1 if ev.taker_buy else -1
        self.hawkes[side] = (self.intensity(side, local_ms) + 1.0, local_ms)
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

    # --- online estimators
    def intensity(self, side: int, local_ms: int) -> float:
        lam, t = self.hawkes[side]
        return lam * math.exp(-max(local_ms - t, 0) / HAWKES_DECAY_MS)

    def intensity_ratio(self, side: int, local_ms: int) -> float | None:
        base = self.hawkes_base[side]
        return self.intensity(side, local_ms) / base if base else None

    @property
    def sigma_1s(self) -> float | None:
        return math.sqrt(self.var_1s) if self.var_1s is not None else None

    @property
    def gap_sigma(self) -> float | None:
        return math.sqrt(self.gap_var) if self.gap_var is not None else None

    @property
    def forecast_slope(self) -> float:
        return self.fc_sxy / (self.fc_sxx + FORECAST_PRIOR)

    def forecast(self) -> float | None:
        """Expected seen-mid move over the next 10 s, bps."""
        gap = self.gap()
        return None if gap is None else self.forecast_slope * gap

    def _estimate(self, local_ms: int, gap: float) -> None:
        a = 1.0 - math.exp(-math.log(2) * GRID_MS / VOL_HALF_LIFE_MS)
        r = log_bps(self.view.at(local_ms), self.view.at(local_ms - 1_000))
        self.var_1s = r * r if self.var_1s is None else self.var_1s + a * (r * r - self.var_1s)
        self.gap_var = gap * gap if self.gap_var is None else self.gap_var + a * (gap * gap - self.gap_var)
        mid = self.view.at(local_ms)
        if mid is not None:
            self.fc_pending.append((local_ms, gap, mid))
        while self.fc_pending and self.fc_pending[0][0] + FORECAST_MS <= local_ms:
            t0, g0, m0 = self.fc_pending.popleft()
            if t0 + FORECAST_MS + 2 * GRID_MS < local_ms or mid is None:
                continue  # a gap in the grid: no clean 10 s label
            decay = math.exp(-math.log(2) * max(local_ms - self.fc_ms, 0) / FORECAST_HALF_LIFE_MS) if self.fc_ms else 1.0
            y = log_bps(mid, m0)
            self.fc_sxx = decay * self.fc_sxx + g0 * g0
            self.fc_sxy = decay * self.fc_sxy + g0 * y
            self.fc_ms = local_ms
        b = 1.0 - math.exp(-math.log(2) * GRID_MS / HAWKES_BASE_HALF_LIFE_MS)
        for side in (1, -1):
            lam = self.intensity(side, local_ms)
            base = self.hawkes_base[side]
            self.hawkes_base[side] = lam if base is None else base + b * (lam - base)

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
            dt = local_ms - self.basis_ms if self.basis_ms else 0
            alpha = 1.0 - math.exp(-math.log(2) * max(dt, 0) / BASIS_HALF_LIFE_MS)
            self.basis += alpha * (raw - self.basis)
        self.basis_ms = local_ms
        x = self.features(local_ms)
        if x is None:
            return
        self._estimate(local_ms, x[0])
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

    def load(self, state: dict[str, Any]) -> None:
        """Rows and basis from an earlier run; the model is refitted at the first sample."""
        self.rows = [list(map(float, r)) for r in state["rows"]]
        self.row_ms = [int(t) for t in state["row_ms"]]
        self.row_mid = [float(m) for m in state["row_mid"]]
        self.basis = state["basis"]
        self.basis_ms = 0
        self.fitted_ms = -REFIT_MS
