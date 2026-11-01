"""Forced-flow forecaster v2 (exploratory): the book and liquidation prices from node fills and
Hydromancer snapshots, against v1's margin-free prior on the same inputs.

    python -m marketimmune.cli.forced_v2 --coin SOL --dates 20251201..20251231
    python -m marketimmune.cli.forced_v2 --coin SOL --dates 20251201..20251231 --report eval/forced_v2_sol.json

Every variant reads node fills only (``forced.node_book``): the trade-implied mid, market
liquidations as the target, and positions rolled from each leg's ``start_position``.

- ``v1``: the book rolled from the first date; every liquidation price from the margin-free
  prior (``cli.forced_forecast``'s model, on node-fill inputs).
- ``v2a``: from the first snapshot on, the book is reset to each day's snapshot at its block and
  rolled between snapshots. A wallet that has not traded since the latest snapshot keeps the
  snapshot's liquidation price; any other gets the prior.
- ``v2``: the same book; a snapshot wallet that trades has its account rolled
  (``forced.node_book.Account``) and its liquidation price re-solved. Only wallets missing from
  the latest snapshot get the prior.

The rest is shared and fitted on earlier dates only, as in v1: the distance prior (from the
first date on), the hazard scale (realised over raw forecast notional, per variant, from that
variant's earlier forecasts) and the cascade impact. A variant forecasts once the prior has a
date behind it (and, for v2a and v2, from the first snapshot); its first forecast date only fits the
scale, and scoring starts the date after. Dates are processed in order, each once: the state
file carries the books, prior and fits, and ``--max-days`` bounds one call. Grid files are
``<out-dir>/<COIN>/<COIN>-<date>.<variant>.parquet`` in ``forced_forecast``'s format, plus
``book_usd`` and ``exact_share`` (the share of it priced from a snapshot). ``--report`` scores
each variant on its own days, v1 on v2's days, and each pair in ``PAIRS`` on their common days.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.cli.forced_forecast import onset_times, onsets_on_grid
from marketimmune.features.cex_gap import DEFAULT_LATENCY_MS, PriceSeries, cex_gap_features, read_binance_aggtrades_zip
from marketimmune.forced.evaluate import _calibrate, evaluate_forecasts, long_frame
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
from marketimmune.forced.node_book import (
    Account,
    account_from_snapshot,
    market_liquidations,
    read_legs,
    read_snapshot,
    roll_accounts,
    wallet_events,
)
from marketimmune.forced.positions import TOLERANCE, WalletState, roll_positions
from marketimmune.logger import init_logger
from marketimmune.models.compare import compare_rungs
from marketimmune.priority.fees import trade_mids
from marketimmune.utils import DAY_MS, day_start_ms, parse_date_spec, shift_date

logger = init_logger(__name__)
FloatArray = npt.NDArray[np.float64]
VARIANTS = ("v1", "v2a", "v2")
LIQ_KEY = {"v1": None, "v2a": "liq_a", "v2": "liq_b"}
PAIRS = (("v2", "v1"), ("v2a", "v1"), ("v2", "v2a"))  # (challenger, base)
TAIL_MS = 2 * 3_600_000.0  # mids carried into the next date (volatility and CEX-gap warm-up)
EVENT_TAIL_MS = 300_000.0  # liquidations carried into the next date (persistence)
# kinds of book rows: a fill, a snapshot reset (v2)
FILL, RESET = 0, 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--hydro-dir", type=Path, default=Path("data/bronze/hydromancer"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/gold/hyperliquid/forced_v2"))
    parser.add_argument("--grid-s", type=float, default=10.0)
    parser.add_argument("--horizons", default="5,15,60")
    parser.add_argument("--latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    parser.add_argument("--binary-usd", type=float, default=BINARY_USD)
    parser.add_argument("--no-cascade", action="store_true")
    parser.add_argument("--max-days", type=int, default=0, help="process at most this many new dates (0 = all)")
    parser.add_argument("--fresh", action="store_true", help="discard the state file and start from the first date")
    parser.add_argument("--report", type=Path, default=None, help="score the grid files written so far into this JSON")
    parser.add_argument(
        "--parts",
        default="variants,v1_on_v2,pairs",
        help="report sections to (re)compute: variants (or v1, v2a, v2 alone), v1_on_v2, pairs; the others are kept from an existing report file",
    )
    return parser.parse_args(argv)


@dataclass
class RunState:
    dates_done: list[str] = field(default_factory=list)
    v1_book: dict[str, WalletState] = field(default_factory=dict)
    v2_book: dict[str, WalletState] | None = None
    v2_liq_a: dict[str, float] = field(default_factory=dict)  # untouched snapshot wallets -> liq (inf = none)
    v2_accounts: dict[str, Account] = field(default_factory=dict)
    v2_liq_b: dict[str, float] = field(default_factory=dict)  # snapshot wallets -> rolled liq
    sample: list[FloatArray] = field(default_factory=list)
    realised_sum: dict[str, dict[float, float]] = field(default_factory=dict)
    forecast_sum: dict[str, dict[float, float]] = field(default_factory=dict)
    impact_x: list[FloatArray] = field(default_factory=list)
    impact_y: list[FloatArray] = field(default_factory=list)
    mid_tail: tuple[FloatArray, FloatArray] = field(default_factory=lambda: (np.zeros(0), np.zeros(0)))
    event_tail: tuple[FloatArray, npt.NDArray[np.bool_], FloatArray] = field(
        default_factory=lambda: (np.zeros(0), np.zeros(0, dtype=bool), np.zeros(0))
    )


def state_path(out_dir: Path, coin: str) -> Path:
    return out_dir / coin / "_state.pkl"


def grid_path(out_dir: Path, coin: str, date: str, variant: str) -> Path:
    return out_dir / coin / f"{coin}-{date}.{variant}.parquet"


def load_state(path: Path) -> RunState:
    if not path.exists():
        return RunState()
    with path.open("rb") as fh:
        state = pickle.load(fh)
    assert isinstance(state, RunState)
    return state


def save_state(path: Path, state: RunState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    with part.open("wb") as fh:
        pickle.dump(state, fh, protocol=pickle.HIGHEST_PROTOCOL)
    part.replace(path)


ROW_KEYS = ("ts", "wallet", "size", "entry", "liq_a", "liq_b", "kind")


@dataclass
class BookRows:
    """A book over one date: the state at the start, then one row per change in time order
    (fills, and for v2 the snapshot reset rows, all at the snapshot's time). ``liq_a`` / ``liq_b``
    are v2a's and v2's liquidation price after the row (NaN: the prior applies)."""

    start: dict[str, WalletState]
    start_liq_a: dict[str, float]
    start_liq_b: dict[str, float]
    rows: dict[str, Any]


def _rows(rolled: pd.DataFrame, liq_a: FloatArray | None = None, liq_b: FloatArray | None = None) -> dict[str, Any]:
    n = len(rolled)
    return {
        "ts": rolled["ts_ms"].to_numpy(dtype=np.float64),
        "wallet": rolled["wallet"].to_numpy(dtype=object),
        "size": rolled["position_after"].to_numpy(dtype=np.float64),
        "entry": rolled["entry_px_after"].to_numpy(dtype=np.float64),
        "liq_a": np.full(n, np.nan) if liq_a is None else liq_a,
        "liq_b": np.full(n, np.nan) if liq_b is None else liq_b,
        "kind": np.full(n, FILL, dtype=np.int8),
    }


def _cat(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        empty = {k: np.zeros(0) for k in ROW_KEYS}
        empty["wallet"], empty["kind"] = np.zeros(0, dtype=object), np.zeros(0, dtype=np.int8)
        return empty
    return {k: np.concatenate([p[k] for p in parts]) for k in ROW_KEYS}


def _copy_book(book: dict[str, WalletState]) -> dict[str, WalletState]:
    return {w: WalletState(s.position, s.entry_px, s.last_ts_ms) for w, s in book.items() if abs(s.position) > TOLERANCE}


def _segment(state: RunState, coin: str, events: pd.DataFrame, parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll v2's book, accounts and snapshot prices through fills between two resets."""
    assert state.v2_book is not None
    rolled, state.v2_book, stats = roll_positions(events, state.v2_book)
    for w in set(events["wallet"]):
        state.v2_liq_a.pop(w, None)  # traded since the snapshot: v2a falls back to the prior
    liq_b = roll_accounts(coin, events, state.v2_accounts)
    known = ~np.isnan(liq_b)
    state.v2_liq_b.update(zip(events["wallet"].to_numpy(dtype=object)[known], liq_b[known].tolist(), strict=True))
    parts.append(_rows(rolled, None, liq_b))
    return stats.to_dict()


def roll_v2(state: RunState, coin: str, events: pd.DataFrame, snap: pd.DataFrame | None, info: dict[str, Any]) -> BookRows | None:
    """v2's book over the date: fills before the snapshot's block on the previous book, the
    reset to the snapshot, then the fills after it."""
    if state.v2_book is None and snap is None:
        return None
    start = _copy_book(state.v2_book) if state.v2_book is not None else {}
    start_a, start_b = dict(state.v2_liq_a), dict(state.v2_liq_b)
    parts: list[dict[str, Any]] = []
    if snap is None:
        info["v2_roll"] = _segment(state, coin, events, parts)
    else:
        block = int(snap["snapshot_block"].iloc[0])
        t_snap = float(snap["snapshot_ts_ms"].iloc[0])
        if state.v2_book is not None:
            _segment(state, coin, events[events["block_number"] <= block], parts)
        users = snap["user"].tolist()
        liq = np.nan_to_num(snap["liquidation_price"].to_numpy(dtype=np.float64), nan=np.inf)
        book = {
            w: WalletState(position=float(sz), entry_px=float(e)) for w, sz, e in zip(users, snap["size"], snap["entry_price"], strict=True)
        }
        gone = [w for w in (state.v2_book or {}) if w not in book]
        n_gone = len(gone)
        snap_liq = np.concatenate([liq, np.full(n_gone, np.nan)])
        parts.append(
            {
                "ts": np.full(len(users) + n_gone, t_snap),
                "wallet": np.array([*users, *gone], dtype=object),
                "size": np.concatenate([snap["size"].to_numpy(dtype=np.float64), np.zeros(n_gone)]),
                "entry": np.concatenate([snap["entry_price"].to_numpy(dtype=np.float64), np.full(n_gone, np.nan)]),
                "liq_a": snap_liq,
                "liq_b": snap_liq.copy(),
                "kind": np.full(len(users) + n_gone, RESET, dtype=np.int8),
            }
        )
        state.v2_book = book
        state.v2_liq_a = dict(zip(users, liq.tolist(), strict=True))
        state.v2_liq_b = dict(state.v2_liq_a)
        state.v2_accounts = {
            r.user: account_from_snapshot(
                coin, float(r.size), float(r.notional), float(r.liquidation_price), float(r.account_value),
                r.leverage_type == "isolated", float(r.leverage),
            )
            for r in snap.itertuples()
        }  # fmt: skip
        info["v2_roll"] = _segment(state, coin, events[events["block_number"] > block], parts)  # breaks: snapshot vs fills
    rows = _cat(parts)
    assert np.all(np.diff(rows["ts"]) >= 0.0), "book rows out of time order"
    return BookRows(start, start_a, start_b, rows)


class GridBook:
    """Walks ``BookRows`` forward: the book strictly before each grid time, with v2a's and v2's
    liquidation prices (NaN where the prior applies).

    A known price the mark has passed is stale if the wallet still holds the position one grid
    step later: liquidation fires at the next mark update (seconds), and a fill would have
    changed the row. Off-coin profit, deposits and funding move a cross account's real price
    between snapshots, and without this rule such a position would count as certain to
    liquidate at every grid time. A stale price becomes NaN (the prior, conditioned on surviving
    the excursion) until the wallet's next row."""

    def __init__(self, b: BookRows) -> None:
        rows = b.rows
        index = pd.Index(list(b.start), dtype=object).append(pd.Index(pd.unique(rows["wallet"]), dtype=object)).unique()
        extra = [w for w in (*b.start_liq_a, *b.start_liq_b) if w not in index]
        index = index.append(pd.Index(pd.unique(np.array(extra, dtype=object)), dtype=object)) if extra else index
        self.index = index
        self.codes = index.get_indexer(rows["wallet"])
        n = len(index)
        self.arrays = {"size": np.zeros(n), "entry": np.full(n, np.nan), "liq_a": np.full(n, np.nan), "liq_b": np.full(n, np.nan)}
        c = index.get_indexer(list(b.start))
        self.arrays["size"][c] = [s.position for s in b.start.values()]
        self.arrays["entry"][c] = [s.entry_px for s in b.start.values()]
        for key, start in (("liq_a", b.start_liq_a), ("liq_b", b.start_liq_b)):
            if start:
                self.arrays[key][index.get_indexer(list(start))] = list(start.values())
        self.rows = rows
        self.k = 0
        self.crossed = {key: np.zeros(n, dtype=bool) for key in ("liq_a", "liq_b")}
        self.expired_usd = dict.fromkeys(("liq_a", "liq_b"), 0.0)

    def advance_to(self, t_ms: float, mark: float) -> None:
        k2 = int(np.searchsorted(self.rows["ts"], t_ms, side="left"))
        if k2 > self.k:  # the last row per wallet wins
            u, last = np.unique(self.codes[self.k : k2][::-1], return_index=True)
            for key, arr in self.arrays.items():
                arr[u] = self.rows[key][self.k : k2][::-1][last]
            for flags in self.crossed.values():
                flags[u] = False
            self.k = k2
        if not math.isfinite(mark):
            return
        size = self.arrays["size"]
        for key, flags in self.crossed.items():
            liq = self.arrays[key]
            now = ((size > 0.0) & np.isfinite(liq) & (liq >= mark)) | ((size < 0.0) & (liq <= mark))
            stale = now & flags
            if stale.any():
                self.expired_usd[key] += float(np.abs(size[stale]).sum() * mark)
                liq[stale] = np.nan
            flags[:] = now & ~stale

    def book(self, mark: float, liq_key: str | None) -> tuple[PositionBook, float, float]:
        """The open book with ``liq_key``'s prices, its notional at ``mark``, and the share of it
        that has a snapshot-based price."""
        size = self.arrays["size"]
        open_ = size != 0.0
        notional = np.abs(size[open_]) * mark
        total = float(notional.sum())
        liq = None if liq_key is None else self.arrays[liq_key][open_]
        exact = float(notional[~np.isnan(liq)].sum() / total) if liq is not None and total > 0 else 0.0
        return PositionBook(size[open_], self.arrays["entry"][open_], liq), total, exact


def forecast_day(args: argparse.Namespace, state: RunState, date: str) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    coin = args.coin.upper()
    horizons = [float(h) for h in args.horizons.split(",")]
    legs = read_legs(args.node_dir, coin, date)
    assert legs is not None, f"{coin} {date}: no node fills"
    day0 = float(day_start_ms(date))
    info: dict[str, Any] = {"date": date}

    mids = trade_mids(legs)
    mt = (mids["t"].dt.epoch("ns").to_numpy() / 1e6).astype(np.float64)
    mid_ts = np.concatenate([state.mid_tail[0], mt])
    mid = np.concatenate([state.mid_tail[1], mids["mid"].to_numpy().astype(np.float64)])
    order = np.argsort(mid_ts, kind="stable")
    mid_ts, mid = mid_ts[order], mid[order]
    step = args.grid_s * 1000.0
    grid = np.arange(day0 + step, day0 + DAY_MS - max(horizons) * 1000.0, step)
    grid = grid[grid > mid_ts[0]]
    symbol = f"{coin}USDT"
    zips = [args.binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip" for d in (shift_date(date, -1), date)]
    assert zips[1].exists(), f"missing {zips[1]}"
    cex = PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])
    gap = cex_gap_features(grid, np.ones(grid.size), mid_ts, mid, cex, latency_ms=args.latency_ms)["cex_gap_bps"]
    j = np.searchsorted(mid_ts, grid, side="left") - 1
    mid_before = np.where(j >= 0, mid[np.maximum(j, 0)], np.nan)
    implied = mid_before * np.exp(np.nan_to_num(gap) / 1e4)
    sigma = ewma_sigma_1s(mid_ts, mid, grid)

    ev_ts, ev_ask, ev_usd = market_liquidations(legs)
    all_ts = np.concatenate([state.event_tail[0], ev_ts])
    all_ask = np.concatenate([state.event_tail[1], ev_ask])
    all_usd = np.concatenate([state.event_tail[2], ev_usd])
    shared = pd.DataFrame({"ts_ms": grid, "implied_mark": implied, "sigma_1s": sigma})
    for h in horizons:
        hh = f"{int(h)}s"
        shared[f"real_bid_{hh}"], shared[f"real_ask_{hh}"] = realised_forced_notional(all_ts, all_ask, all_usd, grid, h)
        shared[f"persist_bid_{hh}"], shared[f"persist_ask_{hh}"] = realised_forced_notional(all_ts, all_ask, all_usd, grid - h * 1000.0, h)
    shared["onset_bid_ms"] = onsets_on_grid(onset_times(all_ts[all_ask]), grid, args.grid_s)
    shared["onset_ask_ms"] = onsets_on_grid(onset_times(all_ts[~all_ask]), grid, args.grid_s)
    shared["date"] = date
    info["market_liquidation_usd"] = float(ev_usd.sum())

    events = wallet_events(legs)
    first = not state.dates_done
    v1_start = _copy_book(state.v1_book)
    rolled1, state.v1_book, s1 = roll_positions(events, state.v1_book)
    info["v1_roll"] = s1.to_dict()
    snap = read_snapshot(args.hydro_dir, coin, date)
    info["snapshot_ts_ms"] = int(snap["snapshot_ts_ms"].iloc[0]) if snap is not None else None
    rows2 = roll_v2(state, coin, events, snap, info)
    deltas = np.sort(np.concatenate(state.sample)) if state.sample else np.zeros(0)
    kappa = None
    if state.impact_x and not args.no_cascade:
        k_fit = impact_slope(np.concatenate(state.impact_x), np.concatenate(state.impact_y))
        kappa = max(k_fit, 0.0) if k_fit is not None else None
    # (book rows, variants on them, first grid time): the prior needs an earlier date first
    plans: list[tuple[BookRows, tuple[str, ...], float]] = []
    if not first and deltas.size:
        plans.append((BookRows(v1_start, {}, {}, _rows(rolled1)), ("v1",), -np.inf))
        if rows2 is not None:
            reset = rows2.rows["ts"][rows2.rows["kind"] == RESET]
            start_ms = float(reset[0]) if not rows2.start and reset.size else -np.inf  # first snapshot: from it on
            plans.append((rows2, ("v2a", "v2"), start_ms))
    frames: dict[str, pd.DataFrame] = {}
    fields = forecast_columns(horizons)
    for rows, variants, start_ms in plans:
        gb = GridBook(rows)
        use = grid > start_ms
        scales: dict[str, dict[float, float]] = {}
        for v in variants:
            rs, fs = state.realised_sum.setdefault(v, {}), state.forecast_sum.setdefault(v, {})
            scales[v] = {h: rs[h] / fs[h] for h in horizons if fs.get(h, 0.0) > 0.0}
        tables = {v: np.zeros((grid.size, len(fields))) for v in variants}
        extras = {v: np.zeros((grid.size, 4)) for v in variants}
        for g in np.flatnonzero(use).tolist():
            gb.advance_to(float(grid[g]), float(implied[g]))
            for v in variants:
                book, total, exact = gb.book(float(mid_before[g]), LIQ_KEY[v])
                f = forecast_forced_flow(
                    book,
                    float(implied[g]),
                    float(sigma[g]) if np.isfinite(sigma[g]) else 0.0,
                    deltas,
                    horizons,
                    scales[v] or None,
                    binary_usd=args.binary_usd,
                    impact_bps_per_musd=kappa,
                )
                tables[v][g] = [f[c] for c in fields]
                size = book.size
                extras[v][g] = float(size[size > 0].sum() * mid_before[g]), float(-size[size < 0].sum() * mid_before[g]), total, exact
        for v in variants:
            frame = shared[use].reset_index(drop=True).copy()
            frame[["oi_long_usd", "oi_short_usd", "book_usd", "exact_share"]] = extras[v][use]
            frame[fields] = tables[v][use]
            frame["hazard_scaled"] = bool(scales[v])
            frame["impact_bps_per_musd"] = kappa if kappa is not None else np.nan
            frames[v] = frame
            rs, fs = state.realised_sum[v], state.forecast_sum[v]
            for h in horizons:
                hh = f"{int(h)}s"
                rs[h] = rs.get(h, 0.0) + float(frame[f"real_bid_{hh}"].sum() + frame[f"real_ask_{hh}"].sum())
                fs[h] = fs.get(h, 0.0) + float(frame[f"Fraw_bid_{hh}"].sum() + frame[f"Fraw_ask_{hh}"].sum())
            info[v] = {
                "expired_usd": gb.expired_usd.get(LIQ_KEY[v] or "", 0.0),
                "grid_points": int(use.sum()),
                "hazard_scale": {f"{int(h)}s": x for h, x in scales[v].items()},
                "mean_exact_share": float(frame["exact_share"].mean()),
            }
    info["prior_n"] = int(deltas.size)
    info["impact_bps_per_musd"] = kappa

    # fits and carries for the next date
    in_day = (ev_ts >= day0) & (ev_ts + 1_000.0 <= mid_ts[-1])
    ix, iy = forced_impact_samples(ev_ts[in_day], ev_ask[in_day], ev_usd[in_day], mid_ts, mid)
    state.impact_x.append(ix)
    state.impact_y.append(iy)
    state.sample.append(liquidation_distances(rolled1))
    keep = mid_ts > mid_ts[-1] - TAIL_MS
    state.mid_tail = (mid_ts[keep], mid[keep])
    tail = ev_ts > day0 + DAY_MS - EVENT_TAIL_MS
    state.event_tail = (ev_ts[tail], ev_ask[tail], ev_usd[tail])
    state.dates_done.append(date)
    return frames, info


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    sp = state_path(args.out_dir, coin)
    if args.fresh and sp.exists():
        sp.unlink()
    state = load_state(sp)
    done = 0
    infos = []
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        if date in state.dates_done:
            continue
        if state.dates_done:
            assert date > state.dates_done[-1], f"{date} comes before {state.dates_done[-1]}: dates must run in order (--fresh restarts)"
        if args.max_days and done >= args.max_days:
            break
        if not (args.node_dir / coin / f"{coin}-{date}.parquet").exists():
            logger.info(f"{coin} {date}: no node fills, skipped")
            continue
        frames, info = forecast_day(args, state, date)
        for variant, frame in frames.items():
            out = grid_path(args.out_dir, coin, date, variant)
            out.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(out, index=False)
        save_state(sp, state)
        info["elapsed_s"] = round(time.perf_counter() - t0, 1)
        logger.info(json.dumps(info, default=str))
        infos.append(info)
        done += 1
    return infos


