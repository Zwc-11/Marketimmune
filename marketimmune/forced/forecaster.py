"""Forced-flow forecaster without margin data (plan B.4, margin-free prior).

The plan's forecaster needs each position's liquidation price, which needs its
margin (Hydromancer snapshots or ``clearinghouseState``). Until those are
available, the liquidation price comes from where liquidations actually trigger:
on SOL in December 2025 the adverse move from average entry to the liquidation
fill clusters at ~2.5% (positions opened at maximum leverage). So, for a wallet
holding signed size ``s`` with entry ``e`` and current adverse excursion ``x``
(fraction of entry), its liquidation distance is the *conditional median* of the
empirical distances ``delta`` given ``delta > x`` (it has survived ``x``):

    L = e * (1 - sign(s) * median(delta | delta > x))

Trigger probability over ``h`` seconds follows B.4: the log mark starts at the
Binance-implied mark ``m~ = mid * exp(gap)`` and moves with per-second
volatility ``sigma``; by the reflection principle ``pi = 2 Phi(-|d| / (sigma sqrt h))``
with ``d = ln(L / m~)``, and ``pi = 1`` when ``m~`` has already crossed ``L``
(fires at the next mark update). Positions above 100k USDC are liquidated in 20%
slices. Expected forced notional per side:

    F_bid = sum over longs of pi * |s| * m~ * slice,   F_ask = same over shorts.

Everything at time ``t`` uses fills strictly before ``t``, mids strictly before
``t`` and Binance trades at or before ``t - latency``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]
SLICE_NOTIONAL = 100_000.0
SLICE_FRACTION = 0.2
BINARY_USD = 10_000.0
FORECAST_FIELDS = ("F_bid", "F_ask", "Fraw_bid", "Fraw_ask", "P_any", "P_bid", "P_ask", "cascade")


def conditional_median_distance(sorted_delta: FloatArray, excursion: FloatArray) -> FloatArray:
    """Median of ``delta`` among samples above ``excursion`` (NaN when none are)."""
    n = sorted_delta.size
    i0 = np.searchsorted(sorted_delta, excursion, side="right")
    remaining = n - i0
    mid = i0 + (remaining - 1) // 2
    out = np.full(excursion.shape, np.nan)
    ok = remaining > 0
    out[ok] = sorted_delta[mid[ok]]
    return out


def trigger_probability(distance_log: FloatArray, sigma_1s: FloatArray, horizon_s: float) -> FloatArray:
    """``2 Phi(-|d| / (sigma sqrt h))``; 1 where already crossed (``d >= 0`` toward the mark)."""
    from scipy.special import ndtr  # type: ignore[import-untyped]

    scale = np.maximum(sigma_1s * math.sqrt(horizon_s), 1e-12)
    p = 2.0 * ndtr(-np.abs(distance_log) / scale)
    out: FloatArray = np.where(distance_log >= 0.0, 1.0, np.minimum(p, 1.0))
    return out


@dataclass(frozen=True, slots=True)
class PositionBook:
    """Open positions at one instant: signed size and average entry (NaN = unknown)."""

    size: FloatArray
    entry: FloatArray


def forecast_forced_flow(
    book: PositionBook,
    implied_mark: float,
    sigma_1s: float,
    sorted_delta: FloatArray,
    horizons_s: Sequence[float],
    hazard_scale: dict[float, float] | None = None,
    *,
    binary_usd: float = BINARY_USD,
    impact_bps_per_musd: float | None = None,
) -> dict[str, float]:
    """Expected forced notional per side and horizon, from open positions.

    Per horizon ``h`` (column suffix ``<h>s``):

    - ``F_bid`` / ``F_ask``: expected USD notional forced into bids (longs) and
      asks (shorts), hazard-scaled and, when ``impact_bps_per_musd`` is given,
      after one cascade pass.
    - ``Fraw_bid`` / ``Fraw_ask``: the same before the hazard scale and the
      cascade pass; ``build`` fits the next day's scale from these.
    - ``P_any``: probability that any position triggers (first pass).
    - ``P_bid`` / ``P_ask``: probability that at least one position whose book
      slice is ``binary_usd`` or more triggers on that side (the binary target).
    - ``cascade``: final minus first-pass expected notional, both sides.

    Plus ``heatmap_bid_1pct`` / ``heatmap_ask_1pct``: notional with a point
    liquidation price within 1% of the mark (the static measure dashboards show).

    ``hazard_scale[h]`` multiplies every trigger probability at horizon ``h``. The
    distance prior comes only from wallets that *were* liquidated (the
    max-leverage ones), so applied to all open positions it overstates each one's
    hazard; the scale, fitted on earlier days (realised / forecast notional),
    corrects that selection bias.

    Cascade pass (plan B.4): forced sells push the mark down and trigger more. The
    first pass's net expected flow ``F_ask - F_bid`` moves the implied mark by
    ``impact_bps_per_musd`` per million USD; trigger probabilities are recomputed
    at the moved mark with liquidation prices held fixed.
    """
    known = ~np.isnan(book.entry) & (book.size != 0.0)
    size, entry = book.size[known], book.entry[known]
    out: dict[str, float] = {}
    if size.size == 0 or not math.isfinite(implied_mark) or sorted_delta.size == 0:
        for h in horizons_s:
            for name in FORECAST_FIELDS:
                out[f"{name}_{int(h)}s"] = 0.0
        out["heatmap_bid_1pct"] = out["heatmap_ask_1pct"] = 0.0
        return out
    sign = np.sign(size)
    excursion = np.maximum(-sign * (implied_mark - entry) / entry, 0.0)
    delta = conditional_median_distance(sorted_delta, excursion)
    liq = entry * (1.0 - sign * delta)
    usable = ~np.isnan(liq) & (liq > 0.0)
    safe = np.where(usable, liq, implied_mark)
    notional = np.abs(size) * implied_mark
    sliced = notional * np.where(notional > SLICE_NOTIONAL, SLICE_FRACTION, 1.0)
    longs, shorts = usable & (sign > 0), usable & (sign < 0)
    big = sliced >= binary_usd
    sig = np.full(size.shape, sigma_1s)

    def hazard(mark: float, h: float, scale: float) -> FloatArray:
        # Longs liquidate into bids when the mark falls to L, shorts into asks when
        # it rises to L; ``toward`` is negative while the mark has not reached L.
        toward = np.where(sign > 0, np.log(safe / mark), np.log(mark / safe))
        p = np.minimum(trigger_probability(toward, sig, h) * scale, 1.0)
        res: FloatArray = np.where(usable, p, 0.0)
        return res

    for h in horizons_s:
        hh = f"{int(h)}s"
        scale = 1.0 if hazard_scale is None else hazard_scale.get(h, 1.0)
        pi_raw = hazard(implied_mark, h, 1.0)
        pi = pi_raw if scale == 1.0 else hazard(implied_mark, h, scale)
        out[f"Fraw_bid_{hh}"] = float((pi_raw * sliced)[longs].sum())
        out[f"Fraw_ask_{hh}"] = float((pi_raw * sliced)[shorts].sum())
        f_bid, f_ask = float((pi * sliced)[longs].sum()), float((pi * sliced)[shorts].sum())
        out[f"P_any_{hh}"] = float(1.0 - np.prod(1.0 - pi[usable]))
        first = f_bid + f_ask
        if impact_bps_per_musd:
            moved = implied_mark * math.exp(impact_bps_per_musd * (f_ask - f_bid) / 1e6 / 1e4)
            pi = hazard(moved, h, scale)
            f_bid, f_ask = float((pi * sliced)[longs].sum()), float((pi * sliced)[shorts].sum())
        out[f"F_bid_{hh}"], out[f"F_ask_{hh}"] = f_bid, f_ask
        out[f"P_bid_{hh}"] = float(1.0 - np.prod(1.0 - pi[longs & big]))
        out[f"P_ask_{hh}"] = float(1.0 - np.prod(1.0 - pi[shorts & big]))
        out[f"cascade_{hh}"] = f_bid + f_ask - first
    near = usable & (np.abs(liq / implied_mark - 1.0) <= 0.01)
    out["heatmap_bid_1pct"] = float(notional[near & (sign > 0)].sum())
    out["heatmap_ask_1pct"] = float(notional[near & (sign < 0)].sum())
    return out


def forced_impact_samples(event_ts_ms: FloatArray, is_ask: npt.NDArray[np.bool_],
                          notional: FloatArray, mid_ts_ms: FloatArray, mid: FloatArray,
                          after_ms: float = 1_000.0) -> tuple[FloatArray, FloatArray]:
    """Signed forced notional per block (buys positive) and the log mid move in bps
    from the last mid strictly before the block to the last mid at or before
    ``after_ms`` later. Liquidation sells rest on the ask side of the order (they
    hit bids), so they count negative.

    The move also contains whatever triggered the liquidation, so the slope fitted
    from these samples is an upper bound on mechanical impact; that biases the
    cascade pass toward a larger correction, which is the conservative direction
    for the claim that the correction is small."""
    if event_ts_ms.size == 0 or mid_ts_ms.size == 0:
        return np.zeros(0), np.zeros(0)
    signed = np.where(is_ask, -notional, notional)
    ts, inverse = np.unique(event_ts_ms, return_inverse=True)
    net = np.bincount(inverse, weights=signed, minlength=ts.size)
    before = np.searchsorted(mid_ts_ms, ts, side="left") - 1
    after = np.searchsorted(mid_ts_ms, ts + after_ms, side="right") - 1
    ok = (before >= 0) & (after > before)
    ret = 1e4 * np.log(mid[after[ok]] / mid[before[ok]])
    return net[ok].astype(np.float64), ret.astype(np.float64)


def impact_slope(signed_usd: FloatArray, ret_bps: FloatArray) -> float | None:
    """Least-squares slope through the origin, bps per million USD (None if no data)."""
    x = signed_usd / 1e6
    denom = float(x @ x)
    return float(x @ ret_bps) / denom if denom > 0.0 else None


def ewma_sigma_1s(mid_ts_ms: FloatArray, mid: FloatArray, grid_ms: FloatArray,
                  halflife_s: float = 60.0) -> FloatArray:
    """Per-second volatility of log mid on a 1 s clock, EWMA, read strictly before each grid time."""
    if mid_ts_ms.size < 2:
        return np.full(grid_ms.shape, np.nan)
    start, end = math.floor(mid_ts_ms[0] / 1000.0) + 1, math.ceil(grid_ms.max() / 1000.0)
    secs = np.arange(start, end + 1) * 1000.0
    idx = np.searchsorted(mid_ts_ms, secs, side="left") - 1  # last mid strictly before each second
    lm = np.log(mid[np.maximum(idx, 0)])
    r2 = np.concatenate(([0.0], np.diff(lm) ** 2))
    alpha = 1.0 - 0.5 ** (1.0 / halflife_s)
    var = pd.Series(r2).ewm(alpha=alpha, adjust=True).mean().to_numpy()
    j = np.searchsorted(secs, grid_ms, side="left") - 1  # last full second strictly before t
    out = np.full(grid_ms.shape, np.nan)
    ok = j >= 1
    out[ok] = np.sqrt(var[j[ok]])
    return out


def realised_forced_notional(event_ts_ms: FloatArray, is_ask: npt.NDArray[np.bool_],
                             notional: FloatArray, grid_ms: FloatArray,
                             horizon_s: float) -> tuple[FloatArray, FloatArray]:
    """Forced notional hitting bids (liquidation sells) and asks in ``(t, t + h]``."""
    out = []
    for side_mask in (is_ask, ~is_ask):
        ts = event_ts_ms[side_mask]
        order = np.argsort(ts, kind="stable")
        ts = ts[order]
        cum = np.concatenate(([0.0], np.cumsum(notional[side_mask][order])))
        lo = np.searchsorted(ts, grid_ms, side="right")
        hi = np.searchsorted(ts, grid_ms + horizon_s * 1000.0, side="right")
        out.append(cum[hi] - cum[lo])
    return out[0], out[1]


def liquidation_distances(positions: pd.DataFrame) -> FloatArray:
    """Adverse move (fraction of entry) from average entry to each liquidation burst's
    first fill, for liquidated wallets whose entry was known (``build_positions`` rows)."""
    fr = positions.sort_values(["wallet", "ts_ms", "seq"], kind="stable")
    entry_before = fr.groupby("wallet")["entry_px_after"].shift(1)
    forced = fr["forced"].to_numpy(dtype=bool) & entry_before.notna().to_numpy()
    first = fr[forced].assign(entry_before=entry_before[forced]).groupby(
        ["wallet", "ts_ms"], as_index=False
    ).first()
    sign = np.sign(first["start_pos"].to_numpy(dtype=np.float64))
    e = first["entry_before"].to_numpy(dtype=np.float64)
    move = -sign * (first["px"].to_numpy(dtype=np.float64) - e) / e
    out: FloatArray = np.sort(move[move > 0.0])
    return out


def brier_decomposition(p: FloatArray, y: FloatArray, bins: int = 10) -> dict[str, float]:
    """Brier score with Murphy's reliability / resolution / uncertainty split."""
    k = np.minimum((p * bins).astype(int), bins - 1)
    n = p.size
    obar = float(y.mean())
    rel = res = 0.0
    for b in range(bins):
        m = k == b
        if m.any():
            rel += m.sum() * (p[m].mean() - y[m].mean()) ** 2
            res += m.sum() * (y[m].mean() - obar) ** 2
    return {"brier": float(np.mean((p - y) ** 2)), "reliability": rel / n,
            "resolution": res / n, "uncertainty": obar * (1.0 - obar)}
