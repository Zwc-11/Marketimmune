"""Tests for seeding the current replay lake from Hyperliquid public samples."""

from __future__ import annotations

from pathlib import Path

import pytest

from marketimmune.ingest.hyperliquid_api import Candle
from marketimmune.ingest.hyperliquid_archive import BookSnapshot, L2Level
from marketimmune.ingest.hyperliquid_replay_seed import (
    _write_records,
    select_replay_candles,
    write_replay_lake_seed,
)
from marketimmune.simulator.data_loader import DepthRepository, KlineRepository, _load_parquet


def _candle(open_ts_ms: int, close: float, *, interval: str = "1m") -> Candle:
    return Candle(
        coin="BTC",
        interval=interval,
        open_ts_ms=open_ts_ms,
        close_ts_ms=open_ts_ms + 59_999,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=10.0,
        trade_count=7,
    )


def _book(ts_ms: int = 1_767_225_660_000) -> BookSnapshot:
    return BookSnapshot(
        ts_ms=ts_ms,
        coin="BTC",
        bids=(
            L2Level(px=99.0, sz=2.0, n=1),
            L2Level(px=98.0, sz=3.0, n=1),
        ),
        asks=(
            L2Level(px=101.0, sz=4.0, n=1),
            L2Level(px=102.0, sz=5.0, n=1),
        ),
    )


def test_select_replay_candles_keeps_latest_single_utc_day() -> None:
    candles = [
        _candle(1_767_225_540_000, 100.0),  # 2025-12-31 23:59 UTC
        _candle(1_767_225_600_000, 101.0),  # 2026-01-01 00:00 UTC
        _candle(1_767_225_660_000, 102.0),  # 2026-01-01 00:01 UTC
    ]

    selected, dropped = select_replay_candles(candles, max_candles=1)

    assert [candle.close for candle in selected] == [102.0]
    assert dropped == 2


def test_select_replay_candles_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="without candles"):
        select_replay_candles([])


def test_select_replay_candles_rejects_invalid_max_candles() -> None:
    with pytest.raises(ValueError, match="max_candles"):
        select_replay_candles([_candle(1_767_225_600_000, 101.0)], max_candles=0)


def test_write_replay_lake_seed_matches_replay_repositories(tmp_path: Path) -> None:
    candles = [
        _candle(1_767_225_600_000, 101.0),
        _candle(1_767_225_660_000, 102.0),
    ]

    seed = write_replay_lake_seed(
        lake_root=tmp_path,
        symbol="BTCUSDT",
        candles=candles,
        book=_book(),
    )
    _load_parquet.cache_clear()

    klines = KlineRepository(tmp_path).load("BTCUSDT", "2026-01-01", 10)
    depths = DepthRepository(tmp_path).load("BTCUSDT", "2026-01-01")

    assert seed.date == "2026-01-01"
    assert seed.kline_write.rows == 2
    assert seed.depth_write.rows == 4
    assert klines[0].event_id == "hl:BTC:1767225600000"
    assert klines[-1].close == pytest.approx(102.0)
    assert len(depths) == 1
    assert [level.percentage for level in depths[0].levels] == pytest.approx(
        [-2.0, -1.0, 1.0, 2.0]
    )


def test_write_replay_lake_seed_rejects_wrong_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only 1m candles"):
        write_replay_lake_seed(
            lake_root=tmp_path,
            symbol="BTCUSDT",
            candles=[_candle(1_767_225_600_000, 101.0, interval="5m")],
            book=_book(),
        )


def test_write_replay_lake_seed_rejects_coin_mismatch(tmp_path: Path) -> None:
    book = BookSnapshot(
        ts_ms=1_767_225_660_000,
        coin="ETH",
        bids=(L2Level(px=99.0, sz=2.0, n=1),),
        asks=(L2Level(px=101.0, sz=4.0, n=1),),
    )

    with pytest.raises(ValueError, match="does not match"):
        write_replay_lake_seed(
            lake_root=tmp_path,
            symbol="BTCUSDT",
            candles=[_candle(1_767_225_600_000, 101.0)],
            book=book,
        )


def test_write_replay_lake_seed_rejects_empty_book_side(tmp_path: Path) -> None:
    book = BookSnapshot(
        ts_ms=1_767_225_660_000,
        coin="BTC",
        bids=(),
        asks=(),
    )

    with pytest.raises(ValueError, match="empty side"):
        write_replay_lake_seed(
            lake_root=tmp_path,
            symbol="BTCUSDT",
            candles=[_candle(1_767_225_600_000, 101.0)],
            book=book,
        )


def test_write_records_rejects_empty_artifact(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty replay-lake"):
        _write_records(tmp_path / "empty.parquet", [])
