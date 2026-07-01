"""Market-data seam acceptance tests.

Proves that routing market-data construction through the ports + adapter factory
produces *identical* replay behavior to constructing the Binance repositories
directly — the exit criterion for the "Seam" phase ("v1 behaves identically
through ports") and the rollback safety net for the Hyperliquid migration.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.adapters import (
    BinanceDepthRepository,
    BinanceKlineRepository,
    market_data_sources,
)
from marketimmune.simulator.config import ReplayConfig
from marketimmune.simulator.data_loader import (
    DepthRepository,
    KlineRepository,
    _load_parquet,
)
from marketimmune.simulator.replay_builder import ReplayBuilder

SYMBOL = "BTCUSDT"
DATE = "2026-01-01"


def _write_lake(lake: Path) -> None:
    """Write a tiny aligned kline + bookDepth lake (mirrors test_data_loader)."""
    kline_path = lake / "klines" / SYMBOL / "1m" / f"{SYMBOL}-klines-1m-{DATE}.parquet"
    kline_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "event_id": ["ev1", "ev2", "ev3"],
                "timestamp": [
                    f"{DATE}T00:00:00Z",
                    f"{DATE}T00:01:00Z",
                    f"{DATE}T00:02:00Z",
                ],
                "open_price": [100.0, 101.0, 102.0],
                "high_price": [105.0, 106.0, 107.0],
                "low_price": [99.0, 100.0, 101.0],
                "close_price": [101.0, 102.0, 103.0],
                "volume": [1000.0, 2000.0, 3000.0],
                "trade_count": [10, 20, 30],
            }
        ),
        kline_path,
    )
    depth_path = lake / "bookDepth" / SYMBOL / f"{SYMBOL}-bookDepth-{DATE}.parquet"
    depth_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "timestamp": [f"{DATE}T00:00:00Z", f"{DATE}T00:00:00Z", f"{DATE}T00:01:00Z"],
                "percentage": [1.0, -1.0, 1.0],
                "depth": [5.0, 4.0, 6.0],
                "notional": [500.0, 400.0, 600.0],
            }
        ),
        depth_path,
    )
    _load_parquet.cache_clear()


def _config() -> ReplayConfig:
    return ReplayConfig(symbol=SYMBOL, scenario_name="spoofing_layering", replay_date=DATE, limit=3)


def test_from_lake_matches_direct_construction(tmp_path: Path) -> None:
    """The factory-wired builder yields the same ticks as direct repos."""
    _write_lake(tmp_path)

    direct = ReplayBuilder(
        kline_repo=KlineRepository(tmp_path),
        depth_repo=DepthRepository(tmp_path),
    )
    via_seam = ReplayBuilder.from_lake(tmp_path)

    plan_direct = direct.build(_config())
    plan_seam = via_seam.build(_config())

    # run_id carries a random uuid; everything that depends on the data must match.
    assert plan_seam.ticks == plan_direct.ticks
    assert plan_seam.depth_snapshot_count == plan_direct.depth_snapshot_count
    assert len(plan_seam.ticks) == 3


def test_factory_defaults_to_binance(tmp_path: Path) -> None:
    kline_repo, depth_repo = market_data_sources(tmp_path)
    assert isinstance(kline_repo, BinanceKlineRepository)
    assert isinstance(depth_repo, BinanceDepthRepository)


def test_binance_adapters_are_the_concrete_repositories() -> None:
    # The Binance adapter is intentionally a thin alias for Phase 0.
    assert BinanceKlineRepository is KlineRepository
    assert BinanceDepthRepository is DepthRepository


def test_factory_is_case_insensitive(tmp_path: Path) -> None:
    kline_repo, _ = market_data_sources(tmp_path, source="BINANCE")
    assert isinstance(kline_repo, BinanceKlineRepository)


def test_factory_reads_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETIMMUNE_MARKET_SOURCE", "binance")
    kline_repo, _ = market_data_sources(tmp_path)
    assert isinstance(kline_repo, BinanceKlineRepository)


def test_factory_rejects_unknown_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown market source"):
        market_data_sources(tmp_path, source="hyperliquid")
