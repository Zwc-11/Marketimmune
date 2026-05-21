"""Pure-function tests for the derived-quote helper."""

from __future__ import annotations

from datetime import datetime

from marketimmune.simulator.data_loader import DepthLevel, DepthSnapshot
from marketimmune.simulator.pricing import derive_quote_from_depth


def _snapshot(*levels: tuple[float, float, float]) -> DepthSnapshot:
    return DepthSnapshot(
        timestamp=datetime(2026, 1, 1),
        levels=tuple(DepthLevel(percentage=p, depth=d, notional=n) for p, d, n in levels),
    )


def test_quote_uses_inside_band_when_present() -> None:
    snap = _snapshot(
        (-2.0, 1.0, 100.0),
        (-1.0, 1.5, 110.0),
        (+1.0, 2.0, 120.0),
        (+2.0, 0.5, 50.0),
    )
    quote = derive_quote_from_depth(mid=100.0, snapshot=snap)
    # Inside band is ±1%, so bid=99, ask=101, spread=2.
    assert quote.bid == 99.0
    assert quote.ask == 101.0
    assert quote.spread == 2.0
    assert quote.band_percent == 1.0


def test_quote_falls_back_when_no_snapshot() -> None:
    quote = derive_quote_from_depth(mid=100.0, snapshot=None, fallback_band=2.0)
    assert quote.bid == 98.0
    assert quote.ask == 102.0
    assert quote.band_percent == 2.0


def test_quote_handles_zero_mid_safely() -> None:
    quote = derive_quote_from_depth(mid=0.0, snapshot=None)
    assert quote.bid == 0.0
    assert quote.ask == 0.0
    assert quote.spread == 0.0
