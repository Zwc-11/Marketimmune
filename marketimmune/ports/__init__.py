"""Ports — infrastructure-agnostic interfaces the domain depends on.

Phase 1 of the current roadmap keeps this seam intentionally small. The replay
engine and immune loop depend on these Protocols, never on a concrete venue, so
swapping Binance for Hyperliquid (or any other source) is a new *adapter*, not a
domain change. See :mod:`marketimmune.adapters` for the implementations.
"""

from marketimmune.ports.market_data import DepthSource, KlineSource

__all__ = ["DepthSource", "KlineSource"]
