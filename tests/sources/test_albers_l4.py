"""Tests for the Albers L4 book rebuild (statuses for time, diffs for what rested)."""

from __future__ import annotations

import gzip
import json
from typing import Any

import numpy as np
import pytest

from marketimmune.sources.albers_l4 import (
    MBO_ADD,
    MBO_CANCEL,
    MBO_FILL,
    MBO_SCHEMA,
    STATUS_DTYPE,
    STATUS_LABELS,
    TIF_LABELS,
    AlbersBook,
    ReplayStats,
    Rested,
    albers_trades_member_to_matches,
    decode_fixed,
    drop_replayed,
    fixed_to_ticks,
    iso_to_ns,
    l2_table,
    match_from_albers_trade,
    mbo_table,
    merge_rested,
    read_status_records,
    read_users_csv,
    rested_orders_gz,
)
from marketimmune.sources.hyperliquid_node_fills import MatchFill

S = 1_000_000_000  # one second in ns


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


def rested(sizes: dict[int, float]) -> Rested:
    return merge_rested((np.array(list(sizes), dtype=np.uint64), np.array(list(sizes.values()))))


def replay(
    book: AlbersBook, events: list[dict[str, Any]], sizes: dict[int, float]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], ReplayStats]:
    stats = ReplayStats()
    rows, order_events = book.replay_hour(status_records(events), rested(sizes), stats)
    return l2_table(rows).to_pylist(), order_events.to_pylist(), stats


def test_fixed_point_decoding() -> None:
    assert decode_fixed([enc(133.2)])[0] == pytest.approx(133.2)
    assert decode_fixed([enc(0.125, 3)])[0] == pytest.approx(0.125)
    assert fixed_to_ticks([enc(133.2), enc(133.20, 3)]).tolist() == [1_332_000_000] * 2


def test_read_status_records_checks_length() -> None:
    raw = status_records([{"ts": 1, "status": "open", "oid": 1}]).tobytes()
    assert read_status_records(raw)["oid"][0] == 1
    with pytest.raises(AssertionError, match="54-byte"):
        read_status_records(raw + b"x")


def _diff_line(oid: int, coin: str, diff: object) -> str:
    return json.dumps({"user": "0xabc", "oid": oid, "coin": coin, "side": "B", "px": "1.5", "raw_book_diff": diff}, separators=(",", ":"))


def test_rested_orders_gz_keeps_new_diffs_of_the_coin() -> None:
    lines = [
        _diff_line(1, "SOL", {"new": {"sz": "2.5"}}),
        _diff_line(1, "SOL", "remove"),
        _diff_line(2, "BTC", {"new": {"sz": "9"}}),
        _diff_line(3, "SOL", {"update": {"origSz": "1", "newSz": "0.5"}}),
        _diff_line(4, "SOLX", {"new": {"sz": "1"}}),
        _diff_line(5, "SOL", {"new": {"sz": "0.25"}}),
        _diff_line(1, "SOL", {"new": {"sz": "3"}}),
    ]
    oids, sizes = rested_orders_gz(gzip.compress(("\n".join(lines) + "\n").encode()), "sol")
    assert oids.tolist() == [1, 5, 1] and sizes.tolist() == [2.5, 0.25, 3.0]
    keys, merged = merge_rested((oids, sizes), (np.array([5], dtype=np.uint64), np.array([7.0])))
    assert keys.tolist() == [1, 5] and merged.tolist() == [3.0, 7.0]  # the later line, then the later part, wins
    empty = rested_orders_gz(gzip.compress(b""), "SOL")
    assert empty[0].dtype == np.uint64 and empty[0].size == 0


def test_rested_orders_gz_asserts_the_key_order() -> None:
    reordered = json.dumps({"coin": "SOL", "oid": 7, "side": "A", "px": "2", "raw_book_diff": {"new": {"sz": "3"}}}, separators=(",", ":"))
    with pytest.raises(AssertionError, match="key order"):
        rested_orders_gz(gzip.compress((reordered + "\n").encode()), "SOL")


