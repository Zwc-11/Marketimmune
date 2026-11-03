"""Tests for the position roll-forward from fills."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from marketimmune.forced.positions import (
    long_short_open_interest,
    open_positions,
    roll_positions,
    wallet_events,
)


def _fills(rows: list[tuple]) -> pd.DataFrame:
    cols = ["ts_ms", "px", "sz", "taker_side", "taker_user", "maker_user", "taker_start_position", "maker_start_position", "liquidation"]
    return pd.DataFrame(rows, columns=cols)


def test_wallet_events_signs_and_order() -> None:
    ev = wallet_events(
        _fills(
            [
                (2, 101.0, 1.0, "A", "u", "v", 0.0, 0.0, True),
                (1, 100.0, 2.0, "B", "t", None, 0.0, 5.0, False),
                (2, 102.0, 3.0, "B", "w", "x", 1.0, None, False),
            ]
        )
    )
    # time order, maker before taker; a side with no wallet or no start position is dropped
    assert list(zip(ev.ts_ms, ev.seq, ev.role, ev.wallet, strict=True)) == [
        (1, 1, "taker", "t"),
        (2, 0, "maker", "v"),
        (2, 0, "taker", "u"),
        (2, 2, "taker", "w"),
    ]
    assert ev.delta.tolist() == [2.0, 1.0, -1.0, 3.0]
    assert ev.forced.tolist() == [False, False, True, False]


def test_roll_tracks_entry_detects_breaks_and_liquidations() -> None:
    fills = _fills(
        [
            (1, 100.0, 2.0, "B", "a", "m", 0.0, 10.0, False),  # a opens long 2 @100
            (2, 110.0, 2.0, "B", "a", "m", 2.0, 8.0, False),  # a adds: entry 105
            (3, 120.0, 1.0, "A", "a", "m", 4.0, 6.0, False),  # a reduces: entry stays 105
            (4, 90.0, 3.0, "A", "a", "m", 3.0, 7.0, True),  # forced sell of a, to flat
            (5, 95.0, 1.0, "A", "a", "m", 0.0, 10.0, False),  # a opens short 1 @95
            (6, 96.0, 2.0, "B", "a", "m", -1.0, 11.0, False),  # a flips to long 1 @96
            (7, 97.0, 1.0, "B", "a", "m", 5.0, 9.0, False),  # a's start_pos jumped: break
        ]
    )
    rolled, state, stats = roll_positions(wallet_events(fills))
    a = rolled[rolled.wallet == "a"].reset_index(drop=True)
    assert a.position_after.tolist() == [2.0, 4.0, 3.0, 0.0, -1.0, 1.0, 6.0]
    assert a.entry_px_after[1] == pytest.approx(105.0) and a.entry_px_after[2] == pytest.approx(105.0)
    assert math.isnan(a.entry_px_after[3]) and a.entry_px_after[4] == 95.0
    assert a.entry_px_after[5] == 96.0 and math.isnan(a.entry_px_after[6])
    assert a.chain_ok.tolist() == [True] * 6 + [False]
    assert stats.breaks == 1 and stats.break_abs_sizes == [4.0]
    assert stats.liquidation_events == 1 and stats.to_dict()["liquidation_reducing_share"] == 1.0
    assert stats.wallets == 2 and stats.chained == 12
    # maker "m" first seen at 10.0 with unknown entry, chain intact throughout
    assert rolled[rolled.wallet == "m"].chain_ok.all()
    opened = open_positions(state).set_index("wallet")
    assert opened.loc["a", "position"] == 6.0 and opened.loc["m", "position"] == 8.0
    assert long_short_open_interest(state) == {"long": 14.0, "short": 0.0}


def test_state_carries_across_calls_and_empty_stats() -> None:
    day1 = _fills([(1, 100.0, 1.0, "B", "a", "m", 0.0, 0.0, False)])
    day2 = _fills([(2, 101.0, 1.0, "B", "a", "m", 1.0, -1.0, False)])
    _r, state, _s = roll_positions(wallet_events(day1))
    _r2, state, stats = roll_positions(wallet_events(day2), state)
    assert stats.breaks == 0 and stats.chained == 2
    assert state["a"].entry_px == pytest.approx(100.5)
    empty = roll_positions(wallet_events(day1.iloc[:0]))[2].to_dict()
    assert empty["chain_break_share"] is None and empty["unknown_entry_share"] is None
    assert open_positions({}).empty
