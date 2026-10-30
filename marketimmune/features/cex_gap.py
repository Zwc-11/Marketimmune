"""Rung L1: the CEX-gap control (v3 plan, Workstream A.3).

Binance leads Hyperliquid by 600-800 ms, so a resting Hyperliquid quote is stale
when Binance has moved since Hyperliquid's mid last changed. For a fill at ``t``:

* ``cex_gap_bps``: Binance log return from ``t_c - latency`` to ``t - latency``,
  where ``t_c`` is when the Hyperliquid mid last changed strictly before ``t``.
  This is the staleness the maker's quote carries into the fill.
* ``cex_ret_<w>ms_bps``: Binance log return over the ``w`` ms ending at
  ``t - latency``.
* ``*_maker_bps``: the same signed to the maker (negative = Binance already
  moved against the side the maker was filled on).

``latency_ms`` is the maker's own Binance feed latency (default 300 ms, the plan's
conservative value): no Binance trade later than ``t - latency_ms`` is ever read,
and Hyperliquid mids are read strictly before ``t``. Every rung of the v3 ladder
from L1 up carries these columns, so a later signal has to beat them.
"""

from __future__ import annotations

import io
import math
import random
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow.csv as pacsv

FloatArray = npt.NDArray[np.float64]
AGGTRADES_COLUMNS = (
    "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
    "transact_time", "is_buyer_maker",
)
DEFAULT_LATENCY_MS = 300.0
DEFAULT_WINDOWS_MS = (100.0, 500.0, 1_000.0, 5_000.0)
BPS = 10_000.0


def cex_feature_columns(windows_ms: Sequence[float] = DEFAULT_WINDOWS_MS) -> tuple[str, ...]:
    return (
        "cex_gap_bps",
        "cex_gap_maker_bps",
        *(f"cex_ret_{int(w)}ms_bps" for w in windows_ms),
        "cex_ret_1000ms_maker_bps",
    )


CEX_FEATURE_COLUMNS = cex_feature_columns()


@dataclass(frozen=True, slots=True)
class PriceSeries:
    """Trade prices sorted by time (ms), held as log prices."""

    ts_ms: FloatArray
    log_px: FloatArray

    @classmethod
    def from_arrays(cls, ts_ms: npt.ArrayLike, px: npt.ArrayLike) -> PriceSeries:
        ts = np.asarray(ts_ms, dtype=np.float64)
        p = np.asarray(px, dtype=np.float64)
        if ts.shape != p.shape:
            raise ValueError("ts_ms and px must have the same length")
        if np.any(p <= 0.0):
            raise ValueError("prices must be positive")
        order = np.argsort(ts, kind="stable")
        return cls(ts_ms=ts[order], log_px=np.log(p[order]))

    @classmethod
    def concat(cls, parts: Sequence[PriceSeries]) -> PriceSeries:
        if not parts:
            return cls(np.zeros(0), np.zeros(0))
        ts = np.concatenate([p.ts_ms for p in parts])
        lp = np.concatenate([p.log_px for p in parts])
        order = np.argsort(ts, kind="stable")
        return cls(ts_ms=ts[order], log_px=lp[order])

    def at_or_before(self, t_ms: FloatArray) -> FloatArray:
        """Log price of the last trade with ``ts <= t`` (NaN when none)."""
        idx = np.searchsorted(self.ts_ms, t_ms, side="right") - 1
        out = np.full(np.shape(t_ms), np.nan)
        ok = idx >= 0
        out[ok] = self.log_px[idx[ok]]
        return out


def read_binance_aggtrades_zip(path: Path) -> PriceSeries:
    """One Binance Vision USD-M ``aggTrades`` daily zip -> :class:`PriceSeries`."""
    with zipfile.ZipFile(path) as zf:
        (name,) = zf.namelist()
        raw = zf.read(name)
    has_header = raw.startswith(b"agg_trade_id")
    read = pacsv.ReadOptions(column_names=None if has_header else list(AGGTRADES_COLUMNS))
    convert = pacsv.ConvertOptions(include_columns=["price", "transact_time"])
    table = pacsv.read_csv(io.BytesIO(raw), read_options=read, convert_options=convert)
    return PriceSeries.from_arrays(
        table["transact_time"].to_numpy().astype(np.float64),
        table["price"].to_numpy().astype(np.float64),
    )