def test_replay_hour_rests_only_diffed_orders_and_defers_triggers() -> None:
    events = [
        # block 1: a two-sided book; a marketable GTC logs ``open`` but never rests;
        # a stop logs ``open`` while it waits off-book.
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        {"ts": 1 * S, "status": "open", "oid": 3, "px": 101.00, "sz": 1.0, "tif": "Gtc"},
        {"ts": 1 * S, "status": "open", "oid": 4, "px": 99.00, "sz": 0.5, "ask": True, "tif": "null", "trigger": True},
        # block 2: partial fill of the ask, the only bid cancels -> one-sided
        {"ts": 2 * S, "status": "filled", "oid": 2, "px": 100.01, "sz": 1.0, "ask": True},
        {"ts": 2 * S, "status": "canceled", "oid": 1, "px": 100.00, "sz": 2.0},
        # block 3: a new bid; the stop triggers and rests as an ask at 100.02
        {"ts": 3 * S, "status": "open", "oid": 5, "px": 100.00, "sz": 1.0},
        {"ts": 3 * S, "status": "triggered", "oid": 4, "px": 100.02, "sz": 0.5, "ask": True},
        # block 4: the rest of the 100.01 ask fills; a liquidation fill is counted
        {"ts": 4 * S, "status": "filled", "oid": 2, "px": 100.01, "sz": 0.0, "ask": True},
        {"ts": 4 * S, "status": "filled", "oid": 9, "px": 100.01, "sz": 0.0, "tif": "LiquidationMarket"},
        # block 5: nothing that changes the top -> no row
        {"ts": 5 * S, "status": "canceled", "oid": 77},
    ]
    rows, _events, stats = replay(AlbersBook("sol", {0: "0xa"}), events, {1: 2.0, 2: 3.0, 4: 0.5, 5: 1.0})

    assert [r["ts_ns"] for r in rows] == [1 * S, 3 * S, 4 * S]
    first, third = rows[0], rows[2]
    assert (first["bid_px"], first["ask_px"], first["ask_sz"]) == (100.0, 100.01, 3.0)
    assert first["mid"] == pytest.approx(100.005) and first["ts_ms"] == 1_000
    assert first["bid_px_2"] is None and first["coin"] == "SOL"
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


def test_a_trigger_fired_through_the_book_trades_instead_of_resting() -> None:
    # 2025-12-19 04:11: a buy stop with limit 131.61 fired with the best ask at 121.86. Its
    # ``new`` diff exists from placement; resting it crossed the book for 28 hours.
    events = [
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        {"ts": 1 * S, "status": "open", "oid": 3, "px": 110.00, "sz": 1.0, "tif": "null", "trigger": True},
        {"ts": 1 * S, "status": "open", "oid": 4, "px": 99.00, "sz": 1.0, "tif": "null", "trigger": True},
        {"ts": 2 * S, "status": "triggered", "oid": 3, "px": 110.00, "sz": 1.0},
        {"ts": 3 * S, "status": "triggered", "oid": 4, "px": 99.00, "sz": 1.0},
    ]
    rows, _events, stats = replay(AlbersBook("sol", {0: "0xa"}), events, {1: 2.0, 2: 3.0, 3: 1.0, 4: 1.0})
    assert stats.triggers_marketable == 1 and stats.triggers_rested == 1 and stats.crossed_blocks == 0
    assert (rows[-1]["bid_px"], rows[-1]["bid_px_2"], rows[-1]["ask_px"]) == (100.0, 99.0, 100.01)


