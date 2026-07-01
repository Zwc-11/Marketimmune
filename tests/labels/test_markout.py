"""Tests for the realized-markout adverse-selection label (100% branch coverage)."""

import pytest

from marketimmune.labels import (
    MakerFill,
    MarkoutConfig,
    future_mid_at,
    is_toxic,
    markout_bps,
    realized_markout_bps,
)


def test_markout_buy_pickoff_is_negative() -> None:
    # Maker bought at 100; mid falls to 99 -> picked off -> negative.
    assert markout_bps(100.0, 99.0, side=1) == pytest.approx(-100.0)


def test_markout_buy_favourable_is_positive() -> None:
    assert markout_bps(100.0, 101.0, side=1) == pytest.approx(100.0)


def test_markout_sell_pickoff_is_negative() -> None:
    # Maker sold at 100; mid rises to 101 -> picked off -> negative.
    assert markout_bps(100.0, 101.0, side=-1) == pytest.approx(-100.0)


def test_markout_rejects_nonpositive_price() -> None:
    with pytest.raises(ValueError, match="fill_price"):
        markout_bps(0.0, 100.0, side=1)


def test_markout_rejects_bad_side() -> None:
    with pytest.raises(ValueError, match="side"):
        markout_bps(100.0, 100.0, side=0)


def test_is_toxic_threshold() -> None:
    assert is_toxic(-2.0, fee_bps=1.0)
    assert not is_toxic(-0.5, fee_bps=1.0)


def test_future_mid_forward_asof() -> None:
    mid_ts = [0.0, 1.0, 2.0, 3.0]
    mid_px = [100.0, 101.0, 102.0, 103.0]
    # fill at t=0, horizon 2s -> first mid at/after t=2 -> 102.
    assert future_mid_at(0.0, 2.0, mid_ts, mid_px) == 102.0


def test_future_mid_beyond_series_is_none() -> None:
    assert future_mid_at(0.0, 99.0, [0.0, 1.0], [100.0, 101.0]) is None


def test_future_mid_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="same length"):
        future_mid_at(0.0, 1.0, [0.0, 1.0], [100.0])


def test_realized_markout_uses_horizon() -> None:
    fill = MakerFill(ts_s=0.0, price=100.0, side=1)
    mid_ts = [0.0, 1.0, 2.0]
    mid_px = [100.0, 100.0, 98.0]
    # at t+2 mid=98 -> buy picked off -> (98-100)/100*1e4 = -200 bps.
    assert realized_markout_bps(fill, mid_ts, mid_px, horizon_s=2.0) == pytest.approx(-200.0)


def test_realized_markout_none_past_end() -> None:
    fill = MakerFill(ts_s=0.0, price=100.0, side=1)
    assert realized_markout_bps(fill, [0.0], [100.0], horizon_s=5.0) is None


def test_markout_config_defaults() -> None:
    cfg = MarkoutConfig()
    assert cfg.horizons_s == (1.0, 10.0, 60.0)
    assert cfg.fee_bps == 1.0
