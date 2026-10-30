"""Tests for the Albers L4 book rebuild (statuses for time, diffs for what rested)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from marketimmune.ingest.albers import (
    STATUS_DTYPE,
    STATUS_LABELS,
    TIF_LABELS,
    AlbersBook,
    albers_trades_to_matches,
    decode_fixed,
    fixed_to_ticks,
    iso_to_ns,
    match_from_albers_trade,
    read_status_records,
    read_users_csv,
    rested_orders,
)
from marketimmune.ingest.hyperliquid_fills import MatchFill


def enc(value: float, decimals: int = 2) -> int:
    return (decimals << 29) | round(value * 10**decimals)


def status_records(events: list[dict[str, Any]]) -> np.ndarray:
    out = np.zeros(len(events), dtype=STATUS_DTYPE)
    for i, e in enumerate(events):
        out[i]["ts"] = e["ts"]
        out[i]["statusId"] = STATUS_LABELS.index(e["status"])
        out[i]["isAsk"] = e.get("ask", False)
        out[i]["limitPx"] = enc(e.get("px", 0.0))
        out[i]["sz"] = enc(e.get("sz", 0.0))
        out[i]["origSz"] = enc(e.get("sz", 0.0))
        out[i]["oid"] = e["oid"]
        out[i]["tifId"] = TIF_LABELS.index(e.get("tif", "Alo"))
        out[i]["isTrigger"] = e.get("trigger", False)
        out[i]["userId"] = e.get("user", 0)
    return out


def test_fixed_point_decoding() -> None:
    assert decode_fixed([enc(133.2)])[0] == pytest.approx(133.2)
    assert decode_fixed([enc(0.125, 3)])[0] == pytest.approx(0.125)
    assert fixed_to_ticks([enc(133.2), enc(133.20, 3)]).tolist() == [1_332_000_000] * 2


def test_read_status_records_checks_length() -> None:
    raw = status_records([{"ts": 1, "status": "open", "oid": 1}]).tobytes()
    assert read_status_records(raw)["oid"][0] == 1
    with pytest.raises(ValueError, match="54-byte"):
        read_status_records(raw + b"x")


def test_rested_orders_keeps_new_diffs_of_the_coin() -> None:
    def line(oid: int, coin: str, diff: object) -> str:
        return json.dumps({"oid": oid, "coin": coin, "side": "B", "px": "1", "raw_book_diff": diff})

    lines = [
        line(1, "SOL", {"new": {"sz": "2.5"}}),
        line(1, "SOL", "remove"),
        line(2, "BTC", {"new": {"sz": "9"}}),
        line(3, "SOL", {"update": {"origSz": "1", "newSz": "0.5"}}),
        line(4, "SOLX", {"new": {"sz": "1"}}),
    ]
    assert rested_orders(lines, "sol") == {1: 2.5}


S = 1_000_000_000  # one second in ns


def test_replay_hour_rests_only_diffed_orders_and_defers_triggers() -> None:
    records = status_records([
        # block 1: a two-sided book; a marketable GTC logs ``open`` but never rests;
        # a stop logs ``open`` while it waits off-book.
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        {"ts": 1 * S, "status": "open", "oid": 3, "px": 101.00, "sz": 1.0, "tif": "Gtc"},
        {"ts": 1 * S, "status": "open", "oid": 4, "px": 99.00, "sz": 0.5, "ask": True,
         "tif": "null", "trigger": True},
        # block 2: partial fill of the ask, the only bid cancels -> one-sided
        {"ts": 2 * S, "status": "filled", "oid": 2, "px": 100.01, "sz": 1.0, "ask": True},
        {"ts": 2 * S, "status": "canceled", "oid": 1, "px": 100.00, "sz": 2.0},
        # block 3: a new bid; the stop triggers and rests as an ask at 100.02
        {"ts": 3 * S, "status": "open", "oid": 5, "px": 100.00, "sz": 1.0},
        {"ts": 3 * S, "status": "triggered", "oid": 4, "px": 100.02, "sz": 0.5, "ask": True},
        # block 4: the rest of the 100.01 ask fills; a liquidation fill is counted
        {"ts": 4 * S, "status": "filled", "oid": 2, "px": 100.01, "sz": 0.0, "ask": True},
        {"ts": 4 * S, "status": "filled", "oid": 9, "px": 100.01, "sz": 0.0,
         "tif": "LiquidationMarket"},
        # block 5: nothing that changes the top -> no row
        {"ts": 5 * S, "status": "canceled", "oid": 77},
    ])
    rested = {1: 2.0, 2: 3.0, 4: 0.5, 5: 1.0}
    book = AlbersBook("sol")
    rows, stats = book.replay_hour(records, rested)

    assert [r["ts_ns"] for r in rows] == [1 * S, 3 * S, 4 * S]
    first, third = rows[0], rows[2]
    assert (first["bid_px"], first["ask_px"], first["ask_sz"]) == (100.0, 100.01, 3.0)
    assert first["mid"] == pytest.approx(100.005) and first["ts_ms"] == 1_000
    assert first["bid_px_2"] is None
    assert rows[1]["ask_sz"] == pytest.approx(1.0) and rows[1]["ask_px_2"] == pytest.approx(100.02)
    assert (third["bid_px"], third["ask_px"], third["ask_sz"]) == (100.0, 100.02, 0.5)
    assert stats.opens_rested == 3 and stats.opens_not_resting == 1
    assert stats.trigger_opens_deferred == 1 and stats.triggers_rested == 1
    assert stats.resting_fills == 2 and stats.fills_at_touch == 2
    assert stats.liquidation_fills == 1
    assert stats.one_sided_blocks == 1 and stats.crossed_blocks == 0
    assert stats.blocks == 5 and stats.rows == 3 and stats.resting_orders_end == 2
    summary = stats.to_dict()
    assert summary["fill_at_touch_share"] == 1.0 and summary["crossed_share"] == 0.0


def test_book_levels_aggregate_and_reopen() -> None:
    book = AlbersBook("SOL", depth=2)
    book.add(1, False, 100, 1.0)
    book.add(2, False, 100, 2.0)
    book.add(3, False, 90, 1.0)
    book.add(1, False, 95, 1.5)  # same oid re-added: moves, never double-counts
    assert book.bids.top(2, descending=True) == ((100, 2.0, 1), (95, 1.5, 1))
    book.set_size(2, 0.5)
    book.remove(2)
    book.remove(42)
    assert book.best() == (95, None)
    empty_rows, empty_stats = book.replay_hour(np.zeros(0, dtype=STATUS_DTYPE), {})
    assert empty_rows == [] and empty_stats.blocks == 0
    assert empty_stats.to_dict()["fill_at_touch_share"] is None


def test_replay_hour_records_liquidations_and_lost_races() -> None:
    records = status_records([
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        # block 2: the ask is cancelled before an IOC buy at 100.01 runs -> lost race;
        # a passive IOC buy at 99.00 never could have filled; a forced sell fills.
        {"ts": 2 * S, "status": "canceled", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        {"ts": 2 * S, "status": "iocCancelRejected", "oid": 3, "px": 100.01, "sz": 1.0,
         "tif": "Ioc", "user": 7},
        {"ts": 2 * S, "status": "iocCancelRejected", "oid": 4, "px": 99.00, "sz": 1.0,
         "tif": "Ioc"},
        {"ts": 2 * S, "status": "filled", "oid": 5, "px": 90.00, "sz": 0.0, "ask": True,
         "tif": "LiquidationMarket", "user": 9},
    ])
    events: list[dict[str, Any]] = []
    _rows, stats = AlbersBook("SOL").replay_hour(records, {1: 2.0, 2: 3.0}, None, events)
    kinds = [(e["kind"], e["oid"], e["marketable_at_block_start"]) for e in events]
    assert kinds == [("ioc_unfilled", 3, True), ("ioc_unfilled", 4, False),
                     ("liquidation", 5, True)]
    assert events[0]["opposite_best_px"] == pytest.approx(100.01) and events[0]["user_id"] == 7
    assert events[2]["opposite_best_px"] == pytest.approx(100.0)
    assert events[2]["tif"] == "LiquidationMarket"
    assert stats.ioc_unfilled == 2 and stats.ioc_unfilled_marketable == 1


def test_read_users_csv() -> None:
    assert read_users_csv(["0xabc,0\n", "0xdef,3\n", "\n"]) == {0: "0xabc", 3: "0xdef"}


def test_iso_to_ns() -> None:
    assert iso_to_ns("2025-12-01T00:00:01.388469225") == 1_764_547_201_388_469_225
    assert iso_to_ns("2025-12-01T00:00:01.5Z") == 1_764_547_201_500_000_000
    assert iso_to_ns("2025-12-01T00:00:01") == 1_764_547_201_000_000_000


TRADE = {
    "coin": "SOL", "side": "A", "time": "2025-12-01T00:00:01.388469225", "px": "133.41",
    "sz": "0.23", "hash": "0x12",
    "side_info": [
        {"user": "0xbuyer", "start_pos": "58.48", "oid": 11, "twap_id": None, "cloid": None},
        {"user": "0xseller", "start_pos": "-1.5", "oid": 12, "twap_id": None, "cloid": None},
    ],
}


def test_match_from_albers_trade_orients_by_aggressor() -> None:
    m = match_from_albers_trade(TRADE, {12})
    # side A: the seller crossed, so the buyer is the maker (maker bought: +1)
    assert (m.taker_user, m.maker_user, m.taker_oid, m.maker_oid) == ("0xseller", "0xbuyer", 12, 11)
    assert m.maker_side == 1 and m.taker_start_position == -1.5 and m.liquidation is True
    assert m.ts_ms == 1_764_547_201_388 and m.maker_fee is None
    buy = match_from_albers_trade({**TRADE, "side": "B"})
    assert (buy.taker_user, buy.maker_side, buy.liquidation) == ("0xbuyer", -1, False)
    assert MatchFill.from_record(m.to_dict()) == m


def test_albers_trades_to_matches_filters_coin() -> None:
    lines = [json.dumps({**TRADE, "coin": c}) for c in ("SOL", "SOLX", "BTC")]
    assert len(albers_trades_to_matches(lines, "sol")) == 1
