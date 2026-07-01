"""Seed the current replay engine from Hyperliquid public API samples.

The long-term design is a native Hyperliquid replay adapter. Until that
adapter exists, the simulator still consumes the legacy replay-lake shape:

``klines/<symbol>/1m/<symbol>-klines-1m-YYYY-MM-DD.parquet``
``bookDepth/<symbol>/<symbol>-bookDepth-YYYY-MM-DD.parquet``

This module is the explicit bridge between those worlds. It keeps the
translation small, typed, and easy to delete once the native adapter lands.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.ingest.hyperliquid_api import Candle
from marketimmune.ingest.hyperliquid_archive import BookSnapshot, L2Level


@dataclass(frozen=True, slots=True)
class ReplayLakeWrite:
    """One replay-lake parquet write."""

    path: Path
    rows: int


@dataclass(frozen=True, slots=True)
class ReplayLakeSeed:
    """Summary of one Hyperliquid public API replay seed."""

    coin: str
    symbol: str
    date: str
    selected_candles: tuple[Candle, ...]
    dropped_candles: int
    kline_write: ReplayLakeWrite
    depth_write: ReplayLakeWrite


def write_replay_lake_seed(
    *,
    lake_root: Path,
    symbol: str,
    candles: Sequence[Candle],
    book: BookSnapshot,
    max_candles: int | None = None,
) -> ReplayLakeSeed:
    """Write Hyperliquid candles/book into the current replay-lake contract."""
    selected, dropped = select_replay_candles(candles, max_candles=max_candles)
    date = _date_iso(selected[-1].open_ts_ms)
    coin = selected[-1].coin
    if book.coin != coin:
        raise ValueError(f"book coin {book.coin!r} does not match candle coin {coin!r}")

    root = Path(lake_root)
    kline_write = _write_kline_rows(root, symbol, date, selected)
    depth_write = _write_depth_rows(root, symbol, date, book)
    return ReplayLakeSeed(
        coin=coin,
        symbol=symbol,
        date=date,
        selected_candles=tuple(selected),
        dropped_candles=dropped,
        kline_write=kline_write,
        depth_write=depth_write,
    )


def select_replay_candles(
    candles: Sequence[Candle],
    *,
    max_candles: int | None = None,
) -> tuple[tuple[Candle, ...], int]:
    """Pick a single UTC day of 1m candles for replay alignment."""
    if not candles:
        raise ValueError("cannot seed replay lake without candles")
    if max_candles is not None and max_candles < 1:
        raise ValueError("max_candles must be >= 1")

    ordered = tuple(sorted(candles, key=lambda candle: candle.open_ts_ms))
    bad_intervals = {candle.interval for candle in ordered if candle.interval != "1m"}
    if bad_intervals:
        raise ValueError("replay lake seed currently supports only 1m candles")

    target_date = _date_iso(ordered[-1].open_ts_ms)
    same_day = tuple(
        candle for candle in ordered if _date_iso(candle.open_ts_ms) == target_date
    )
    selected = same_day[-max_candles:] if max_candles is not None else same_day
    return selected, len(ordered) - len(selected)


def _write_kline_rows(
    lake_root: Path,
    symbol: str,
    date: str,
    candles: Sequence[Candle],
) -> ReplayLakeWrite:
    rows = [_kline_row(symbol, candle) for candle in candles]
    path = (
        lake_root
        / "klines"
        / symbol
        / "1m"
        / f"{symbol}-klines-1m-{date}.parquet"
    )
    _write_records(path, rows)
    return ReplayLakeWrite(path=path, rows=len(rows))


def _write_depth_rows(
    lake_root: Path,
    symbol: str,
    date: str,
    book: BookSnapshot,
) -> ReplayLakeWrite:
    rows = _depth_rows(book)
    path = lake_root / "bookDepth" / symbol / f"{symbol}-bookDepth-{date}.parquet"
    _write_records(path, rows)
    return ReplayLakeWrite(path=path, rows=len(rows))


def _kline_row(symbol: str, candle: Candle) -> dict[str, Any]:
    return {
        "event_id": f"hl:{candle.coin}:{candle.open_ts_ms}",
        "timestamp": _timestamp_iso(candle.open_ts_ms),
        "symbol": symbol,
        "open_price": candle.open,
        "high_price": candle.high,
        "low_price": candle.low,
        "close_price": candle.close,
        "volume": candle.volume,
        "trade_count": candle.trade_count,
    }


def _depth_rows(book: BookSnapshot) -> list[dict[str, Any]]:
    features = book.features()
    mid = features["mid"]
    timestamp = _timestamp_iso(book.ts_ms)
    return [
        _depth_row(timestamp, mid, level, side=-1.0)
        for level in book.bids
    ] + [
        _depth_row(timestamp, mid, level, side=1.0)
        for level in book.asks
    ]


def _depth_row(
    timestamp: str,
    mid: float,
    level: L2Level,
    *,
    side: float,
) -> dict[str, Any]:
    percentage = abs((level.px / mid - 1.0) * 100.0)
    return {
        "timestamp": timestamp,
        "percentage": side * percentage,
        "depth": level.sz,
        "notional": level.px * level.sz,
    }


def _write_records(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if not records:
        raise ValueError("cannot write an empty replay-lake artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([dict(record) for record in records])
    pq.write_table(table, path, compression="zstd")  # type: ignore[no-untyped-call]


def _timestamp_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, UTC).strftime("%Y-%m-%d")
