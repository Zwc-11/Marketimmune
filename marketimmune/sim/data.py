"""One day of inputs for the quote simulator: the rebuilt book and the signals on its rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow.parquet as pq

from marketimmune.features.cex_gap import PriceSeries, cex_gap_features, read_binance_aggtrades_zip
from marketimmune.lake.tables import L2_DEPTH, HyperliquidLakeLayout
from marketimmune.sim.attribution import PX_SCALE
from marketimmune.sim.engine import DayBook, FloatArray, IntArray
from marketimmune.utils import shift_date


def load_day(lake_root: Path, coin: str, date: str) -> DayBook:
    """Silver L2 rows and near-touch L4 events (``build_albers_silver --mbo``) of one date."""
    layout = HyperliquidLakeLayout(lake_root)
    levels = [f"{side}_{what}_{i}" for side in ("bid", "ask") for what in ("px", "sz") for i in range(1, L2_DEPTH + 1)]
    l2 = pq.read_table(layout.silver_l2_book_path(coin, date), columns=["ts_ns", *levels])

    def depth(side: str, what: str) -> FloatArray:
        cols = [l2[f"{side}_{what}_{i}"].to_numpy(zero_copy_only=False).astype(np.float64) for i in range(1, L2_DEPTH + 1)]
        return np.nan_to_num(np.column_stack(cols), nan=0.0)

    def ticks(side: str) -> IntArray:
        return np.rint(depth(side, "px") * PX_SCALE).astype(np.int64)

    ts = l2["ts_ns"].to_numpy()
    # NOTE: a block whose statuses straddle two hourly files (2025-12-01 06:59:59.826) gets a row
    # from each hour; the later one is the book after the whole block.
    last = np.append(ts[1:] != ts[:-1], True)
    mbo = pq.ParquetFile(layout.silver_mbo_path(coin, date))

    def events(column: str) -> npt.NDArray[Any]:
        # One column at a time: reading the whole table of a 30M-event ETH day peaked above 3.6 GB.
        values: npt.NDArray[Any] = mbo.read(columns=[column])[column].to_numpy(zero_copy_only=False)
        return values

    return DayBook(
        l2_ts=ts[last],
        bid_px=ticks("bid")[last],
        bid_sz=depth("bid", "sz")[last],
        ask_px=ticks("ask")[last],
        ask_sz=depth("ask", "sz")[last],
        ev_ts=events("ts_ns"),
        ev_kind=events("kind"),
        ev_ask=events("is_ask"),
        ev_px=events("px_ticks"),
        ev_sz=events("sz"),
        ev_added=events("added_ns"),
        ev_alo=events("alo"),
    )


def binance_days(binance_dir: Path, coin: str, date: str) -> PriceSeries:
    """Binance aggTrades of ``date`` and, when present, the day before (as Gold's L1 columns)."""
    symbol = f"{coin.upper()}USDT"
    zips = [binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip" for d in (shift_date(date, -1), date)]
    assert zips[1].exists(), f"missing {zips[1]}"
    return PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])


def cex_gaps(book: DayBook, binance_dir: Path, coin: str, date: str, *, latency_ms: float) -> tuple[FloatArray, FloatArray]:
    """``cex_gap_maker_bps`` for a bid and for an ask on every L2 row, known after that row's
    block: Hyperliquid mids up to the row, Binance up to ``latency_ms`` before it."""
    cex = binance_days(binance_dir, coin, date)
    t_ms = book.l2_ts / 1e6
    mid = (book.bid_px[:, 0] + book.ask_px[:, 0]) / 2.0 / PX_SCALE
    gap = cex_gap_features(t_ms + 1.0, np.ones(t_ms.size), t_ms, mid, cex, latency_ms=latency_ms)["cex_gap_bps"]
    return gap, -gap
