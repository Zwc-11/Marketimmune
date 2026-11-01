"""Forced-flow forecaster without margin data (plan B.4, margin-free prior).

The plan's forecaster needs each position's liquidation price, which needs its margin
(Hydromancer snapshots or ``clearinghouseState``). Until those are available, the liquidation
price comes from where liquidations actually trigger: on SOL in December 2025 the adverse move
from average entry to the liquidation fill clusters at ~2.5% (positions opened at maximum
leverage). So, for a wallet holding signed size ``s`` with entry ``e`` and current adverse
excursion ``x`` (fraction of entry), its liquidation distance is the *conditional median* of
the empirical distances ``delta`` given ``delta > x`` (it has survived ``x``):

    L = e * (1 - sign(s) * median(delta | delta > x))

Trigger probability over ``h`` seconds follows B.4: the log mark starts at the Binance-implied
mark ``m~ = mid * exp(gap)`` and moves with per-second volatility ``sigma``; by the reflection
principle ``pi = 2 Phi(-|d| / (sigma sqrt h))`` with ``d = ln(L / m~)``, and ``pi = 1`` when
``m~`` has already crossed ``L`` (fires at the next mark update). Positions above 100k USDC are
liquidated in 20% slices. Expected forced notional per side:

    F_bid = sum over longs of pi * |s| * m~ * slice,   F_ask = same over shorts.

Everything at time ``t`` uses fills strictly before ``t``, mids strictly before ``t`` and
Binance trades at or before ``t - latency``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.special import ndtr  # type: ignore[import-untyped]

FloatArray = npt.NDArray[np.float64]
SLICE_NOTIONAL = 100_000.0
SLICE_FRACTION = 0.2
BINARY_USD = 10_000.0
# per-horizon outputs, in the order the forecast grid stores them
FORECAST_FIELDS = ("Fraw_bid", "Fraw_ask", "P_any", "F_bid", "F_ask", "P_bid", "P_ask", "cascade")
# ndtr(-z) is exactly 0.0 from z = 37.7 on, so the reflection formula is only evaluated below
_Z_ZERO = 38.0
assert ndtr(-_Z_ZERO) == 0.0


def forecast_columns(horizons_s: Sequence[float]) -> list[str]:
    return [*(f"{name}_{int(h)}s" for h in horizons_s for name in FORECAST_FIELDS), "heatmap_bid_1pct", "heatmap_ask_1pct"]


def conditional_median_distance(sorted_delta: FloatArray, excursion: FloatArray) -> FloatArray:
    """Median of ``delta`` among samples above ``excursion`` (NaN when none are)."""
    i0 = np.searchsorted(sorted_delta, excursion, side="right")
    remaining = sorted_delta.size - i0
    out = np.full(excursion.shape, np.nan)
    ok = remaining > 0
    out[ok] = sorted_delta[(i0 + (remaining - 1) // 2)[ok]]
    return out


def trigger_probability(distance_log: FloatArray, sigma_1s: float | FloatArray, horizon_s: float | FloatArray) -> FloatArray:
    """``2 Phi(-|d| / (sigma sqrt h))``; 1 where already crossed (``d >= 0`` toward the mark).
    Broadcasts, so ``horizon_s`` of shape ``(H, 1)`` gives one row per horizon."""
    z = np.abs(distance_log) / np.maximum(sigma_1s * np.sqrt(horizon_s), 1e-12)
    p = np.zeros(z.shape)
    near = z < _Z_ZERO
    p[near] = 2.0 * ndtr(-z[near])
    out: FloatArray = np.where(distance_log >= 0.0, 1.0, np.minimum(p, 1.0))
    return out


@dataclass(frozen=True, slots=True)
class PositionBook:
    """Open positions at one instant: signed size and average entry (NaN = unknown).

    ``liq``, when given, is each position's known liquidation price: finite = exact (a
    position snapshot), ``inf`` = none (the account cannot be liquidated on this coin), NaN =
    unknown, so the margin-free prior applies (which needs the entry)."""

    size: FloatArray
    entry: FloatArray
    liq: FloatArray | None = None


def forecast_forced_flow(
    book: PositionBook,
    implied_mark: float,
    sigma_1s: float,
    sorted_delta: FloatArray,
    horizons_s: Sequence[float],
    hazard_scale: Mapping[float, float] | None = None,
    *,
    binary_usd: float = BINARY_USD,
    impact_bps_per_musd: float | None = None,
) -> dict[str, float]:
    """Expected forced notional per side and horizon, from open positions.

    Per horizon ``h`` (column suffix ``<h>s``):

    - ``F_bid`` / ``F_ask``: expected USD notional forced into bids (longs) and asks (shorts),
      hazard-scaled and, when ``impact_bps_per_musd`` is given, after one cascade pass.
    - ``Fraw_bid`` / ``Fraw_ask``: the same before the hazard scale and the cascade pass;
      ``forced_forecast`` fits the next day's scale from these.
    - ``P_any``: probability that any position triggers (first pass).
    - ``P_bid`` / ``P_ask``: probability that at least one position whose book slice is
      ``binary_usd`` or more triggers on that side (the binary target).
    - ``cascade``: final minus first-pass expected notional, both sides.

    Plus ``heatmap_bid_1pct`` / ``heatmap_ask_1pct``: notional with a point liquidation price
    within 1% of the mark (the static measure dashboards show).

    ``hazard_scale[h]`` multiplies every trigger probability at horizon ``h``. The distance prior
    comes only from wallets that *were* liquidated (the max-leverage ones), so applied to all open
    positions it overstates each one's hazard; the scale, fitted on earlier days (realised /
    forecast notional), corrects that selection bias.

    Cascade pass (plan B.4): forced sells push the mark down and trigger more. The first pass's
    net expected flow ``F_ask - F_bid`` moves the implied mark by ``impact_bps_per_musd`` per
    million USD; trigger probabilities are recomputed at the moved mark with liquidation prices
    held fixed.
    """
    given = np.full(book.size.shape, np.nan) if book.liq is None else book.liq
    known = (~np.isnan(book.entry) | ~np.isnan(given)) & (book.size != 0.0)
    size, entry, given = book.size[known], book.entry[known], given[known]
    if size.size == 0 or not math.isfinite(implied_mark) or (sorted_delta.size == 0 and np.isnan(given).any()):
        return dict.fromkeys(forecast_columns(horizons_s), 0.0)
    sign = np.sign(size)
    prior = np.isnan(given)
    liq = given.copy()
    if prior.any():
        excursion = np.maximum(-sign[prior] * (implied_mark - entry[prior]) / entry[prior], 0.0)
        liq[prior] = entry[prior] * (1.0 - sign[prior] * conditional_median_distance(sorted_delta, excursion))
    # Only positions with a liquidation price carry hazard. Selecting them up front keeps every
    # sum below over the same elements, in the same order, as summing the full book with zeros.
    usable = np.isfinite(liq) & (liq > 0.0)
    liq, long = liq[usable], sign[usable] > 0
    notional = np.abs(size[usable]) * implied_mark
    sliced = notional * np.where(notional > SLICE_NOTIONAL, SLICE_FRACTION, 1.0)
    big_long, big_short = long & (sliced >= binary_usd), ~long & (sliced >= binary_usd)
    h = np.asarray(horizons_s, dtype=np.float64)[:, None]
    scale = np.array([[1.0 if hazard_scale is None else hazard_scale.get(x, 1.0)] for x in horizons_s])

    def hazard(mark: float | FloatArray) -> FloatArray:
        # Longs liquidate into bids when the mark falls to L, shorts into asks when it rises to L;
        # the log distance is negative while the mark has not reached L. One row per horizon.
        return trigger_probability(np.log(np.where(long, liq / mark, mark / liq)), sigma_1s, h)

    raw = hazard(implied_mark)
    pi = np.minimum(raw * scale, 1.0)
    raw_usd, first_usd = raw * sliced, pi * sliced
    # NOTE: 1-D row sums on purpose: ndarray.sum(axis=1) rounds differently from summing each row.
    first_bid = [float(r[long].sum()) for r in first_usd]
    first_ask = [float(r[~long].sum()) for r in first_usd]
    final, f_bid, f_ask = pi, first_bid, first_ask
    if impact_bps_per_musd:
        moved = np.array(
            [[implied_mark * math.exp(impact_bps_per_musd * (a - b) / 1e6 / 1e4)] for b, a in zip(first_bid, first_ask, strict=True)]
        )
        final = np.minimum(hazard(moved) * scale, 1.0)
        final_usd = final * sliced
        f_bid = [float(r[long].sum()) for r in final_usd]
        f_ask = [float(r[~long].sum()) for r in final_usd]
    out: dict[str, float] = {}
    for k, hk in enumerate(horizons_s):
        hh = f"{int(hk)}s"
        out[f"Fraw_bid_{hh}"] = float(raw_usd[k][long].sum())
        out[f"Fraw_ask_{hh}"] = float(raw_usd[k][~long].sum())
        out[f"P_any_{hh}"] = float(1.0 - np.prod(1.0 - pi[k]))
        out[f"F_bid_{hh}"], out[f"F_ask_{hh}"] = f_bid[k], f_ask[k]
        out[f"P_bid_{hh}"] = float(1.0 - np.prod(1.0 - final[k][big_long]))
        out[f"P_ask_{hh}"] = float(1.0 - np.prod(1.0 - final[k][big_short]))
        out[f"cascade_{hh}"] = f_bid[k] + f_ask[k] - (first_bid[k] + first_ask[k])
    near = np.abs(liq / implied_mark - 1.0) <= 0.01
    out["heatmap_bid_1pct"] = float(notional[near & long].sum())
    out["heatmap_ask_1pct"] = float(notional[near & ~long].sum())
    return out


def forced_impact_samples(
    event_ts_ms: FloatArray,
    is_ask: npt.NDArray[np.bool_],
    notional: FloatArray,
    mid_ts_ms: FloatArray,
    mid: FloatArray,
    after_ms: float = 1_000.0,
) -> tuple[FloatArray, FloatArray]:
    """Signed forced notional per block (buys positive) and the log mid move in bps from the last
    mid strictly before the block to the last mid at or before ``after_ms`` later. Liquidation
    sells rest on the ask side of the order (they hit bids), so they count negative.

    The move also contains whatever triggered the liquidation, so the slope fitted from these
    samples is an upper bound on mechanical impact; that biases the cascade pass toward a larger
    correction, the conservative direction for the claim that the correction is small."""
    ts, inverse = np.unique(event_ts_ms, return_inverse=True)
    net = np.bincount(inverse, weights=np.where(is_ask, -notional, notional), minlength=ts.size)
    before = np.searchsorted(mid_ts_ms, ts, side="left") - 1
    after = np.searchsorted(mid_ts_ms, ts + after_ms, side="right") - 1
    ok = (before >= 0) & (after > before)
    return net[ok].astype(np.float64), (1e4 * np.log(mid[after[ok]] / mid[before[ok]])).astype(np.float64)


def impact_slope(signed_usd: FloatArray, ret_bps: FloatArray) -> float | None:
    """Least-squares slope through the origin, bps per million USD (None if no data)."""
    x = signed_usd / 1e6
    denom = float(x @ x)
    return float(x @ ret_bps) / denom if denom > 0.0 else None


def ewma_sigma_1s(mid_ts_ms: FloatArray, mid: FloatArray, grid_ms: FloatArray, halflife_s: float = 60.0) -> FloatArray:
    """Per-second volatility of log mid on a 1 s clock, EWMA, read strictly before each grid time."""
    secs = np.arange(math.floor(mid_ts_ms[0] / 1000.0) + 1, math.ceil(grid_ms.max() / 1000.0) + 1) * 1000.0
    idx = np.searchsorted(mid_ts_ms, secs, side="left") - 1  # last mid strictly before each second
    r2 = np.concatenate(([0.0], np.diff(np.log(mid[np.maximum(idx, 0)])) ** 2))
    var = pd.Series(r2).ewm(alpha=1.0 - 0.5 ** (1.0 / halflife_s), adjust=True).mean().to_numpy()
    j = np.searchsorted(secs, grid_ms, side="left") - 1  # last full second strictly before t
    out = np.full(grid_ms.shape, np.nan)
    ok = j >= 1
    out[ok] = np.sqrt(var[j[ok]])
    return out


def realised_forced_notional(
    event_ts_ms: FloatArray, is_ask: npt.NDArray[np.bool_], notional: FloatArray, grid_ms: FloatArray, horizon_s: float
) -> tuple[FloatArray, FloatArray]:
    """Forced notional hitting bids (liquidation sells) and asks in ``(t, t + h]``."""
    out = []
    for side_mask in (is_ask, ~is_ask):
        order = np.argsort(event_ts_ms[side_mask], kind="stable")
        ts = event_ts_ms[side_mask][order]
        cum = np.concatenate(([0.0], np.cumsum(notional[side_mask][order])))
        lo = np.searchsorted(ts, grid_ms, side="right")
        hi = np.searchsorted(ts, grid_ms + horizon_s * 1000.0, side="right")
        out.append(cum[hi] - cum[lo])
    return out[0], out[1]


def liquidation_distances(positions: pd.DataFrame) -> FloatArray:
    """Adverse move (fraction of entry) from average entry to each liquidation burst's first fill,
    for liquidated wallets whose entry was known (``build_positions`` rows, in file order, which
    is time order for every wallet)."""
    entry_before = positions.groupby("wallet", sort=False)["entry_px_after"].shift(1)
    forced = positions["forced"].to_numpy(dtype=bool) & entry_before.notna().to_numpy()
    first = positions[forced].assign(entry_before=entry_before[forced]).drop_duplicates(["wallet", "ts_ms"])
    sign = np.sign(first["start_pos"].to_numpy(dtype=np.float64))
    e = first["entry_before"].to_numpy(dtype=np.float64)
    move = -sign * (first["px"].to_numpy(dtype=np.float64) - e) / e
    out: FloatArray = np.sort(move[move > 0.0])
    return out


def brier_decomposition(p: FloatArray, y: FloatArray, bins: int = 10) -> dict[str, float]:
    """Brier score with Murphy's reliability / resolution / uncertainty split."""
    k = np.minimum((p * bins).astype(int), bins - 1)
    obar = float(y.mean())
    rel = res = 0.0
    for b in range(bins):
        m = k == b
        if m.any():
            rel += m.sum() * (p[m].mean() - y[m].mean()) ** 2
            res += m.sum() * (y[m].mean() - obar) ** 2
    return {
        "brier": float(np.mean((p - y) ** 2)),
        "reliability": rel / p.size,
        "resolution": res / p.size,
        "uncertainty": obar * (1.0 - obar),
    }
