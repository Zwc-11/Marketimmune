from __future__ import annotations

import json

import pytest

from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot, L2Level, l2_book_key, parse_l2_book_ndjson

BOOK = {
    "coin": "BTC",
    "time": 1694856600000,
    "levels": [
        [{"px": "100.0", "sz": "2.0", "n": 3}, {"px": "99.0", "sz": "1.0", "n": 1}],
        [{"px": "101.0", "sz": "1.0", "n": 2}, {"px": "102.0", "sz": "5.0", "n": 4}],
    ],
}


def archive_line(book: dict[str, object]) -> str:
    """One l2Book line as the requester-pays archive stores it."""
    return json.dumps({"time": "2023-09-16T09:00:01.039593170", "ver_num": 1, "raw": {"channel": "l2Book", "data": book}})


def test_l2_book_key() -> None:
    assert l2_book_key("SOL", "20230916", 9) == "market_data/20230916/9/l2Book/SOL.lz4"


def test_parse_archive_lines() -> None:
    snaps = parse_l2_book_ndjson(archive_line(BOOK) + "\n" + archive_line(BOOK | {"time": 1694856601000}) + "\n")
    assert [s.ts_ms for s in snaps] == [1694856600000, 1694856601000]
    assert snaps[0] == BookSnapshot(
        ts_ms=1694856600000,
        coin="BTC",
        bids=(L2Level(100.0, 2.0, 3), L2Level(99.0, 1.0, 1)),
        asks=(L2Level(101.0, 1.0, 2), L2Level(102.0, 5.0, 4)),
    )


def test_features() -> None:
    feats = parse_l2_book_ndjson(archive_line(BOOK))[0].features()
    assert feats["mid"] == pytest.approx(100.5)
    assert feats["spread_bps"] == pytest.approx((101.0 - 100.0) / 100.5 * 10_000.0)
    # microprice = (bb*ask_sz + ba*bid_sz) / (bid_sz + ask_sz) = (100*1 + 101*2) / 3
    assert feats["microprice"] == pytest.approx((100.0 * 1.0 + 101.0 * 2.0) / 3.0)
    assert feats["top_imbalance"] == pytest.approx((2.0 - 1.0) / 3.0)


def test_features_reject_empty_side_and_zero_size() -> None:
    with pytest.raises(AssertionError, match="empty side"):
        BookSnapshot(ts_ms=0, coin="BTC", bids=(), asks=(L2Level(1.0, 1.0, 1),)).features()
    with pytest.raises(AssertionError, match="size is zero"):
        BookSnapshot(ts_ms=0, coin="BTC", bids=(L2Level(100.0, 0.0, 1),), asks=(L2Level(101.0, 0.0, 1),)).features()
