from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from marketimmune.features.trade_state import (
    FEE_COLUMNS,
    FEE_PLACEBO_COLUMNS,
    FORCED_COLUMNS,
    TRADE_STATE_COLUMNS,
    block_table,
    trade_features,
    verify_trade_features_no_lookahead,
)


def _trades() -> pl.DataFrame:
    """Blocks 10-14, 100 ms apart: sellers hit the bid with fees in blocks 11 and 12, a buyer
    pays nothing in block 13, a liquidation sells in block 14."""
    rows = [
        # block, taker oid, px, notional, taker side, fee bps, liquidation
        (10, 1, 100.0, 1_000.0, "B", 0.0, False),
        (10, 2, 99.9, 1_000.0, "A", 0.0, False),
        (11, 3, 99.8, 2_000.0, "A", 2.0, False),
        (12, 4, 99.7, 1_000.0, "A", 6.0, False),
        (12, 5, 99.7, 1_000.0, "A", 0.0, False),
        (13, 6, 99.9, 3_000.0, "B", 0.0, False),
        (14, 7, 99.5, 5_000.0, "A", 0.0, True),
    ]
    return pl.DataFrame(
        {
            "block_number": [r[0] for r in rows],
            "taker_oid": [r[1] for r in rows],
            "t_ms": [1_000.0 + 100.0 * (r[0] - 10) for r in rows],
            "px": [r[2] for r in rows],
            "notional": [r[3] for r in rows],
            "taker_side": [r[4] for r in rows],
            "fee_bps": [r[5] for r in rows],
            "liquidation": [r[6] for r in rows],
        }
    )


def test_block_table_quotes_and_sides() -> None:
    b = block_table(_trades())
    assert b["block_number"].to_list() == [10, 11, 12, 13, 14]
    assert b["ask_px"].to_list() == [100.0, 100.0, 100.0, 99.9, 99.9]  # carried forward
    assert b["mid"].to_list() == pytest.approx([99.95, 99.9, 99.85, 99.8, 99.7])
    assert b["fee_usd_bid"].to_list() == [0.0, 4_000.0, 6_000.0, 0.0, 0.0] and b["max_fee_bid"].to_list() == [0.0, 2.0, 6.0, 0.0, 0.0]
    assert b["forced_usd_bid"].to_list() == [0.0, 0.0, 0.0, 0.0, 5_000.0]


def test_fee_pressure_reads_earlier_blocks_only() -> None:
    blocks = block_table(_trades())
    # a maker on the bid (hit by sellers) and one on the ask, both filled in block 13
    f = trade_features([13, 13], [1_300.0, 1_300.0], [1.0, -1.0], blocks)
    # k = 3: blocks 10-12. Bid side: 1,000 (no fee) + 2,000 at 2 bps + 1,000 at 6 + 1,000 at 0
    assert f["fp_same_3b"][0] == pytest.approx((4_000 + 6_000) / 5_000)
    assert f["fc_same_3b"][0] == 2 and f["fm_same_3b"][0] == 6.0 and f["share_same_3b"][0] == pytest.approx(3_000 / 5_000)
    assert f["fp_opp_3b"][0] == 0.0 and f["fp_imb_3b"][0] == pytest.approx(2.0)
    # the maker on the ask sees the same blocks from the other side
    assert f["fp_same_3b"][1] == 0.0 and f["fp_opp_3b"][1] == pytest.approx(2.0) and f["fp_imb_3b"][1] == pytest.approx(-2.0)
    # k = 3 from block 14 drops block 10 and adds block 13 (a buyer: ask side)
    g = trade_features([14], [1_400.0], [1.0], blocks)
    assert g["fc_same_3b"][0] == 2 and g["share_same_3b"][0] == pytest.approx(3_000 / 4_000)
    assert f[FORCED_COLUMNS[0]][0] == 0.0 and trade_features([15], [1_500.0], [1.0], blocks)[FORCED_COLUMNS[0]][0] == 5_000.0


def test_trade_state_windows() -> None:
    blocks = block_table(_trades())
    f = trade_features([14], [1_400.0], [1.0], blocks)
    # 1 s window: blocks 10-13. Buys 1,000 + 3,000, sells 5,000
    assert f["flow_maker_1000ms"][0] == pytest.approx((4_000 - 5_000) / 9_000)
    assert f["log_taker_usd_1000ms"][0] == pytest.approx(np.log1p(9_000.0)) and f["log_trades_1000ms"][0] == pytest.approx(np.log1p(6))
    assert f["tm_spread_bps"][0] == pytest.approx(0.2 / 99.8 * 1e4)  # after block 13: ask 99.9, bid 99.7
    assert f["log_ms_since_trade"][0] == pytest.approx(np.log1p(100.0))
    r = np.log(np.array([99.9, 99.85, 99.8]) / np.array([99.95, 99.9, 99.85]))
    assert f["tm_vol_10000ms_bps"][0] == pytest.approx(np.sqrt((r**2).sum()) * 1e4)
    first = trade_features([10], [1_000.0], [1.0], blocks)
    assert np.isnan(first["tm_spread_bps"][0]) and first["log_taker_usd_1000ms"][0] == 0.0


def test_no_lookahead_check_passes() -> None:
    trades = _trades()
    report = verify_trade_features_no_lookahead(
        trades["block_number"].to_numpy(),
        trades["t_ms"].to_numpy(),
        np.where(trades["taker_side"].to_numpy() == "A", 1.0, -1.0),
        trades,
        (*TRADE_STATE_COLUMNS, *FEE_COLUMNS, *FEE_PLACEBO_COLUMNS, *FORCED_COLUMNS),
    )
    assert report["passed"] and report["n_mismatched"] == 0


def test_block_quotes_use_execution_order_not_file_order() -> None:
    # one block, listed out of order: buy order 7 sweeps 100.0 then 100.2 after buy order 5
    # filled at 99.9; seller order 6 sweeps 99.8 then 99.6. The block's last ask is 100.2 and
    # its last bid 99.6, whatever order the rows come in.
    rows = [(7, 100.2, "B"), (6, 99.6, "A"), (5, 99.9, "B"), (7, 100.0, "B"), (6, 99.8, "A")]
    trades = pl.DataFrame(
        {
            "block_number": [10] * len(rows),
            "taker_oid": [r[0] for r in rows],
            "t_ms": [1_000.0] * len(rows),
            "px": [r[1] for r in rows],
            "notional": [1_000.0] * len(rows),
            "taker_side": [r[2] for r in rows],
            "fee_bps": [0.0] * len(rows),
            "liquidation": [False] * len(rows),
        }
    )
    row = block_table(trades).row(0, named=True)
    assert (row["ask_px"], row["bid_px"]) == (100.2, 99.6)
