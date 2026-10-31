"""Forecast forced liquidation flow per side and score it against what happened.

    python -m marketimmune.cli.forced_forecast --coin SOL --dates 20251201..20251231

Needs Silver positions (``build_positions``), Silver L2 mids, Silver order events
and the Binance zips. Each date is forecast on a grid (default every 10 s) with
the liquidation-distance prior and the hazard scale fitted on *earlier* dates
only: the first date seeds the prior, the second the scale, and scoring starts
on the third. Writes ``gold/hyperliquid/forced/<COIN>/<COIN>-<date>.parquet``
(forecasts, baselines, realised notional) and ``eval/forced_<coin>.json``.

Each grid row also carries open interest per side (wallets seen so far), onset
times of forced flow and the realised forced notional per side over the next
``h``; ``forced.evaluate`` scores the forecasts against zero, persistence, OI
change, volatility and the static heatmap, walk-forward by day. The cascade pass
uses a forced-flow impact fitted on earlier days (``--no-cascade`` to skip).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.cli.build_positions import positions_path
from marketimmune.features.cex_gap import (
    DEFAULT_LATENCY_MS,
    PriceSeries,
    cex_gap_features,
    read_binance_aggtrades_zip,
)
from marketimmune.forced.evaluate import evaluate_forecasts
from marketimmune.forced.forecaster import (
    BINARY_USD,
    PositionBook,
    ewma_sigma_1s,
    forced_impact_samples,
    forecast_forced_flow,
    impact_slope,
    liquidation_distances,
    realised_forced_notional,
)
from marketimmune.lake.tables import HyperliquidLakeLayout

FloatArray = npt.NDArray[np.float64]
DAY_MS = 86_400_000.0
ONSET_QUIET_MS = 60_000.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--binance-dir", type=Path,
                        default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--grid-s", type=float, default=10.0)
    parser.add_argument("--horizons", default="5,15,60")
    parser.add_argument("--latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    parser.add_argument("--binary-usd", type=float, default=BINARY_USD,
                        help="binary target: forced notional on a side within h at least this")
    parser.add_argument("--no-cascade", action="store_true",
                        help="skip the cascade pass (impact fitted on earlier days)")
    parser.add_argument("--evaluate-only", action="store_true",
                        help="score grid files already written, without forecasting again")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def _shift(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def _read_days(paths: list[Path], columns: list[str]) -> pd.DataFrame:
    frames = [pq.read_table(p, columns=columns).to_pandas() for p in paths if p.exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def onset_times(ts_ms: FloatArray, quiet_ms: float = ONSET_QUIET_MS) -> FloatArray:
    """Forced blocks with no forced flow on the same side in the previous ``quiet_ms``."""
    ts = np.unique(ts_ms)
    prev = np.concatenate(([-np.inf], ts[:-1]))
    out: FloatArray = ts[ts - prev > quiet_ms]
    return out


def onsets_on_grid(onsets: FloatArray, grid: FloatArray, grid_s: float) -> FloatArray:
    """First onset in ``(t, t + grid_s]`` for each grid time ``t`` (NaN if none)."""
    out = np.full(grid.size, np.nan)
    g = np.searchsorted(grid, onsets, side="left") - 1
    ok = (g >= 0) & (onsets <= grid[np.maximum(g, 0)] + grid_s * 1000.0)
    for gi, ts in zip(g[ok][::-1], onsets[ok][::-1], strict=True):  # earliest wins
        out[gi] = ts
    return out


def _wallet_arrays(state: dict[str, tuple[float, float]], wallets: npt.NDArray[Any]
                   ) -> tuple[pd.Index, npt.NDArray[np.int64], FloatArray, FloatArray]:
    keys = pd.Index(list(state), dtype=object)
    index = keys.append(pd.Index(pd.unique(wallets), dtype=object)).unique()
    codes = index.get_indexer(wallets).astype(np.int64)
    size = np.zeros(len(index))
    entry = np.full(len(index), np.nan)
    if len(keys):
        size[: len(keys)] = np.fromiter((v[0] for v in state.values()), np.float64, len(keys))
        entry[: len(keys)] = np.fromiter((v[1] for v in state.values()), np.float64, len(keys))
    return index, codes, size, entry


def forecast_day(args: argparse.Namespace, layout: HyperliquidLakeLayout, coin: str, date: str,
                 state: dict[str, tuple[float, float]], deltas: FloatArray,
                 hazard_scale: dict[float, float] | None = None,
                 impact_bps_per_musd: float | None = None,
                 ) -> tuple[pd.DataFrame, tuple[FloatArray, FloatArray]]:
    """Grid forecasts for one date and that day's forced-impact samples.

    ``state`` (wallet -> (size, entry)) is advanced through the whole day."""
    horizons = [float(h) for h in args.horizons.split(",")]
    binary_usd = getattr(args, "binary_usd", BINARY_USD)
    day0 = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC).timestamp() * 1000.0
    pos = pd.read_parquet(positions_path(args.lake_root, coin, date),
                          columns=["ts_ms", "wallet", "position_after", "entry_px_after"])
    pos = pos.sort_values("ts_ms", kind="stable")
    mids = _read_days([layout.silver_l2_book_path(coin, _shift(date, -1)),
                       layout.silver_l2_book_path(coin, date)], ["ts_ms", "mid"])
    mids = mids.sort_values("ts_ms", kind="stable")
    mid_ts = mids["ts_ms"].to_numpy(dtype=np.float64)
    mid = mids["mid"].to_numpy(dtype=np.float64)
    grid = np.arange(day0 + args.grid_s * 1000.0, day0 + DAY_MS - max(horizons) * 1000.0,
                     args.grid_s * 1000.0)
    grid = grid[grid > (mid_ts[0] if mid_ts.size else np.inf)]
    symbol = f"{coin}USDT"
    zips = [args.binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip"
            for d in (_shift(date, -1), date)]
    cex = PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])
    gap = cex_gap_features(grid, np.ones(grid.size), mid_ts, mid, cex,
                           latency_ms=args.latency_ms)["cex_gap_bps"]
    j = np.searchsorted(mid_ts, grid, side="left") - 1
    mid_before = np.where(j >= 0, mid[np.maximum(j, 0)], np.nan)
    implied = mid_before * np.exp(np.nan_to_num(gap) / 1e4)
    sigma = ewma_sigma_1s(mid_ts, mid, grid)
    ev = _read_days([layout.silver_order_events_path(coin, date),
                     layout.silver_order_events_path(coin, _shift(date, 1))],
                    ["ts_ms", "kind", "is_ask", "orig_sz", "sz", "opposite_best_px"])
    ev = ev[ev["kind"] == "liquidation"]
    ev_ts = ev["ts_ms"].to_numpy(dtype=np.float64)
    ev_ask = ev["is_ask"].to_numpy(dtype=bool)
    ev_usd = ((ev["orig_sz"] - ev["sz"]) * ev["opposite_best_px"]).to_numpy(dtype=np.float64)

    pts = pos["ts_ms"].to_numpy(dtype=np.float64)
    psize = pos["position_after"].to_numpy(dtype=np.float64)
    pentry = pos["entry_px_after"].to_numpy(dtype=np.float64)
    index, codes, size, entry = _wallet_arrays(state, pos["wallet"].to_numpy(dtype=object))

    def advance(k: int, k2: int) -> None:  # last row per wallet in [k, k2) wins
        if k2 > k:
            c = codes[k:k2][::-1]
            u, first = np.unique(c, return_index=True)
            size[u] = psize[k:k2][::-1][first]
            entry[u] = pentry[k:k2][::-1][first]

    rows: list[dict[str, Any]] = []
    k = 0
    for g in range(grid.size):
        k2 = int(np.searchsorted(pts, grid[g], side="left"))  # fills strictly before t
        advance(k, k2)
        k = k2
        live = size != 0.0
        f = forecast_forced_flow(PositionBook(size[live], entry[live]), float(implied[g]),
                                 float(sigma[g]) if np.isfinite(sigma[g]) else 0.0, deltas,
                                 horizons, hazard_scale, binary_usd=binary_usd,
                                 impact_bps_per_musd=impact_bps_per_musd)
        lsz = size[live]
        rows.append({"ts_ms": grid[g], "implied_mark": implied[g], "sigma_1s": sigma[g],
                     "oi_long_usd": float(lsz[lsz > 0].sum() * mid_before[g]),
                     "oi_short_usd": float(-lsz[lsz < 0].sum() * mid_before[g]), **f})
    advance(k, pts.size)  # rest of the day's fills, for the next date's state
    state.clear()
    keep = size != 0.0
    state.update(zip(index[keep], zip(size[keep].tolist(), entry[keep].tolist(), strict=True),
                     strict=True))
    out = pd.DataFrame(rows)
    for h in horizons:
        bid, ask = realised_forced_notional(ev_ts, ev_ask, ev_usd, grid, h)
        pbid, pask = realised_forced_notional(ev_ts, ev_ask, ev_usd, grid - h * 1000.0, h)
        out[f"real_bid_{int(h)}s"], out[f"real_ask_{int(h)}s"] = bid, ask
        out[f"persist_bid_{int(h)}s"], out[f"persist_ask_{int(h)}s"] = pbid, pask
    # liquidation sells rest on the ask (``is_ask``) and hit bids
    out["onset_bid_ms"] = onsets_on_grid(onset_times(ev_ts[ev_ask]), grid, args.grid_s)
    out["onset_ask_ms"] = onsets_on_grid(onset_times(ev_ts[~ev_ask]), grid, args.grid_s)
    out["date"] = date
    in_day = (ev_ts >= day0) & (ev_ts + 1_000.0 <= (mid_ts[-1] if mid_ts.size else 0.0))
    samples = forced_impact_samples(ev_ts[in_day], ev_ask[in_day], ev_usd[in_day], mid_ts, mid)
    return out, samples


def _write_result(args: argparse.Namespace, coin: str, frames: list[pd.DataFrame],
                  horizons: list[float]) -> dict[str, Any]:
    if not frames:
        return {"skipped": "need at least three dates: one seeds the prior, one the scale"}
    result = {"coin": coin, "dates": args.dates, "grid_s": args.grid_s,
              "cascade": not args.no_cascade,
              **evaluate_forecasts(pd.concat(frames, ignore_index=True), horizons,
                                   grid_s=args.grid_s, binary_usd=args.binary_usd)}
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
        frames = [f for f in (pd.read_parquet(p) for p in paths if p.exists())
                  if bool(f["hazard_scaled"].any())]
        return _write_result(args, coin, frames, horizons)
    state: dict[str, tuple[float, float]] = {}
    sample: list[FloatArray] = []
    impact_x: list[FloatArray] = []
    impact_y: list[FloatArray] = []
    frames = []
    # Selection-bias correction, fitted on earlier days only: realised / forecast
    # forced notional per horizon, from the unscaled first-pass forecasts.
    realised_sum = {h: 0.0 for h in horizons}
    forecast_sum = {h: 0.0 for h in horizons}
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        path = positions_path(args.lake_root, coin, date)
        if not path.exists() or not layout.silver_l2_book_path(coin, date).exists():
            continue
        deltas = np.sort(np.concatenate(sample)) if sample else np.zeros(0)
        if deltas.size:
            scale = {h: realised_sum[h] / forecast_sum[h] for h in horizons
                     if forecast_sum[h] > 0.0}
            kappa = (impact_slope(np.concatenate(impact_x), np.concatenate(impact_y))
                     if impact_x and not args.no_cascade else None)
            if kappa is not None:
                kappa = max(kappa, 0.0)  # a negative fitted impact is noise, not physics
            frame, (ix, iy) = forecast_day(args, layout, coin, date, state, deltas,
                                           scale or None, kappa)
            frame["hazard_scaled"] = bool(scale)
            frame["impact_bps_per_musd"] = kappa if kappa is not None else np.nan
            if scale:
                frames.append(frame)
            for h in horizons:
                hh = f"{int(h)}s"
                realised_sum[h] += float(frame[f"real_bid_{hh}"].sum() + frame[f"real_ask_{hh}"].sum())
                forecast_sum[h] += float(frame[f"Fraw_bid_{hh}"].sum()
                                         + frame[f"Fraw_ask_{hh}"].sum())
            impact_x.append(ix)
            impact_y.append(iy)
            out = forced_grid_path(args.lake_root, coin, date)
            out.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out, index=False)
            print(json.dumps({"date": date, "grid_points": len(frame), "prior_n": int(deltas.size),
                              "hazard_scale": {f"{int(h)}s": v for h, v in scale.items()},
                              "impact_bps_per_musd": kappa,
                              "elapsed_s": round(time.perf_counter() - t0, 1)}), flush=True)
        else:  # first date: only seeds the prior and the state
            last = pd.read_parquet(path, columns=["ts_ms", "wallet", "position_after",
                                                  "entry_px_after"])
            last = last.sort_values("ts_ms", kind="stable").drop_duplicates("wallet", keep="last")
            state.update(zip(last["wallet"], zip(last["position_after"].tolist(),
                                                 last["entry_px_after"].tolist(), strict=True),
                             strict=True))
        sample.append(liquidation_distances(pd.read_parquet(path)))
    return _write_result(args, coin, frames, horizons)


def forced_grid_path(lake_root: Path, coin: str, date: str) -> Path:
    symbol = coin.upper()
    return lake_root / "gold" / "hyperliquid" / "forced" / symbol / f"{symbol}-{date}.parquet"


def main(argv: list[str] | None = None) -> int:
    result = build(parse_args(argv))
    print(json.dumps(result, indent=2)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
