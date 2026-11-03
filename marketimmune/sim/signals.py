"""Quote-time markout models for the simulator's S2 and S3.

The ladder's quantile models score a fill with columns that exist only once a taker has hit the
quote: the trade's size (``sz``) and the taker's wallet score (``taker_tox_*``, ``taker_log_n``). A
quoting rule cannot use them. The models here are the ladder's policy rungs (S2: ``l2_book``, S3:
``l3_book``) without those columns, trained as the ladder trains: LightGBM quantiles at 0.1, 0.5
and 0.9 with the pre-registered settings, on the same Gold rows and label (``markout_bps_1s``),
in rolling 7-day folds with a 60 s purge and seed 42 plus the fold number. Every rung-L2 column is
a wallet column, so S2 is the ``l1_book`` rung without ``sz``.

Each model predicts, on every Silver L2 row of its test day and for each side, the markout
quantiles of the next fill that side would get. A row's features are the ones Gold gives a fill 1 ms
after the row's block: the book up to and including that block, Binance up to the feed latency
before that time, and the order events and forecast grid strictly before it. ``quote_features`` at
Gold's own fill times reproduces the matrix the models train on; ``check_against_gold`` asserts
that on every day that is scored (train/serve consistency).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

from marketimmune.cli.build_albers_gold import PREV_DAY_SPAN_MS, load_mids
from marketimmune.cli.enrich_albers import EVENT_COLUMNS, _arrays, _read, _tail
from marketimmune.cli.forced_forecast import forced_grid_path
from marketimmune.features.cex_gap import CEX_FEATURE_COLUMNS, DEFAULT_LATENCY_MS, PriceSeries, cex_gap_features
from marketimmune.features.forced_flow_features import FORECAST_FEATURE_COLUMNS, GRID_INPUTS, forecast_features
from marketimmune.features.order_events import FORCED_FEATURE_COLUMNS, RACE_FEATURE_COLUMNS, order_event_features
from marketimmune.features.training_rows import FEATURE_SETS, HYPERLIQUID_OFI_COLUMNS, ofi_columns
from marketimmune.features.wallet_toxicity import WALLET_FEATURE_COLUMNS
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.models.cross_validation import FoldArrays, temporal_fold_arrays
from marketimmune.models.quantile_ladder import DEFAULT_TAUS, PREREGISTERED, LgbParams, quantile_column
from marketimmune.sim.data import binance_days
from marketimmune.utils import DAY_MS, shift_date

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

FILL_TIME_COLUMNS = ("sz", *WALLET_FEATURE_COLUMNS)
QUOTE_RUNGS = {"s2": "l2_book", "s3": "l3_book"}
HORIZON = "1s"
TRAIN_DAYS = 7
PURGE_MS = 60_000.0
SEED = 42
SIDES = {"bid": 1.0, "ask": -1.0}  # Gold's maker_side: +1 when the maker's bid is hit
QUOTE_DELAY_MS = 1.0  # a row's features are those of a fill this long after its block
CHUNK_ROWS = 1 << 18
_BOOK = ("bid_px", "bid_sz", "ask_px", "ask_sz")
L2_SOURCE_COLUMNS = ("ts_ms", "ts_ns", *_BOOK, "mid", "spread_bps", "microprice", "top_imbalance")
GOLD_SOURCE_COLUMNS = ("l2_mid", "l2_microprice")  # Gold keeps the raw microprice; training derives the offset


def quote_columns(name: str) -> tuple[str, ...]:
    """The rung's feature columns that are known before a fill."""
    return tuple(c for c in FEATURE_SETS[QUOTE_RUNGS[name]] if c not in FILL_TIME_COLUMNS)


def quote_signals_path(root: Path, coin: str, date: str) -> Path:
    symbol = coin.upper()
    return root / symbol / f"{symbol}-{date}.parquet"


def signal_column(name: str, tau: float, side: str) -> str:
    """``("s2", 0.1, "bid") -> "s2_q10_bid"``."""
    return f"{name}_{quantile_column(tau)}_{side}"


