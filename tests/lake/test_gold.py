"""Tests for pure Hyperliquid Gold markout assembly."""

from __future__ import annotations

import pytest

from marketimmune.labels.markout import MarkoutConfig
from marketimmune.lake.gold import (
    book_mid_series,
    build_markout_gold_rows,
    build_markout_gold_rows_from_mids,
    horizon_key,
)
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot, L2Level
from marketimmune.sources.hyperliquid_node_fills import pair_fill_legs, parse_fill_row


def _book(ts_ms: int, bid: float, ask: float) -> BookSnapshot:
    return BookSnapshot(
        ts_ms=ts_ms,
        coin="BTC",
        bids=(L2Level(px=bid, sz=2.0, n=1),),
        asks=(L2Level(px=ask, sz=2.0, n=1),),
    )


def test_horizon_key() -> None:
    assert horizon_key(10.0) == "10s"
    assert horizon_key(0.5) == "0.5s"


def test_book_mid_series_sorts_by_time() -> None:
    series = book_mid_series([
        _book(2_000, 101.0, 103.0),
        _book(1_000, 99.0, 101.0),
    ])
    assert series == ((1.0, 100.0), (2.0, 102.0))


def test_build_markout_gold_rows() -> None:
    fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": False,
        "time": 1_000,
        "oid": 1,
        "tid": 2,
    })
    rows = build_markout_gold_rows(
        [fill],
        [_book(1_000, 99.0, 101.0), _book(2_000, 98.0, 100.0)],
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0, reference="fill_px"),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.markout_bps["1s"] == pytest.approx(-100.0)
    assert row.toxic["1s"] is True
    assert row.to_dict()["tid"] == 2


def test_build_markout_gold_rows_flips_taker_to_maker_side() -> None:
    fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": True,
        "time": 1_000,
    })
    rows = build_markout_gold_rows(
        [fill],
        [_book(2_000, 100.0, 102.0)],
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0, reference="fill_px"),
    )
    assert rows[0].maker_side == -1
    assert rows[0].markout_bps["1s"] == pytest.approx(-100.0)


def test_build_markout_gold_rows_filters_coin_and_skips_missing_future() -> None:
    btc_fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": False,
        "time": 1_000,
    })
    eth_fill = parse_fill_row({
        "coin": "ETH",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": False,
        "time": 10_000,
    })
    rows = build_markout_gold_rows(
        [btc_fill, eth_fill],
        [_book(2_000, 100.0, 102.0)],
        MarkoutConfig(horizons_s=(1.0, 10.0), fee_bps=1.0, reference="fill_px"),
        coin="BTC",
    )
    assert len(rows) == 1
    assert rows[0].coin == "BTC"
    assert set(rows[0].markout_bps) == {"1s"}


def test_build_markout_gold_rows_skips_fill_with_no_available_horizon() -> None:
    fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": False,
        "time": 10_000,
    })
    rows = build_markout_gold_rows(
        [fill],
        [_book(2_000, 100.0, 102.0)],
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0, reference="fill_px"),
    )
    assert rows == []


def test_build_markout_gold_rows_empty_books() -> None:
    fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "1.0",
        "side": "B",
        "crossed": False,
        "time": 1_000,
    })
    assert build_markout_gold_rows([fill], []) == []


def test_pre_fill_mid_label_ignores_snapshot_in_fill_millisecond() -> None:
    # Fix L2: the anchor is the last mid strictly before the fill. The snapshot at
    # 1_000 may already show the fill, so the 999 mid (100) is the reference.
    fill = parse_fill_row({
        "coin": "BTC", "px": "99.5", "sz": "1.0", "side": "B",
        "crossed": False, "time": 1_000, "tid": 7,
    })
    books = [_book(999, 99.0, 101.0), _book(1_000, 103.0, 105.0), _book(2_000, 100.0, 102.0)]
    rows = build_markout_gold_rows([fill], books, MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0))
    assert len(rows) == 1
    row = rows[0]
    assert row.mid_before == pytest.approx(100.0)
    assert row.markout_bps["1s"] == pytest.approx(100.0)  # (101 - 100) / 100
    assert row.markout_px_bps["1s"] == pytest.approx((101.0 - 99.5) / 99.5 * 1e4)
    assert row.toxic["1s"] is False


def test_pre_fill_mid_label_skips_fill_without_prior_mid() -> None:
    fill = parse_fill_row({
        "coin": "BTC", "px": "100.0", "sz": "1.0", "side": "B", "crossed": False, "time": 1_000,
    })
    books = [_book(1_000, 99.0, 101.0), _book(2_000, 98.0, 100.0)]
    assert build_markout_gold_rows([fill], books, MarkoutConfig(horizons_s=(1.0,))) == []


def test_match_fill_labels_once_and_carries_wallets_and_fees() -> None:
    # Fix B2/B1/L3: two legs of one match give one Gold row with both wallets.
    legs = [
        parse_fill_row({
            "coin": "BTC", "px": "100.0", "sz": "2.0", "side": "A", "crossed": True,
            "time": 1_000, "tid": 9, "oid": 11, "fee": "0.009", "user": "0xtaker",
            "startPosition": "1.0", "priorityGas": "3",
        }),
        parse_fill_row({
            "coin": "BTC", "px": "100.0", "sz": "2.0", "side": "B", "crossed": False,
            "time": 1_000, "tid": 9, "oid": 12, "fee": "-0.002", "user": "0xmaker",
            "startPosition": "-4.0",
        }),
    ]
    books = [_book(900, 99.0, 101.0), _book(2_000, 98.0, 100.0)]
    leg_rows = build_markout_gold_rows(legs, books, MarkoutConfig(horizons_s=(1.0,)))
    assert len(leg_rows) == 2  # the v2 double count this fix removes
    rows = build_markout_gold_rows(pair_fill_legs(legs), books, MarkoutConfig(horizons_s=(1.0,)))
    assert len(rows) == 1
    row = rows[0]
    assert row.maker_side == 1 and row.side == "A" and row.crossed is True
    assert (row.maker_user, row.taker_user) == ("0xmaker", "0xtaker")
    assert row.maker_fee_bps == pytest.approx(-0.002 / 200.0 * 1e4)
    assert row.taker_fee_bps == pytest.approx(0.009 / 200.0 * 1e4)
    assert row.priority_gas == pytest.approx(3.0)
    assert row.markout_bps["1s"] == pytest.approx(-100.0)


def test_gold_rows_from_mid_arrays_match_snapshot_path() -> None:
    fill = parse_fill_row({
        "coin": "BTC", "px": "99.5", "sz": "1.0", "side": "B", "crossed": False, "time": 1_000,
    })
    books = [_book(999, 99.0, 101.0), _book(2_000, 100.0, 102.0)]
    config = MarkoutConfig(horizons_s=(1.0,))
    via_books = build_markout_gold_rows([fill], books, config)
    via_mids = build_markout_gold_rows_from_mids([fill], [0.999, 2.0], [100.0, 101.0], config)
    assert via_mids == via_books
    assert build_markout_gold_rows_from_mids([fill], [], [], config) == []
    with pytest.raises(ValueError, match="same length"):
        build_markout_gold_rows_from_mids([fill], [1.0], [], config)
    with pytest.raises(ValueError, match="sorted"):
        build_markout_gold_rows_from_mids([fill], [2.0, 1.0], [1.0, 1.0], config)
    with pytest.raises(ValueError, match="unknown markout reference"):
        build_markout_gold_rows_from_mids(
            [fill], [0.5, 2.0], [1.0, 1.0], MarkoutConfig(reference="bogus")  # type: ignore[arg-type]
        )
