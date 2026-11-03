"""Tests for margin tiers and the liquidation-price formula."""

from __future__ import annotations

import pytest

from marketimmune.forced.margin_tiers import (
    liquidation_price,
    maintenance_margin,
    max_leverage_distance,
    tiers_for,
)


def test_maintenance_margin_is_continuous_across_tiers() -> None:
    assert maintenance_margin("SOL", 1e6) == pytest.approx(25_000.0)  # 2.5% at 20x
    below = maintenance_margin("SOL", 70e6)
    above = maintenance_margin("SOL", 70e6 + 1.0)
    assert above - below == pytest.approx(0.05, abs=1e-6)  # the 5% rate on the extra dollar
    assert maintenance_margin("SOL", 100e6) == pytest.approx(70e6 * 0.025 + 30e6 * 0.05)
    with pytest.raises(AssertionError, match="no margin tiers"):
        tiers_for("FOO")


def test_liquidation_price_at_max_leverage() -> None:
    # long 100 SOL at 100 with isolated margin N / 20: liquidation 1/39 below entry
    n = 100 * 100.0
    margin_available = n / 20 - maintenance_margin("SOL", n)
    liq = liquidation_price("SOL", 100.0, 100.0, margin_available)
    assert liq == pytest.approx(100.0 * (1 - 1 / 39))
    assert 1 - liq / 100.0 == pytest.approx(max_leverage_distance("SOL", +1))
    short = liquidation_price("SOL", -100.0, 100.0, margin_available)
    assert short / 100.0 - 1 == pytest.approx(max_leverage_distance("SOL", -1))
    assert max_leverage_distance("SOL", -1) == pytest.approx(1 / 41)
    # at liquidation, equity equals maintenance margin
    equity_at_liq = n / 20 - 100.0 * (100.0 - liq)
    assert equity_at_liq == pytest.approx(maintenance_margin("SOL", 100.0 * liq))
    with pytest.raises(AssertionError, match="no position"):
        liquidation_price("SOL", 0.0, 100.0, 1.0)