def l2_row_features(ts_ms: FloatArray, book: Mapping[str, FloatArray]) -> dict[str, FloatArray]:
    """Gold's L2 columns for a fill whose last earlier book row is each row: the row's spread,
    microprice offset and top imbalance, and the OFI windows ending at it (``ofi_columns``, as
    Gold's join; NaN OFI as 0, as the trainers fill it)."""
    mid = book["mid"]
    out = {
        "l2_spread_bps": book["spread_bps"],
        "l2_microprice_offset_bps": (book["microprice"] - mid) / mid * 10_000.0,
        "l2_top_imbalance": book["top_imbalance"],
    }
    for name, values in ofi_columns(ts_ms, {c: book[c] for c in _BOOK}).items():
        out[f"l2_{name}"] = np.where(np.isnan(values), 0.0, values)
    return out


@dataclass(frozen=True, slots=True)
class DayInputs:
    """Everything one day's quote-time features read, loaded the way Gold was built."""

    l2_ts_ms: FloatArray  # Silver L2 rows, in time order
    l2_ts_ns: npt.NDArray[np.int64]
    l2: dict[str, FloatArray]  # Gold's L2 columns per row
    mid_ts_ms: FloatArray  # mids for the CEX gap, with the previous day's tail
    mid: FloatArray
    cex: PriceSeries
    events: dict[str, npt.NDArray[Any]]  # order events, with the previous day's tail
    grid: dict[str, npt.NDArray[Any]]  # forced-flow forecast grid, previous day included

    def quote_rows(self) -> tuple[npt.NDArray[np.int64], FloatArray]:
        """The simulator's L2 rows (``sim.data.load_day``: the last row per block time) and the
        time their features are read at."""
        last = np.append(self.l2_ts_ns[1:] != self.l2_ts_ns[:-1], True)
        return self.l2_ts_ns[last], self.l2_ts_ms[last] + QUOTE_DELAY_MS


def load_day_inputs(lake_root: Path, binance_dir: Path, coin: str, date: str) -> DayInputs:
    """One day's book, mids, Binance trades, order events and forecast grid.

    Mirrors Gold: the book columns come from the day's Silver L2 only (``rebuild_training_rows``),
    the mids carry the previous day's last 30 minutes (``build_albers_gold``), the order events
    the previous day's last 5 minutes and the grid the whole previous day (``enrich_albers``).
    """
    coin = coin.upper()
    layout = HyperliquidLakeLayout(lake_root)
    table = pq.read_table(layout.silver_l2_book_path(coin, date), columns=list(L2_SOURCE_COLUMNS))
    ts_ms = table["ts_ms"].to_numpy().astype(np.float64)
    assert np.all(ts_ms[1:] >= ts_ms[:-1]), f"{coin} {date}: Silver L2 out of time order"
    book = {c: table[c].to_numpy(zero_copy_only=False).astype(np.float64) for c in L2_SOURCE_COLUMNS[2:]}
    mid_ts, mid = load_mids(layout, coin, date, prev_tail_ms=PREV_DAY_SPAN_MS)
    prev = shift_date(date, -1)
    events = _arrays(
        [
            _tail(_read(layout.silver_order_events_path(coin, prev), EVENT_COLUMNS)),
            _read(layout.silver_order_events_path(coin, date), EVENT_COLUMNS),
        ],
        EVENT_COLUMNS,
    )
    grid = _arrays([_read(forced_grid_path(lake_root, coin, d), GRID_INPUTS, scaled_only=True) for d in (prev, date)], GRID_INPUTS)
    return DayInputs(
        l2_ts_ms=ts_ms,
        l2_ts_ns=table["ts_ns"].to_numpy(),
        l2=l2_row_features(ts_ms, book),
        mid_ts_ms=mid_ts,
        mid=mid,
        cex=binance_days(binance_dir, coin, date),
        events=events,
        grid=grid,
    )