def _scored(args: argparse.Namespace, coin: str, variant: str) -> pd.DataFrame:
    paths = [grid_path(args.out_dir, coin, d, variant) for d in parse_date_spec(args.dates)]
    frames = [f for f in (pd.read_parquet(p) for p in paths if p.exists()) if bool(f["hazard_scaled"].any())]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def paired(v1: pd.DataFrame, v2: pd.DataFrame, horizons: list[float], grid_s: float, binary_usd: float, seed: int = 0) -> dict[str, Any]:
    """v2 against v1 on the grid times both scored, the first common date only calibrating:
    calibrated and raw Brier on the binary target, and calibrated pinball (0.5, 0.9)."""
    common = sorted(set(v1["date"]) & set(v2["date"]))
    key = ["date", "ts_ms"]
    both = v1[v1["date"].isin(common)].merge(v2[v2["date"].isin(common)][key], on=key)[key]
    a = v1.merge(both, on=key).sort_values(key, ignore_index=True)
    b = v2.merge(both, on=key).sort_values(key, ignore_index=True)
    la, lb = long_frame(a, horizons, grid_s), long_frame(b, horizons, grid_s)
    scored = la["date"].to_numpy() != common[0]
    days = la["date"].to_numpy()[scored]
    fast_cut = float(np.quantile(la["sig_volatility"], 0.95))
    fast = la["sig_volatility"].to_numpy()[scored] >= fast_cut
    regimes = {"fast": fast, "quiet": ~fast}
    out: dict[str, Any] = {"common_dates": common, "scored_days": len(common) - 1, "rows": int(scored.sum())}
    for h in horizons:
        hh = f"{int(h)}s"
        ycol, evcol = f"y_{hh}", f"ev_{hh}"
        for lf in (la, lb):
            lf[evcol] = (lf[ycol].to_numpy(dtype=np.float64) >= binary_usd).astype(np.float64)
        y = la[ycol].to_numpy(dtype=np.float64)[scored]
        ev = la[evcol].to_numpy()[scored]

        def rate(v: FloatArray) -> float:
            return float(v.mean())

        entry: dict[str, Any] = {"events": int(ev.sum())}
        pa = _calibrate(la, f"sig_model_{hh}", evcol, rate)[scored]
        pb = _calibrate(lb, f"sig_model_{hh}", evcol, rate)[scored]
        entry["brier_calibrated"] = compare_rungs(days, ev, pa, pb, loss="brier", regimes=regimes, seed=seed)
        ra = np.clip(la[f"p_model_{hh}"].to_numpy(dtype=np.float64)[scored], 0.0, 1.0)
        rb = np.clip(lb[f"p_model_{hh}"].to_numpy(dtype=np.float64)[scored], 0.0, 1.0)
        entry["brier_raw"] = compare_rungs(days, ev, ra, rb, loss="brier", regimes=regimes, seed=seed)
        for tau in (0.5, 0.9):

            def quantile(v: FloatArray, tau: float = tau) -> float:
                return float(np.quantile(v, tau))

            qa = _calibrate(la, f"sig_model_{hh}", ycol, quantile)[scored]
            qb = _calibrate(lb, f"sig_model_{hh}", ycol, quantile)[scored]
            entry[f"pinball_q{round(tau * 100)}"] = compare_rungs(days, y, qa, qb, loss="pinball", tau=tau, regimes=regimes, seed=seed)
        out[hh] = entry
    return out