def mid_change_times(mid_ts_ms: npt.ArrayLike, mid: npt.ArrayLike) -> FloatArray:
    """For each row of a sorted mid series, the time its current value started."""
    ts = np.asarray(mid_ts_ms, dtype=np.float64)
    m = np.asarray(mid, dtype=np.float64)
    changed = np.ones(ts.size, dtype=bool)
    changed[1:] = m[1:] != m[:-1]
    start_idx = np.maximum.accumulate(np.where(changed, np.arange(ts.size), 0))
    out: FloatArray = ts[start_idx]
    return out


def cex_gap_features(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    hl_mid_ts_ms: npt.ArrayLike,
    hl_mid: npt.ArrayLike,
    cex: PriceSeries,
    *,
    latency_ms: float = DEFAULT_LATENCY_MS,
    windows_ms: Sequence[float] = DEFAULT_WINDOWS_MS,
) -> dict[str, FloatArray]:
    """L1 features for each fill (NaN where a Binance or Hyperliquid price is missing)."""
    if latency_ms <= 0.0:
        raise ValueError("latency_ms must be positive: a zero latency reads the fill's own ms")
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    hl_ts = np.asarray(hl_mid_ts_ms, dtype=np.float64)
    change_ts = mid_change_times(hl_ts, hl_mid)
    j = np.searchsorted(hl_ts, t, side="left") - 1  # strictly before the fill
    t_c = np.full(t.shape, np.nan)
    t_c[j >= 0] = change_ts[j[j >= 0]]
    now = cex.at_or_before(t - latency_ms)
    out: dict[str, FloatArray] = {}
    with np.errstate(invalid="ignore"):
        then = cex.at_or_before(np.minimum(t_c, t) - latency_ms)
        out["cex_gap_bps"] = (now - then) * BPS
        out["cex_gap_maker_bps"] = side * out["cex_gap_bps"]
        for w in windows_ms:
            out[f"cex_ret_{int(w)}ms_bps"] = (now - cex.at_or_before(t - latency_ms - w)) * BPS
        out["cex_ret_1000ms_maker_bps"] = side * out["cex_ret_1000ms_bps"]
    return out


def verify_cex_gap_no_lookahead(
    fill_ts_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    hl_mid_ts_ms: npt.ArrayLike,
    hl_mid: npt.ArrayLike,
    cex: PriceSeries,
    *,
    latency_ms: float = DEFAULT_LATENCY_MS,
    sample: int = 200,
    seed: int = 0,
    atol: float = 1e-9,
) -> dict[str, Any]:
    """Fix B3 for L1: recompute sampled fills with every Hyperliquid mid at or after
    the fill and every Binance trade at or after it deleted; any change is look-ahead."""
    t = np.asarray(fill_ts_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    hl_ts = np.asarray(hl_mid_ts_ms, dtype=np.float64)
    hl_px = np.asarray(hl_mid, dtype=np.float64)
    full = cex_gap_features(t, side, hl_ts, hl_px, cex, latency_ms=latency_ms)
    rng = random.Random(seed)
    picks = sorted(rng.sample(range(t.size), min(sample, t.size)))
    mismatched = 0
    worst = 0.0
    for i in picks:
        a = int(np.searchsorted(hl_ts, t[i], side="left"))
        b = int(np.searchsorted(cex.ts_ms, t[i], side="left"))
        cut = cex_gap_features(
            t[i : i + 1], side[i : i + 1], hl_ts[:a], hl_px[:a],
            PriceSeries(cex.ts_ms[:b], cex.log_px[:b]), latency_ms=latency_ms,
        )
        diffs = [_diff(full[c][i], cut[c][0]) for c in full]
        worst = max(worst, *diffs)
        mismatched += int(max(diffs) > atol)
    return {
        "passed": bool(picks) and mismatched == 0,
        "n_checked": len(picks),
        "n_mismatched": mismatched,
        "max_abs_diff": worst,
        "latency_ms": latency_ms,
    }


def _diff(a: float, b: float) -> float:
    if math.isnan(a) and math.isnan(b):
        return 0.0
    if math.isnan(a) or math.isnan(b):
        return math.inf
    return abs(a - b)
