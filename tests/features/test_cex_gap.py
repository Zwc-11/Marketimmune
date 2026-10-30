"""Tests for the L1 CEX-gap control."""

from __future__ import annotations

import math
import zipfile
from pathlib import Path

import numpy as np
import pytest

from marketimmune.features.cex_gap import (
    CEX_FEATURE_COLUMNS,
    PriceSeries,
    cex_gap_features,
    mid_change_times,
    read_binance_aggtrades_zip,
    verify_cex_gap_no_lookahead,
)

BP = 1e4


def test_price_series_sorts_validates_and_looks_up() -> None:
    s = PriceSeries.from_arrays([20.0, 10.0], [101.0, 100.0])
    assert s.ts_ms.tolist() == [10.0, 20.0]
    got = s.at_or_before(np.array([5.0, 10.0, 19.0, 25.0]))
    assert math.isnan(got[0])
    assert np.exp(got[1:]).tolist() == pytest.approx([100.0, 100.0, 101.0])
    with pytest.raises(ValueError, match="same length"):
        PriceSeries.from_arrays([1.0], [])
    with pytest.raises(ValueError, match="positive"):
        PriceSeries.from_arrays([1.0], [0.0])
    both = PriceSeries.concat([PriceSeries.from_arrays([30.0], [99.0]), s])
    assert both.ts_ms.tolist() == [10.0, 20.0, 30.0]
    assert PriceSeries.concat([]).ts_ms.size == 0


@pytest.mark.parametrize("header", [True, False])
def test_read_binance_aggtrades_zip(tmp_path: Path, header: bool) -> None:
    rows = "1,133.37,39.7,10,18,1764547200028,true\n2,133.38,0.31,19,19,1764547200049,false\n"
    text = ("agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,"
            "is_buyer_maker\n" if header else "") + rows
    path = tmp_path / "SOLUSDT-aggTrades-2025-12-01.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("SOLUSDT-aggTrades-2025-12-01.csv", text)
    s = read_binance_aggtrades_zip(path)
    assert s.ts_ms.tolist() == [1764547200028.0, 1764547200049.0]
    assert np.exp(s.log_px).tolist() == pytest.approx([133.37, 133.38])


def test_mid_change_times() -> None:
    assert mid_change_times([0, 1, 2, 3], [5.0, 5.0, 6.0, 6.0]).tolist() == [0, 0, 2, 2]


def _scenario() -> tuple[PriceSeries, np.ndarray, np.ndarray]:
    # Binance: 100 until it jumps to 101 at t=1500 ms, then 102 at t=1900 (inside
    # the latency window, so a fill at 2000 must not see it). HL mid sits at 100
    # from t=0 and only catches up at t=2000, the fill's own millisecond.
    cex = PriceSeries.from_arrays([-1000.0, 1500.0, 1900.0], [100.0, 101.0, 102.0])
    hl_ts = np.array([0.0, 500.0, 2000.0])
    hl_mid = np.array([100.0, 100.0, 101.0])
    return cex, hl_ts, hl_mid


def test_cex_gap_features_respect_latency_and_strict_hl_asof() -> None:
    cex, hl_ts, hl_mid = _scenario()
    f = cex_gap_features([2000.0], [-1.0], hl_ts, hl_mid, cex, latency_ms=300.0)
    assert set(f) == set(CEX_FEATURE_COLUMNS)
    jump = math.log(101.0 / 100.0) * BP
    assert f["cex_gap_bps"][0] == pytest.approx(jump)  # sees 101 (t<=1700), not 102
    assert f["cex_gap_maker_bps"][0] == pytest.approx(-jump)  # maker sold before the rise
    assert f["cex_ret_1000ms_bps"][0] == pytest.approx(jump)
    assert f["cex_ret_100ms_bps"][0] == pytest.approx(0.0)
    assert f["cex_ret_1000ms_maker_bps"][0] == pytest.approx(-jump)
    early = cex_gap_features([-5000.0], [1.0], hl_ts, hl_mid, cex)
    assert math.isnan(early["cex_gap_bps"][0])
    with pytest.raises(ValueError, match="latency_ms"):
        cex_gap_features([2000.0], [1.0], hl_ts, hl_mid, cex, latency_ms=0.0)


def test_verify_cex_gap_no_lookahead_passes() -> None:
    cex, hl_ts, hl_mid = _scenario()
    fills = np.array([600.0, 1600.0, 2000.0, 2500.0])
    sides = np.array([1.0, -1.0, 1.0, -1.0])
    report = verify_cex_gap_no_lookahead(fills, sides, hl_ts, hl_mid, cex)
    assert report["passed"] is True and report["n_checked"] == 4
    empty = verify_cex_gap_no_lookahead(np.zeros(0), np.zeros(0), hl_ts, hl_mid, cex)
    assert empty["passed"] is False