def test_drop_replayed_removes_the_archive_s_repeated_windows() -> None:
    def recs(ts_oid: list[tuple[int, int]]) -> np.ndarray:
        return status_records([{"ts": t * S, "status": "open", "oid": o} for t, o in ts_oid])

    clean = recs([(1, 1), (2, 2), (2, 3)])
    assert drop_replayed(clean, None) is clean and drop_replayed(clean, 1 * S) is clean
    # 2025-12-09 12:41:50 -> 12:39:44: the file jumps back and repeats a window, seam included
    replayed = recs([(1, 1), (2, 2), (3, 3), (2, 2), (3, 3), (4, 4)])
    assert drop_replayed(replayed, None)["oid"].tolist() == [1, 2, 3, 4]
    # the window repeated at the start of the next hour's file
    assert drop_replayed(recs([(2, 2), (3, 3), (5, 5)]), 3 * S)["oid"].tolist() == [3, 5]


def test_book_levels_aggregate_and_reopen() -> None:
    events = [
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.00},
        {"ts": 1 * S, "status": "open", "oid": 3, "px": 90.00},
        {"ts": 1 * S, "status": "open", "oid": 6, "px": 101.00, "ask": True},
        # block 2: oid 1 opens again at 95: it moves, never double-counts
        {"ts": 2 * S, "status": "open", "oid": 1, "px": 95.00},
        # block 3: oid 2 partly fills, then cancels; an unknown cancel is ignored
        {"ts": 3 * S, "status": "filled", "oid": 2, "px": 100.00, "sz": 0.5},
        {"ts": 3 * S, "status": "canceled", "oid": 2},
        {"ts": 3 * S, "status": "canceled", "oid": 42},
    ]
    book = AlbersBook("SOL", {})
    rows, _events, stats = replay(book, events, {1: 1.5, 2: 2.0, 3: 1.0, 6: 1.0})
    assert [(r["bid_px"], r["bid_sz"], r["bid_n"], r["bid_px_2"], r["bid_sz_2"]) for r in rows] == [
        (100.0, 3.5, 2, 90.0, 1.0),
        (100.0, 2.0, 1, 95.0, 1.5),
        (95.0, 1.5, 1, 90.0, 1.0),
    ]
    assert book.orders.keys() == {1, 3, 6} and stats.resting_fills == 1
    empty_rows, empty_events = book.replay_hour(np.zeros(0, dtype=STATUS_DTYPE), rested({}), stats)
    assert empty_rows == [] and empty_events.num_rows == 0 and stats.blocks == 3
    assert ReplayStats().to_dict()["fill_at_touch_share"] is None


