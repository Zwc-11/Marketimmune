"""Tests for forced-flow inputs from node fills and snapshots (forecaster v2)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import polars as pl
import pytest

from marketimmune.forced.margin_tiers import maintenance_terms
from marketimmune.forced.node_book import (
    CROSSED,
    Account,
    account_from_snapshot,
    chain_rank,
    execution_order,
    liquidation_events,
    market_liquidations,
    roll_accounts,
    solve_liquidation_price,
    wallet_events,
)
from marketimmune.forced.positions import roll_positions


def _leg(
    block: int, user: str, side: str, sz: float, start: float, *, px: float = 100.0, crossed: bool = False, **extra: Any
) -> dict[str, Any]:
    return {
        "coin": "SOL", "block_number": block, "time_ms": 1_000 * block, "tid": 0, "oid": 0, "user": user, "side": side,
        "px": px, "sz": sz, "start_position": start, "crossed": crossed, "liquidated_user": extra.get("liquidated_user"),
        "liquidation_mark_px": extra.get("mark"), "liquidation_method": extra.get("method"),
    }  # fmt: skip


def test_fills_are_rechained_within_a_block() -> None:
    # wallet a fills three orders in block 2, listed out of order; b is already in order
    rows = [
        _leg(1, "a", "B", 1.0, 0.0),
        _leg(2, "a", "A", 1.0, 3.0),  # 3 -> 2
        _leg(2, "b", "B", 1.0, 0.0),
        _leg(2, "a", "B", 2.0, 1.0),  # 1 -> 3, first
        _leg(2, "b", "B", 1.0, 1.0),
        _leg(2, "a", "A", 4.0, 2.0),  # 2 -> -2, last
    ]
    legs = pl.DataFrame(rows)
    ordered = execution_order(legs).filter(pl.col("user") == "a")
    assert ordered["start_position"].to_list() == [0.0, 1.0, 3.0, 2.0]
    _, _, stats = roll_positions(wallet_events(legs))
    assert stats.breaks == 0


def test_chain_rank_keeps_file_order_when_it_cannot_chain() -> None:
    # a cycle (0 -> 1 -> 0 -> 1): no unique head, so file order
    assert chain_rank(np.array([0, 1, 0]), np.array([1, 0, 1])).tolist() == [0, 1, 2]
    assert chain_rank(np.array([5, 0, 2]), np.array([7, 2, 5])).tolist() == [2, 0, 1]


def test_market_liquidations_and_first_events() -> None:
    rows = [
        _leg(1, "x", "A", 2.0, 2.0, px=97.0, crossed=True, liquidated_user="x", mark=97.1, method="market"),
        _leg(1, "m", "B", 2.0, 0.0, px=97.0, liquidated_user="x", mark=97.1, method="market"),
        _leg(2, "y", "B", 1.0, -1.0, px=103.0, liquidated_user="y", mark=103.2, method="backstop"),
        _leg(2, "v", "A", 1.0, 0.0, px=103.0, crossed=True, liquidated_user="y", mark=103.2, method="backstop"),
    ]
    legs = pl.DataFrame(rows)
    ts, sells, usd = market_liquidations(legs)
    assert ts.tolist() == [1_000.0] and sells.tolist() == [True] and usd.tolist() == [194.0]
    ev = liquidation_events(legs)
    assert ev.select("user", "method", "mark", "usd").rows() == [("x", "market", 97.1, 194.0), ("y", "backstop", 103.2, 103.0)]
    assert wallet_events(legs)["forced"].tolist() == [False, True, False, False]  # maker leg first in its block


@pytest.mark.parametrize("isolated", [False, True])
@pytest.mark.parametrize("size", [50.0, -50.0])
def test_account_reproduces_the_snapshot_price(size: float, isolated: bool) -> None:
    liq = 90.0 if size > 0 else 110.0
    a = account_from_snapshot("SOL", size, abs(size) * 100.0, liq, 2_000.0, isolated, 10.0)
    assert solve_liquidation_price("SOL", a.size, a.equity, a.mark, a.other_mm) == pytest.approx(liq)
    assert (a.other_mm == 0.0) == isolated


def test_no_price_and_crossed() -> None:
    assert solve_liquidation_price("SOL", 0.0, 1.0, 100.0, 0.0) == math.inf
    assert solve_liquidation_price("SOL", 10.0, 1e9, 100.0, 0.0) == math.inf  # equity covers any fall
    assert solve_liquidation_price("SOL", -10.0, -1e6, 100.0, 0.0) == CROSSED
    a = account_from_snapshot("SOL", 10.0, 1_000.0, math.nan, 500.0)
    assert (a.equity, a.other_mm) == (500.0, 0.0)


def test_roll_moves_the_price_with_size_and_equity() -> None:
    rate, _ = maintenance_terms("SOL", 1_000.0)
    cross = account_from_snapshot("SOL", 10.0, 1_000.0, 92.0, 1_000.0)
    iso = account_from_snapshot("SOL", 10.0, 1_000.0, 92.0, 1_000.0, isolated=True, leverage=10.0)
    accounts: dict[str, Account] = {"c": cross, "i": iso}
    events = pl.DataFrame(
        {"wallet": ["c", "i", "c", "i", "z"], "start_pos": [10.0, 10.0, 20.0, 20.0, 0.0], "delta": [10.0, 10.0, -10.0, -10.0, 1.0],
         "px": [100.0, 100.0, 100.0, 100.0, 100.0]}
    ).to_pandas()  # fmt: skip
    out = roll_accounts("SOL", events, accounts)
    # cross doubles on the same equity: the price moves toward the mark; back to 10 it returns
    assert 92.0 < out[0] < 100.0 and out[2] == pytest.approx(92.0)
    # isolated doubles with its own margin (notional / leverage): its price moves less
    assert 92.0 < out[1] < out[0]
    assert math.isnan(out[4])
    # an isolated reduce keeps the price: margin shrinks with the size
    assert out[3] == pytest.approx(out[1]) and rate > 0
