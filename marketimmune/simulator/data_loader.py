"""Repository pattern around the Binance parquet lake.

Anything that reads `.parquet` files lives here. The rest of the
simulator depends on the *interfaces* (`KlineRecord`, `DepthSnapshot`,
`KlineRepository`, `DepthRepository`) which makes it trivial to swap in
a Kafka-backed source or an HTTP-backed mock for tests.

A small in-process LRU cache is used because the dev server may build
many replays back-to-back and the parquet decode dominates wall-time;
clearing it is as simple as restarting the process.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

# -- Data classes ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KlineRecord:
    """One 1-minute OHLCV bar from Binance USD-M parquet."""

    event_id: str
    timestamp: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DepthLevel:
    """One aggregated %-from-mid level: stored exactly as Binance returns."""

    percentage: float
    depth: float
    notional: float


@dataclass(frozen=True, slots=True)
class DepthSnapshot:
    """All %-from-mid levels recorded at a single timestamp."""

    timestamp: datetime
    levels: tuple[DepthLevel, ...]

    def as_dicts(self) -> list[dict[str, Any]]:
        """API-friendly representation."""
        return [
            {"percentage": lvl.percentage, "depth": lvl.depth, "notional": lvl.notional}
            for lvl in self.levels
        ]


# -- Helpers --------------------------------------------------------------


def _parse_iso(s: str) -> datetime:
    """Parse Binance ISO timestamps as naive datetimes (UTC wall time)."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


# -- Repositories ---------------------------------------------------------


class KlineRepository:
    """Loads 1-minute kline parquet files for a symbol."""

    def __init__(self, lake_root: Path):
        self.lake_root = Path(lake_root)

    def directory_for(self, symbol: str, interval: str = "1m") -> Path:
        return self.lake_root / "klines" / symbol / interval

    def available_dates(self, symbol: str) -> list[str]:
        symbol_directory = self.directory_for(symbol)
        if not symbol_directory.exists():
            return []
        # File names look like BTCUSDT-klines-1m-2026-01-01.parquet
        return sorted(
            "-".join(file.stem.rsplit("-", 3)[-3:])
            for file in symbol_directory.glob("*.parquet")
        )

    def load(self, symbol: str, date: str | None, limit: int) -> list[KlineRecord]:
        symbol_directory = self.directory_for(symbol)
        if not symbol_directory.exists():
            return []
        files = sorted(symbol_directory.glob("*.parquet"))
        if not files:
            return []
        chosen = next((file for file in files if date and date in file.name), files[0])
        rows = _load_parquet(str(chosen))
        rows.sort(key=lambda row: row["timestamp"])
        records: list[KlineRecord] = []
        for kline_row in rows[:limit]:
            records.append(KlineRecord(
                event_id=kline_row.get("event_id", ""),
                timestamp=_parse_iso(kline_row["timestamp"]),
                symbol=symbol,
                open=float(kline_row["open_price"]),
                high=float(kline_row["high_price"]),
                low=float(kline_row["low_price"]),
                close=float(kline_row["close_price"]),
                volume=float(kline_row["volume"]),
                trade_count=int(kline_row.get("trade_count", 0)),
                raw=kline_row,
            ))
        return records


class DepthRepository:
    """Loads aggregated %-from-mid bookDepth parquet files for a symbol."""

    def __init__(self, lake_root: Path):
        self.lake_root = Path(lake_root)

    def directory_for(self, symbol: str) -> Path:
        return self.lake_root / "bookDepth" / symbol

    def available_dates(self, symbol: str) -> list[str]:
        symbol_directory = self.directory_for(symbol)
        if not symbol_directory.exists():
            return []
        # File names look like BTCUSDT-bookDepth-2026-01-01.parquet
        return sorted(
            "-".join(file.stem.rsplit("-", 3)[-3:])
            for file in symbol_directory.glob("*.parquet")
        )

    def load(self, symbol: str, date: str) -> list[DepthSnapshot]:
        path = self.directory_for(symbol) / f"{symbol}-bookDepth-{date}.parquet"
        if not path.exists():
            return []
        rows = _load_parquet(str(path))
        # Group by timestamp first, then build a compact, sorted tuple per snap.
        grouped: dict[str, list[dict[str, Any]]] = {}
        for depth_row in rows:
            grouped.setdefault(depth_row["timestamp"], []).append(depth_row)
        snaps: list[DepthSnapshot] = []
        for ts_str, ladder in grouped.items():
            ladder.sort(key=lambda level: level["percentage"])
            levels = tuple(
                DepthLevel(
                    percentage=float(level["percentage"]),
                    depth=float(level["depth"]),
                    notional=float(level["notional"]),
                )
                for level in ladder
            )
            snaps.append(DepthSnapshot(timestamp=_parse_iso(ts_str), levels=levels))
        snaps.sort(key=lambda snapshot: snapshot.timestamp)
        return snaps

    @staticmethod
    def nearest(
        snapshots: list[DepthSnapshot], target: datetime
    ) -> DepthSnapshot | None:
        """Return the snapshot whose timestamp is closest to `target`."""
        if not snapshots:
            return None
        keys = [snapshot.timestamp for snapshot in snapshots]
        idx = bisect.bisect_left(keys, target)
        candidates = []
        if idx < len(keys):
            candidates.append(idx)
        if idx > 0:
            candidates.append(idx - 1)
        best = min(
            candidates,
            key=lambda candidate_idx: abs((keys[candidate_idx] - target).total_seconds()),
        )
        return snapshots[best]


# -- Caching shim ---------------------------------------------------------


@lru_cache(maxsize=4)
def _load_parquet(path: str) -> list[dict[str, Any]]:
    """Read a parquet file once and cache the materialised list of rows.

    We intentionally use a string key (the path) so the cache survives
    re-imports of `KlineRepository` / `DepthRepository` inside Django.
    The lake on disk is append-only so this cache never serves stale data
    during a single dev-server lifetime.
    """
    table = pq.read_table(path)
    return list(table.to_pylist())
