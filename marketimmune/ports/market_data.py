"""Market-data ports.

These Protocols describe *what* the replay engine needs from a market-data
source, with no commitment to *where* the data comes from. The Binance parquet
repositories in :mod:`marketimmune.simulator.data_loader` already satisfy them
structurally, and a future ``HyperliquidArchiveAdapter`` is a drop-in.

The record value objects (``KlineRecord`` / ``DepthSnapshot``) are reused from
``data_loader`` rather than duplicated; a later phase can move them to a neutral
module if the dependency direction needs tightening.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from marketimmune.simulator.data_loader import DepthSnapshot, KlineRecord


class KlineSource(Protocol):
    """Reads 1-minute OHLCV bars for a symbol from some venue/store."""

    def directory_for(self, symbol: str, interval: str = "1m") -> Path: ...

    def available_dates(self, symbol: str) -> list[str]: ...

    def load(self, symbol: str, date: str | None, limit: int) -> list[KlineRecord]: ...


class DepthSource(Protocol):
    """Reads aggregated %-from-mid book-depth snapshots for a symbol."""

    def directory_for(self, symbol: str) -> Path: ...

    def available_dates(self, symbol: str) -> list[str]: ...

    def load(self, symbol: str, date: str) -> list[DepthSnapshot]: ...

    def nearest(
        self, snapshots: list[DepthSnapshot], target: datetime
    ) -> DepthSnapshot | None: ...