def quote_features(
    inputs: DayInputs,
    t_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    columns: Sequence[str],
    *,
    cex_latency_ms: float = DEFAULT_LATENCY_MS,
) -> FloatArray:
    """Gold's feature matrix (one row per time, ``columns`` in order) for fills at ``t_ms`` on
    ``maker_side``; NaN where Gold has no value (no earlier book row, no Binance price, no grid)."""
    t = np.asarray(t_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64) * np.ones(t.size)
    wanted = set(columns)
    j = np.searchsorted(inputs.l2_ts_ms, t, side="left") - 1  # strictly before, as Gold's join
    feats: dict[str, FloatArray] = {"maker_side": side}
    for name, values in inputs.l2.items():
        if name in wanted:
            feats[name] = np.where(j >= 0, values[np.maximum(j, 0)], np.nan)
    if wanted & set(CEX_FEATURE_COLUMNS):
        feats |= cex_gap_features(t, side, inputs.mid_ts_ms, inputs.mid, inputs.cex, latency_ms=cex_latency_ms)
    if wanted & {*RACE_FEATURE_COLUMNS, *FORCED_FEATURE_COLUMNS}:
        feats |= order_event_features(t, side, inputs.events)
    if wanted & set(FORECAST_FEATURE_COLUMNS):
        feats |= forecast_features(t, side, inputs.grid)
    return np.column_stack([feats[c] for c in columns])


@dataclass(frozen=True, slots=True)
class GoldDay:
    """One day's Gold rows as the trainers see them (``_train_data.prepare_training_frame``):
    the microprice offset derived, NaN OFI as 0, rows in time order."""

    ts_ms: FloatArray
    maker_side: FloatArray
    y: FloatArray  # markout_bps_<horizon>
    labelled: BoolArray  # toxic_<horizon> present
    features: dict[str, FloatArray]


def load_gold_day(lake_root: Path, coin: str, date: str, columns: Sequence[str], *, horizon: str = HORIZON) -> GoldDay:
    path = HyperliquidLakeLayout(lake_root).gold_training_path(coin.upper(), date)
    derived = {"l2_microprice_offset_bps"}
    names = dict.fromkeys(
        (
            "ts_ms",
            "maker_side",
            f"markout_bps_{horizon}",
            f"toxic_{horizon}",
            *GOLD_SOURCE_COLUMNS,
            *(c for c in columns if c not in derived),
        )
    )
    table = pq.read_table(path, columns=list(names))
    order = np.argsort(table["ts_ms"].to_numpy(), kind="stable")
    col = {n: table[n].to_numpy(zero_copy_only=False).astype(np.float64)[order] for n in names if n != f"toxic_{horizon}"}
    mid = col["l2_mid"]
    feats = {c: col[c] for c in columns if c not in derived}
    feats["l2_microprice_offset_bps"] = (col["l2_microprice"] - mid) / mid * 10_000.0
    for c in HYPERLIQUID_OFI_COLUMNS:
        feats[c] = np.where(np.isnan(feats[c]), 0.0, feats[c])
    return GoldDay(
        ts_ms=col["ts_ms"],
        maker_side=col["maker_side"],
        y=col[f"markout_bps_{horizon}"],
        labelled=table[f"toxic_{horizon}"].is_valid().to_numpy(zero_copy_only=False)[order],
        features={c: feats[c] for c in columns},
    )


def check_against_gold(
    inputs: DayInputs, gold: GoldDay, columns: Sequence[str], *, cex_latency_ms: float = DEFAULT_LATENCY_MS
) -> dict[str, Any]:
    """Quote-time features at Gold's fill times against Gold's own columns. Any difference beyond
    rounding means the simulator would serve the models something they were not trained on."""
    served = quote_features(inputs, gold.ts_ms, gold.maker_side, columns, cex_latency_ms=cex_latency_ms)
    mismatched: dict[str, int] = {}
    worst = 0.0
    for k, c in enumerate(columns):
        a, b = served[:, k], gold.features[c]
        both_nan = np.isnan(a) & np.isnan(b)
        diff = np.where(both_nan, 0.0, np.abs(a - b))
        diff = np.where(np.isnan(diff), np.inf, diff)  # NaN on one side only
        bad = diff > 1e-9 * np.maximum(1.0, np.abs(np.nan_to_num(b)))
        worst = max(worst, float(diff.max(initial=0.0)))
        if bad.any():
            mismatched[c] = int(bad.sum())
    return {"passed": not mismatched, "rows": int(gold.ts_ms.size), "mismatched": mismatched, "max_abs_diff": worst}


