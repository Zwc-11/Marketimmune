"""Immutable value objects describing a replay run.

Using a frozen dataclass keeps the config hashable and side-effect free
so the same `ReplayConfig` can be reused in tests, the Django command,
and any future notebook driver without aliasing bugs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """One replay invocation expressed as a value object.

    Attributes:
        symbol: Trading symbol whose parquet data should be replayed.
        scenario_name: Key registered in `ScenarioRegistry`.
        speed: UI playback speed multiplier (1x..100x). Engine itself is
            speed-agnostic — the value is persisted so the cockpit can
            recover the user's preference after a refresh.
        limit: Maximum number of klines to materialise into the session.
        replay_date: Optional ISO date (YYYY-MM-DD) used to align kline +
            bookDepth parquet files. When `None` the loader picks the
            first date with both files present.
    """

    symbol: str = "BTCUSDT"
    scenario_name: str = "spoofing_layering"
    speed: int = 10
    limit: int = 1440
    replay_date: str | None = None
