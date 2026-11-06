"""Live paper trading on Hyperliquid perps: public market data in, simulated quotes and fills out.

No order is ever sent. ``events`` parses the WebSocket messages, ``signals`` keeps each coin's
features and the walk-forward model, ``orders`` matches paper orders against the real trades,
``strategies`` decides the quotes, ``engine`` ties them together and ``live`` runs the feeds.
Results: ``docs/research/paper-trading.md``.
"""