def fit_quantiles(
    x: npt.NDArray[np.float32], y: FloatArray, *, seed: int, params: LgbParams = PREREGISTERED, taus: Sequence[float] = DEFAULT_TAUS
) -> list[lgb.Booster]:
    """One booster per tau on one binned dataset, as ``quantile_ladder.train_quantile_oof``."""
    train = lgb.Dataset(x, label=y)
    return [lgb.train(params.booster_params(tau, seed), train, num_boost_round=params.n_estimators) for tau in taus]


def predict_quantiles(boosters: Sequence[lgb.Booster], x: npt.NDArray[np.float32]) -> FloatArray:
    """``(rows, taus)`` predictions sorted per row (no crossing, as the ladder); NaN on rows with a
    missing feature, which the trainers drop and a quoting rule must not score."""
    out = np.full((x.shape[0], len(boosters)), np.nan)
    ok = np.isfinite(x).all(axis=1)
    if ok.any():
        threads = os.cpu_count() or 1
        raw = np.column_stack([b.predict(x[ok], num_threads=threads) for b in boosters])
        out[ok] = np.sort(raw, axis=1)
    return out


def utc_date(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000.0, UTC).strftime("%Y%m%d")


def day_folds(ts_ms: FloatArray) -> dict[str, tuple[int, FoldArrays]]:
    """Test date -> (fold number, fold) for the ladder's rolling folds (numbered as
    ``train_quantile_oof`` numbers them, so the seeds match its convention)."""
    days = np.floor(ts_ms / DAY_MS)
    if ts_ms.size == 0 or days.max() - days.min() < TRAIN_DAYS:
        return {}  # e.g. S3 before the forecast grid has 7 days behind it
    folds = temporal_fold_arrays(ts_ms, purge_ms=PURGE_MS, train_days=TRAIN_DAYS)
    return {
        utc_date(fold.test_start_ms): (fold_id, fold)
        for fold_id, fold in enumerate(folds, start=1)
        if fold.train.size >= 2 and fold.test.size > 0
    }


def predict_rows(
    inputs: DayInputs,
    models: Mapping[str, Sequence[lgb.Booster]],
    columns: Mapping[str, Sequence[str]],
    *,
    taus: Sequence[float] = DEFAULT_TAUS,
    cex_latency_ms: float = DEFAULT_LATENCY_MS,
) -> dict[str, npt.NDArray[Any]]:
    """Every model's sorted quantiles on every simulator row, for a bid and for an ask:
    ``ts_ns`` plus one ``signal_column`` per (model, tau, side)."""
    ts_ns, t_ms = inputs.quote_rows()
    union = list(dict.fromkeys(c for name in models for c in columns[name]))
    pick = {name: [union.index(c) for c in columns[name]] for name in models}
    out: dict[str, npt.NDArray[Any]] = {"ts_ns": ts_ns}
    for side, sign in SIDES.items():
        preds = {name: np.full((t_ms.size, len(taus)), np.nan) for name in models}
        for lo in range(0, t_ms.size, CHUNK_ROWS):
            hi = min(lo + CHUNK_ROWS, t_ms.size)
            x = quote_features(inputs, t_ms[lo:hi], sign, union, cex_latency_ms=cex_latency_ms).astype(np.float32)
            for name, boosters in models.items():
                preds[name][lo:hi] = predict_quantiles(boosters, x[:, pick[name]])
        for name in models:
            for k, tau in enumerate(taus):
                out[signal_column(name, tau, side)] = preds[name][:, k].astype(np.float32)
    return out
