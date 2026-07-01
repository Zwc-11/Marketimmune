"""Adapters — concrete implementations of the market-data ports.

Each adapter binds a real venue/store to the Protocols in
:mod:`marketimmune.ports`. Binance (the v1 source) lives in
:mod:`marketimmune.adapters.binance`; Hyperliquid arrives in Phase 1. Use
:func:`marketimmune.adapters.factory.market_data_sources` to construct the
configured pair rather than importing a venue directly.
"""

from marketimmune.adapters.binance import BinanceDepthRepository, BinanceKlineRepository
from marketimmune.adapters.factory import DEFAULT_MARKET_SOURCE, market_data_sources

__all__ = [
    "DEFAULT_MARKET_SOURCE",
    "BinanceDepthRepository",
    "BinanceKlineRepository",
    "market_data_sources",
]