def test_replay_hour_records_liquidations_and_lost_races() -> None:
    events = [
        {"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": 1 * S, "status": "open", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        # block 2: the ask is cancelled before an IOC buy at 100.01 runs -> lost race;
        # a passive IOC buy at 99.00 never could have filled; a forced sell fills.
        {"ts": 2 * S, "status": "canceled", "oid": 2, "px": 100.01, "sz": 3.0, "ask": True},
        {"ts": 2 * S, "status": "iocCancelRejected", "oid": 3, "px": 100.01, "sz": 1.0, "tif": "Ioc", "user": 7},
        {"ts": 2 * S, "status": "iocCancelRejected", "oid": 4, "px": 99.00, "sz": 1.0, "tif": "Ioc"},
        {"ts": 2 * S, "status": "filled", "oid": 5, "px": 90.00, "sz": 0.0, "ask": True, "tif": "LiquidationMarket", "user": 9},
    ]
    _rows, order_events, stats = replay(AlbersBook("SOL", {0: "0xa", 7: "0x7", 9: "0x9"}), events, {1: 2.0, 2: 3.0})
    kinds = [(e["kind"], e["oid"], e["marketable_at_block_start"]) for e in order_events]
    assert kinds == [("ioc_unfilled", 3, True), ("ioc_unfilled", 4, False), ("liquidation", 5, True)]
    assert order_events[0]["opposite_best_px"] == pytest.approx(100.01)
    assert (order_events[0]["user_id"], order_events[0]["user"], order_events[0]["ts_ms"]) == (7, "0x7", 2_000)
    assert order_events[2]["opposite_best_px"] == pytest.approx(100.0)
    assert order_events[2]["tif"] == "LiquidationMarket" and order_events[2]["limit_px"] == 90.0
    assert stats.ioc_unfilled == 2 and stats.ioc_unfilled_marketable == 1


def test_replay_hour_collects_near_touch_l4_events_when_asked() -> None:
    # bids at 100, 99, ..., 95: the sixth level (95) is below the top five
    opens = [{"ts": 1 * S, "status": "open", "oid": k, "px": 101.0 - k, "sz": 1.0} for k in range(1, 7)]
    events = [
        *opens,
        {"ts": 2 * S, "status": "open", "oid": 7, "px": 100.00, "sz": 2.0, "tif": "Gtc"},
        {"ts": 3 * S, "status": "filled", "oid": 1, "px": 100.00, "sz": 0.25},  # 0.75 filled, 0.25 left
        {"ts": 3 * S, "status": "filled", "oid": 1, "px": 100.00, "sz": 0.0},  # the rest
        {"ts": 3 * S, "status": "canceled", "oid": 6},  # deep: not recorded
        {"ts": 4 * S, "status": "canceled", "oid": 7},
    ]
    sizes = {k: 1.0 for k in range(1, 7)} | {7: 2.0}
    book = AlbersBook("SOL", {})
    replay(book, events, sizes)
    assert book.mbo is None  # off unless a list is set
    book.reset()
    book.mbo = []
    replay(book, events, sizes)
    got = [(t // S, kind, oid, ask, px / 1e7, sz, added // S, alo) for t, kind, oid, ask, px, sz, added, alo in book.mbo]
    assert got == [
        *((1, MBO_ADD, k, False, 101.0 - k, 1.0, 1, True) for k in range(1, 6)),
        (2, MBO_ADD, 7, False, 100.0, 2.0, 2, False),
        (3, MBO_FILL, 1, False, 100.0, 0.75, 1, True),
        (3, MBO_FILL, 1, False, 100.0, 0.25, 1, True),
        (4, MBO_CANCEL, 7, False, 100.0, 2.0, 2, False),
    ]
    table = mbo_table(book.mbo)
    assert table.schema == MBO_SCHEMA and table.num_rows == 9 and table["px_ticks"][0].as_py() == 100 * 10**7


def test_reset_forgets_every_order() -> None:
    book = AlbersBook("SOL", {})
    opens = [{"ts": 1 * S, "status": "open", "oid": 1, "px": 100.00}, {"ts": 1 * S, "status": "open", "oid": 2, "px": 101.00, "ask": True}]
    replay(book, opens, {1: 1.0, 2: 1.0})
    book.reset()
    assert book.orders == {} and book.bids.prices == [] and book.asks.prices == []
    rows, _events, _stats = replay(book, opens, {1: 1.0, 2: 1.0})
    assert len(rows) == 1  # the same top again is a new row after a reset


def test_read_users_csv() -> None:
    assert read_users_csv(["0xabc,0\n", "0xdef,3\n", "\n"]) == {0: "0xabc", 3: "0xdef"}


def test_iso_to_ns() -> None:
    assert iso_to_ns("2025-12-01T00:00:01.388469225") == 1_764_547_201_388_469_225
    assert iso_to_ns("2025-12-01T00:00:01.5Z") == 1_764_547_201_500_000_000
    assert iso_to_ns("2025-12-01T00:00:01") == 1_764_547_201_000_000_000


TRADE = {
    "coin": "SOL",
    "side": "A",
    "time": "2025-12-01T00:00:01.388469225",
    "px": "133.41",
    "sz": "0.23",
    "hash": "0x12",
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
    buy = match_from_albers_trade({**TRADE, "side": "B"}, set())
    assert (buy.taker_user, buy.maker_side, buy.liquidation) == ("0xbuyer", -1, False)
    assert MatchFill.from_record(m.to_dict()) == m


def test_albers_trades_member_to_matches_filters_coin() -> None:
    data = "\n".join(json.dumps({**TRADE, "coin": c}) for c in ("BTC", "SOLX", "SOL")).encode()
    (match,) = albers_trades_member_to_matches(data, "sol", set())
    assert match.coin == "SOL" and match.px == 133.41
