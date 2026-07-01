"""Tests for pure Hyperliquid Gold markout assembly."""

from __future__ import annotations

import pytest

from marketimmune.ingest.hyperliquid_archive import BookSnapshot, L2Level
from marketimmune.ingest.hyperliquid_fills import parse_fill_row
from marketimmune.ingest.hyperliquid_gold import (
    book_mid_series,
    build_markout_gold_rows,
    horizon_key,
)
from marketimmune.labels.markout import MarkoutConfig


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
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
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
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
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
        MarkoutConfig(horizons_s=(1.0, 10.0), fee_bps=1.0),
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
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
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