def report(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    horizons = [float(h) for h in args.horizons.split(",")]
    parts = set(args.parts.split(","))
    frames = {v: _scored(args, coin, v) for v in VARIANTS}
    res: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8")) if args.report.exists() else {}
    res.update({"coin": coin, "dates": args.dates, "grid_s": args.grid_s, "binary_usd": args.binary_usd})
    for v, f in frames.items():
        if ("variants" in parts or v in parts) and len(f) and f["date"].nunique() >= 2:
            res[v] = evaluate_forecasts(f, horizons, grid_s=args.grid_s, binary_usd=args.binary_usd)
            res[v]["mean_exact_share"] = float(f["exact_share"].mean())
            res[v]["dates_scored"] = sorted(f["date"].unique().tolist())[1:]
    if "v1_on_v2" in parts and len(frames["v1"]) and len(frames["v2"]):
        # v1 on v2's days, so the two tables cover the same days
        same = frames["v1"][frames["v1"]["date"].isin(set(frames["v2"]["date"]))]
        if same["date"].nunique() >= 2:
            res["v1_on_v2_dates"] = evaluate_forecasts(same, horizons, grid_s=args.grid_s, binary_usd=args.binary_usd)
    if "pairs" in parts:
        for chal, base in PAIRS:
            a, b = frames[base], frames[chal]
            if len(a) and len(b) and len(set(a["date"]) & set(b["date"])) >= 3:
                res[f"{chal}_vs_{base}"] = paired(a, b, horizons, args.grid_s, args.binary_usd)
    state = load_state(state_path(args.out_dir, coin))
    res["hazard_fit"] = {
        v: {f"{int(h)}s": state.realised_sum.get(v, {}).get(h, 0.0) / fs for h, fs in state.forecast_sum.get(v, {}).items() if fs > 0}
        for v in VARIANTS
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(res, indent=1, default=float) + "\n", encoding="utf-8")
    return res


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.report is not None:
        res = report(args)
        for chal, base in PAIRS:
            cmp = res.get(f"{chal}_vs_{base}", {}).get("60s", {})
            for name in ("brier_calibrated", "brier_raw", "pinball_q90"):
                if name not in cmp:
                    continue
                a = cmp[name]["all"]
                print(
                    f"{chal} vs {base} 60s {name}: {a.get('mean_daily_improvement')} ({a.get('days_improved')}/{a.get('days')} days), dm p {a.get('diebold_mariano', {}).get('p_value')}"
                )
        return 0
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
