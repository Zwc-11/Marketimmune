"""MarketImmune: predict which Hyperliquid perp fills a market maker will regret.

Sub-packages follow the pipeline: ``sources`` (Bronze) -> ``lake`` (Silver/Gold)
-> ``labels`` and ``features`` -> ``models`` -> ``serving``; ``priority`` holds the
priority-fee study and ``cli`` the commands.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
