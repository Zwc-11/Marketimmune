"""Abstract-factory seam for market-data sources (12-Factor config).

Picks the venue adapter from an explicit argument or the
``MARKETIMMUNE_MARKET_SOURCE`` environment variable (default ``binance``).
This is the one place that maps a config string to concrete adapters, so
Phase 1 registers ``hyperliquid`` here and nothing else changes.
"""

from __future__ import annotations

import os
from pathlib import Path

from marketimmune.adapters.binance import BinanceDepthRepository, BinanceKlineRepository
from marketimmune.ports.market_data import DepthSource, KlineSource

DEFAULT_MARKET_SOURCE = "binance"
_MARKET_SOURCE_ENV = "MARKETIMMUNE_MARKET_SOURCE"


def market_data_sources(
    lake_root: Path | str,
    *,
    source: str | None = None,
) -> tuple[KlineSource, DepthSource]:
    """Return the ``(kline, depth)`` sources for the configured venue.

    Args:
        lake_root: Root of the parquet lake the adapters read from.
        source: Venue key. Falls back to ``$MARKETIMMUNE_MARKET_SOURCE`` and
            then to :data:`DEFAULT_MARKET_SOURCE`.
    """
    name = (source or os.getenv(_MARKET_SOURCE_ENV) or DEFAULT_MARKET_SOURCE).lower()
    root = Path(lake_root)
    if name == "binance":
        return BinanceKlineRepository(root), BinanceDepthRepository(root)
    raise ValueError(
        f"Unknown market source {name!r}. Known sources: 'binance'. "
        "Hyperliquid arrives in Phase 1 of the v2 migration."
    )
