"""Forecast forced liquidation flow per side and score it against what happened.

    python -m marketimmune.cli.forced_forecast --coin SOL --dates 20251201..20251231

Needs Silver positions (``build_positions``), Silver L2 mids, Silver order events and the
Binance zips. Each date is forecast on a grid (every ``--grid-s``) with the liquidation-distance
prior, hazard scale and cascade impact fitted on *earlier* dates only: the first date seeds the
prior, the second the scale, and scoring starts on the third. Writes
``gold/hyperliquid/forced/<COIN>/<COIN>-<date>.parquet`` (forecasts, open interest per side,
realised and previous forced notional per horizon, onsets) and ``eval/forced_<coin>.json`` from
``forced.evaluate``.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.cli.build_positions import positions_path
from marketimmune.features.cex_gap import DEFAULT_LATENCY_MS, PriceSeries, cex_gap_features, read_binance_aggtrades_zip
from marketimmune.forced.evaluate import evaluate_forecasts
from marketimmune.forced.forecaster import (
    BINARY_USD,
    PositionBook,
    ewma_sigma_1s,
    forced_impact_samples,
    forecast_columns,
    forecast_forced_flow,
    impact_slope,
    liquidation_distances,
    realised_forced_notional,
)
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.logger import init_logger
from marketimmune.utils import DAY_MS, day_start_ms, parse_date_spec, shift_date

logger = init_logger(__name__)
FloatArray = npt.NDArray[np.float64]
ONSET_QUIET_MS = 60_000.0
POSITION_COLUMNS = ["ts_ms", "seq", "wallet", "start_pos", "px", "forced", "position_after", "entry_px_after"]
_CACHE_SIZE = 6  # a date reads its own files and its neighbours'


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--grid-s", type=float, default=10.0)
    parser.add_argument("--horizons", default="5,15,60")
    parser.add_argument("--latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    parser.add_argument(
        "--binary-usd", type=float, default=BINARY_USD, help="binary target: forced notional on a side within h at least this"
    )
    parser.add_argument("--no-cascade", action="store_true", help="skip the cascade pass (impact fitted on earlier days)")
    parser.add_argument("--evaluate-only", action="store_true", help="score grid files already written, without forecasting again")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def forced_grid_path(lake_root: Path, coin: str, date: str) -> Path:
    symbol = coin.upper()
    return lake_root / "gold" / "hyperliquid" / "forced" / symbol / f"{symbol}-{date}.parquet"


def onset_times(ts_ms: FloatArray, quiet_ms: float = ONSET_QUIET_MS) -> FloatArray:
    """Forced blocks with no forced flow on the same side in the previous ``quiet_ms``."""
    ts = np.unique(ts_ms)
    out: FloatArray = ts[ts - np.concatenate(([-np.inf], ts[:-1])) > quiet_ms]
    return out


def onsets_on_grid(onsets: FloatArray, grid: FloatArray, grid_s: float) -> FloatArray:
    """First onset in ``(t, t + grid_s]`` for each grid time ``t`` (NaN if none); ``onsets`` sorted."""
    out = np.full(grid.size, np.nan)
    g = np.searchsorted(grid, onsets, side="left") - 1
    ok = (g >= 0) & (onsets <= grid[np.maximum(g, 0)] + grid_s * 1000.0)
    cells, first = np.unique(g[ok], return_index=True)
    out[cells] = onsets[ok][first]
    return out


def _cached[T](cache: dict[Path, Any], path: Path, read: Callable[[Path], T]) -> T:
    if path not in cache:
        while len(cache) >= _CACHE_SIZE:
            cache.pop(next(iter(cache)))
        cache[path] = read(path)
    value: T = cache[path]
    return value


def _read_mids(path: Path) -> tuple[FloatArray, FloatArray]:
    table = pq.read_table(path, columns=["ts_ms", "mid"])
    return table["ts_ms"].to_numpy().astype(np.float64), table["mid"].to_numpy().astype(np.float64)


def _read_liquidations(path: Path) -> tuple[FloatArray, npt.NDArray[np.bool_], FloatArray]:
    """Liquidation orders: time, whether it rests on the ask (a forced sell) and filled notional."""
    cols = ["ts_ms", "is_ask", "orig_sz", "sz", "opposite_best_px"]
    t = pq.read_table(path, columns=cols, filters=[("kind", "==", "liquidation")])
    a = {c: t[c].to_numpy(zero_copy_only=False) for c in cols}
    return a["ts_ms"].astype(np.float64), a["is_ask"].astype(bool), ((a["orig_sz"] - a["sz"]) * a["opposite_best_px"]).astype(np.float64)


def forecast_day(
    args: argparse.Namespace,
    cache: dict[Path, Any],
    date: str,
    positions: pd.DataFrame,
    state: dict[str, tuple[float, float]],
    deltas: FloatArray,
    hazard_scale: dict[float, float] | None,
    impact_bps_per_musd: float | None,
) -> tuple[pd.DataFrame, tuple[FloatArray, FloatArray]]:
    """Grid forecasts for one date and that day's forced-impact samples; ``state``
    (wallet -> (size, entry)) is advanced through the whole day."""
    layout = HyperliquidLakeLayout(args.lake_root)
    coin = args.coin.upper()
    horizons = [float(h) for h in args.horizons.split(",")]
    prev, nxt = shift_date(date, -1), shift_date(date, 1)
    day0 = float(day_start_ms(date))
    mid_days = [_cached(cache, p, _read_mids) for p in (layout.silver_l2_book_path(coin, d) for d in (prev, date)) if p.exists()]
    mid_ts, mid = np.concatenate([m[0] for m in mid_days]), np.concatenate([m[1] for m in mid_days])
    order = np.argsort(mid_ts, kind="stable")
    mid_ts, mid = mid_ts[order], mid[order]
    step = args.grid_s * 1000.0
    grid = np.arange(day0 + step, day0 + DAY_MS - max(horizons) * 1000.0, step)
    grid = grid[grid > mid_ts[0]]
    symbol = f"{coin}USDT"
    zips = (args.binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip" for d in (prev, date))
    cex = PriceSeries.concat([_cached(cache, z, read_binance_aggtrades_zip) for z in zips if z.exists()])
    gap = cex_gap_features(grid, np.ones(grid.size), mid_ts, mid, cex, latency_ms=args.latency_ms)["cex_gap_bps"]
    j = np.searchsorted(mid_ts, grid, side="left") - 1
    mid_before = np.where(j >= 0, mid[np.maximum(j, 0)], np.nan)
    implied = mid_before * np.exp(np.nan_to_num(gap) / 1e4)
    sigma = ewma_sigma_1s(mid_ts, mid, grid)
    ev = [_cached(cache, p, _read_liquidations) for p in (layout.silver_order_events_path(coin, d) for d in (date, nxt)) if p.exists()]
    ev_ts, ev_ask, ev_usd = (np.concatenate([e[k] for e in ev]) for k in range(3))

    assert positions["ts_ms"].is_monotonic_increasing, f"{date}: positions out of time order"
    pts = positions["ts_ms"].to_numpy(dtype=np.float64)
    psize = positions["position_after"].to_numpy(dtype=np.float64)
    pentry = positions["entry_px_after"].to_numpy(dtype=np.float64)
    index = (
        pd.Index(list(state), dtype=object).append(pd.Index(pd.unique(positions["wallet"].to_numpy(dtype=object)), dtype=object)).unique()
    )
    codes = index.get_indexer(positions["wallet"].to_numpy(dtype=object))
    size = np.zeros(len(index))
    entry = np.full(len(index), np.nan)
    size[: len(state)] = [v[0] for v in state.values()]
    entry[: len(state)] = [v[1] for v in state.values()]

    def advance(k: int, k2: int) -> None:  # the last row per wallet in [k, k2) wins
        if k2 > k:
            u, last = np.unique(codes[k:k2][::-1], return_index=True)
            size[u] = psize[k:k2][::-1][last]
            entry[u] = pentry[k:k2][::-1][last]

    fields = forecast_columns(horizons)
    table = np.empty((grid.size, len(fields)))
    oi = np.empty((grid.size, 2))
    k = 0
    for g, k2 in enumerate(np.searchsorted(pts, grid, side="left").tolist()):  # fills strictly before t
        advance(k, k2)
        k = k2
        known = (size != 0.0) & ~np.isnan(entry)
        f = forecast_forced_flow(
            PositionBook(size[known], entry[known]),
            float(implied[g]),
            float(sigma[g]) if np.isfinite(sigma[g]) else 0.0,
            deltas,
            horizons,
            hazard_scale,
            binary_usd=args.binary_usd,
            impact_bps_per_musd=impact_bps_per_musd,
        )
        table[g] = [f[c] for c in fields]
        oi[g] = float(size[size > 0].sum() * mid_before[g]), float(-size[size < 0].sum() * mid_before[g])
    advance(k, pts.size)  # the rest of the day's fills, for the next date's state
    keep = size != 0.0
    state.clear()
    state.update(zip(index[keep], zip(size[keep].tolist(), entry[keep].tolist(), strict=True), strict=True))

    out = pd.DataFrame({"ts_ms": grid, "implied_mark": implied, "sigma_1s": sigma, "oi_long_usd": oi[:, 0], "oi_short_usd": oi[:, 1]})
    out[fields] = table
    for h in horizons:
        hh = f"{int(h)}s"
        out[f"real_bid_{hh}"], out[f"real_ask_{hh}"] = realised_forced_notional(ev_ts, ev_ask, ev_usd, grid, h)
        out[f"persist_bid_{hh}"], out[f"persist_ask_{hh}"] = realised_forced_notional(ev_ts, ev_ask, ev_usd, grid - h * 1000.0, h)
    # liquidation sells rest on the ask (``is_ask``) and hit bids
    out["onset_bid_ms"] = onsets_on_grid(onset_times(ev_ts[ev_ask]), grid, args.grid_s)
    out["onset_ask_ms"] = onsets_on_grid(onset_times(ev_ts[~ev_ask]), grid, args.grid_s)
    out["date"] = date
    in_day = (ev_ts >= day0) & (ev_ts + 1_000.0 <= mid_ts[-1])
    return out, forced_impact_samples(ev_ts[in_day], ev_ask[in_day], ev_usd[in_day], mid_ts, mid)


def _write_result(args: argparse.Namespace, coin: str, frames: list[pd.DataFrame], horizons: list[float]) -> dict[str, Any]:
    if not frames:
        return {"skipped": "need at least three dates: one seeds the prior, one the scale"}
    result = {
        "coin": coin,
        "dates": args.dates,
        "grid_s": args.grid_s,
        "cascade": not args.no_cascade,
        **evaluate_forecasts(pd.concat(frames, ignore_index=True), horizons, grid_s=args.grid_s, binary_usd=args.binary_usd),
    }
    out_json = args.out or Path("eval") / f"forced_{coin.lower()}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def build(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    horizons = [float(h) for h in args.horizons.split(",")]
    if args.evaluate_only:
        paths = [forced_grid_path(args.lake_root, coin, d) for d in parse_date_spec(args.dates)]
        frames = [f for f in (pd.read_parquet(p) for p in paths if p.exists()) if bool(f["hazard_scaled"].any())]
        return _write_result(args, coin, frames, horizons)
    state: dict[str, tuple[float, float]] = {}
    cache: dict[Path, Any] = {}
    sample: list[FloatArray] = []
    impact_x: list[FloatArray] = []
    impact_y: list[FloatArray] = []
    frames = []
    # Selection-bias correction, fitted on earlier days only: realised / forecast forced notional
    # per horizon, from the unscaled first-pass forecasts.
    realised_sum = dict.fromkeys(horizons, 0.0)
    forecast_sum = dict.fromkeys(horizons, 0.0)
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        path = positions_path(args.lake_root, coin, date)
        if not path.exists() or not layout.silver_l2_book_path(coin, date).exists():
            continue
        positions = pd.read_parquet(path, columns=POSITION_COLUMNS)
        deltas = np.sort(np.concatenate(sample)) if sample else np.zeros(0)
        if deltas.size:
            scale = {h: realised_sum[h] / forecast_sum[h] for h in horizons if forecast_sum[h] > 0.0}
            kappa = impact_slope(np.concatenate(impact_x), np.concatenate(impact_y)) if impact_x and not args.no_cascade else None
            if kappa is not None:
                kappa = max(kappa, 0.0)  # a negative fitted impact is noise, not physics
            frame, (ix, iy) = forecast_day(args, cache, date, positions, state, deltas, scale or None, kappa)
            frame["hazard_scaled"] = bool(scale)
            frame["impact_bps_per_musd"] = kappa if kappa is not None else np.nan
            if scale:
                frames.append(frame)
            for h in horizons:
                hh = f"{int(h)}s"
                realised_sum[h] += float(frame[f"real_bid_{hh}"].sum() + frame[f"real_ask_{hh}"].sum())
                forecast_sum[h] += float(frame[f"Fraw_bid_{hh}"].sum() + frame[f"Fraw_ask_{hh}"].sum())
            impact_x.append(ix)
            impact_y.append(iy)
            out = forced_grid_path(args.lake_root, coin, date)
            out.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out, index=False)
            info = {
                "date": date,
                "grid_points": len(frame),
                "prior_n": int(deltas.size),
                "hazard_scale": {f"{int(h)}s": v for h, v in scale.items()},
            }
            logger.info(json.dumps({**info, "impact_bps_per_musd": kappa, "elapsed_s": round(time.perf_counter() - t0, 1)}))
        else:  # first date: only seeds the prior and the state
            last = positions.drop_duplicates("wallet", keep="last")
            state.update(
                zip(last["wallet"], zip(last["position_after"].tolist(), last["entry_px_after"].tolist(), strict=True), strict=True)
            )
        sample.append(liquidation_distances(positions))
    return _write_result(args, coin, frames, horizons)


def main(argv: list[str] | None = None) -> int:
    result = build(parse_args(argv))
    print(json.dumps(result, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
