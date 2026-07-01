"""Binance market-data adapter (the v1 source; deprecated by Phase 3).

The concrete parquet repositories already live in
:mod:`marketimmune.simulator.data_loader`. This module gives them their
venue-specific names and is the single place the rest of v2 references
"Binance" — a Hyperliquid adapter will sit beside it without touching the
domain. The aliases satisfy :class:`marketimmune.ports.market_data.KlineSource`
and :class:`~marketimmune.ports.market_data.DepthSource` structurally.
"""

from __future__ import annotations

from marketimmune.simulator.data_loader import DepthRepository as BinanceDepthRepository
from marketimmune.simulator.data_loader import KlineRepository as BinanceKlineRepository

__all__ = ["BinanceDepthRepository", "BinanceKlineRepository"]
