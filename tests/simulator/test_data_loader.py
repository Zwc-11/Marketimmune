"""Tests for marketimmune.simulator.data_loader.

Uses in-memory parquet files (via pyarrow) so no Binance lake is needed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.simulator.data_loader import (
    DepthLevel,
    DepthRepository,
    DepthSnapshot,
    KlineRecord,
    KlineRepository,
    _load_parquet,
)


# ---------------------------------------------------------------------------
# Helpers to write minimal parquet files
# ---------------------------------------------------------------------------


def _write_kline_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "event_id": ["ev1", "ev2", "ev3"],
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
                "2026-01-01T00:02:00Z",
            ],
            "open_price": [100.0, 101.0, 102.0],
            "high_price": [105.0, 106.0, 107.0],
            "low_price": [99.0, 100.0, 101.0],
            "close_price": [101.0, 102.0, 103.0],
            "volume": [1000.0, 2000.0, 3000.0],
            "trade_count": [10, 20, 30],
        }
    )
    pq.write_table(table, path)


def _write_depth_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
            ],
            "percentage": [1.0, -1.0, 1.0],
            "depth": [5.0, 4.0, 6.0],
            "notional": [500.0, 400.0, 600.0],
        }
    )
    pq.write_table(table, path)


# ---------------------------------------------------------------------------
# KlineRepository
# ---------------------------------------------------------------------------


def test_kline_repo_empty_when_dir_missing(tmp_path: Path) -> None:
    repo = KlineRepository(tmp_path)
    result = repo.load("BTCUSDT", "2026-01-01", 10)
    assert result == []


def test_kline_repo_empty_when_no_files(tmp_path: Path) -> None:
    d = tmp_path / "klines" / "BTCUSDT" / "1m"
    d.mkdir(parents=True)
    repo = KlineRepository(tmp_path)
    result = repo.load("BTCUSDT", "2026-01-01", 10)
    assert result == []


def test_kline_repo_load_returns_records(tmp_path: Path) -> None:
    kline_path = (
        tmp_path / "klines" / "BTCUSDT" / "1m" / "BTCUSDT-klines-1m-2026-01-01.parquet"
    )
    _write_kline_file(kline_path)
    # Clear the lru_cache so a previous test's cache doesn't interfere.
    _load_parquet.cache_clear()

    repo = KlineRepository(tmp_path)
    records = repo.load("BTCUSDT", "2026-01-01", 10)
    assert len(records) == 3
    assert all(isinstance(r, KlineRecord) for r in records)
    assert records[0].symbol == "BTCUSDT"
    assert records[0].open == 100.0


def test_kline_repo_respects_limit(tmp_path: Path) -> None:
    kline_path = (
        tmp_path / "klines" / "BTCUSDT" / "1m" / "BTCUSDT-klines-1m-2026-01-01.parquet"
    )
    _write_kline_file(kline_path)
    _load_parquet.cache_clear()

    repo = KlineRepository(tmp_path)
    records = repo.load("BTCUSDT", "2026-01-01", 2)
    assert len(records) == 2


def test_kline_repo_no_date_picks_first_file(tmp_path: Path) -> None:
    kline_path = (
        tmp_path / "klines" / "BTCUSDT" / "1m" / "BTCUSDT-klines-1m-2026-01-01.parquet"
    )
    _write_kline_file(kline_path)
    _load_parquet.cache_clear()

    repo = KlineRepository(tmp_path)
    records = repo.load("BTCUSDT", None, 10)
    assert len(records) == 3


def test_kline_repo_available_dates(tmp_path: Path) -> None:
    kline_dir = tmp_path / "klines" / "BTCUSDT" / "1m"
    kline_dir.mkdir(parents=True)
    # Write two date files
    for date in ["2026-01-01", "2026-01-02"]:
        p = kline_dir / f"BTCUSDT-klines-1m-{date}.parquet"
        _write_kline_file(p)
    _load_parquet.cache_clear()

    repo = KlineRepository(tmp_path)
    dates = repo.available_dates("BTCUSDT")
    assert "2026-01-01" in dates
    assert "2026-01-02" in dates


def test_kline_repo_available_dates_missing_dir(tmp_path: Path) -> None:
    repo = KlineRepository(tmp_path)
    assert repo.available_dates("NONEXISTENT") == []


# ---------------------------------------------------------------------------
# DepthRepository
# ---------------------------------------------------------------------------


def test_depth_repo_empty_when_file_missing(tmp_path: Path) -> None:
    repo = DepthRepository(tmp_path)
    result = repo.load("BTCUSDT", "2026-01-01")
    assert result == []


def test_depth_repo_load_returns_snapshots(tmp_path: Path) -> None:
    depth_path = (
        tmp_path / "bookDepth" / "BTCUSDT" / "BTCUSDT-bookDepth-2026-01-01.parquet"
    )
    _write_depth_file(depth_path)
    _load_parquet.cache_clear()

    repo = DepthRepository(tmp_path)
    snaps = repo.load("BTCUSDT", "2026-01-01")
    assert len(snaps) == 2  # 2 unique timestamps
    assert all(isinstance(s, DepthSnapshot) for s in snaps)
    # Sorted by timestamp
    assert snaps[0].timestamp < snaps[1].timestamp


def test_depth_repo_levels_are_sorted_by_percentage(tmp_path: Path) -> None:
    depth_path = (
        tmp_path / "bookDepth" / "BTCUSDT" / "BTCUSDT-bookDepth-2026-01-01.parquet"
    )
    _write_depth_file(depth_path)
    _load_parquet.cache_clear()

    repo = DepthRepository(tmp_path)
    snaps = repo.load("BTCUSDT", "2026-01-01")
    first_snap = snaps[0]
    percentages = [lvl.percentage for lvl in first_snap.levels]
    assert percentages == sorted(percentages)


def test_depth_repo_available_dates(tmp_path: Path) -> None:
    depth_dir = tmp_path / "bookDepth" / "BTCUSDT"
    depth_dir.mkdir(parents=True)
    for date in ["2026-01-01", "2026-01-02"]:
        p = depth_dir / f"BTCUSDT-bookDepth-{date}.parquet"
        _write_depth_file(p)
    _load_parquet.cache_clear()

    repo = DepthRepository(tmp_path)
    dates = repo.available_dates("BTCUSDT")
    assert "2026-01-01" in dates
    assert "2026-01-02" in dates


def test_depth_repo_available_dates_missing_dir(tmp_path: Path) -> None:
    repo = DepthRepository(tmp_path)
    assert repo.available_dates("NONEXISTENT") == []


# ---------------------------------------------------------------------------
# DepthSnapshot.as_dicts
# ---------------------------------------------------------------------------


def test_depth_snapshot_as_dicts() -> None:
    level = DepthLevel(percentage=1.0, depth=5.0, notional=500.0)
    snap = DepthSnapshot(timestamp=datetime(2026, 1, 1), levels=(level,))
    dicts = snap.as_dicts()
    assert len(dicts) == 1
    assert dicts[0] == {"percentage": 1.0, "depth": 5.0, "notional": 500.0}


def test_depth_snapshot_as_dicts_empty() -> None:
    snap = DepthSnapshot(timestamp=datetime(2026, 1, 1), levels=())
    assert snap.as_dicts() == []


# ---------------------------------------------------------------------------
# DepthRepository.nearest
# ---------------------------------------------------------------------------


def test_nearest_returns_none_for_empty_list() -> None:
    result = DepthRepository.nearest([], datetime(2026, 1, 1))
    assert result is None


def test_nearest_single_snapshot() -> None:
    snap = DepthSnapshot(timestamp=datetime(2026, 1, 1, 0, 0), levels=())
    result = DepthRepository.nearest([snap], datetime(2026, 1, 1, 0, 5))
    assert result is snap


def test_nearest_picks_closest() -> None:
    t0 = datetime(2026, 1, 1, 0, 0)
    t1 = datetime(2026, 1, 1, 0, 10)
    s0 = DepthSnapshot(timestamp=t0, levels=())
    s1 = DepthSnapshot(timestamp=t1, levels=())
    # Target at 00:02 → closer to t0
    target = datetime(2026, 1, 1, 0, 2)
    result = DepthRepository.nearest([s0, s1], target)
    assert result is s0
    # Target at 00:08 → closer to t1
    target2 = datetime(2026, 1, 1, 0, 8)
    result2 = DepthRepository.nearest([s0, s1], target2)
    assert result2 is s1
