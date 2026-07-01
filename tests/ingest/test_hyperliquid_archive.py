"""Tests for Hyperliquid archive parsing — pure, no network (100% branch coverage)."""

import json

import pytest

from marketimmune.ingest.hyperliquid_archive import (
    BookSnapshot,
    HyperliquidArchive,
    L2Level,
    asset_ctxs_key,
    l2_book_key,
    parse_book_snapshot,
    parse_l2_book_ndjson,
    parse_level,
)

SAMPLE = {
    "coin": "BTC",
    "time": 1694856600000,
    "levels": [
        [{"px": "100.0", "sz": "2.0", "n": 3}, {"px": "99.0", "sz": "1.0", "n": 1}],
        [{"px": "101.0", "sz": "1.0", "n": 2}, {"px": "102.0", "sz": "5.0", "n": 4}],
    ],
}


def test_key_builders() -> None:
    assert l2_book_key("SOL", "20230916", 9) == "market_data/20230916/9/l2Book/SOL.lz4"
    assert asset_ctxs_key("20230916") == "asset_ctxs/20230916.csv.lz4"


def test_parse_level() -> None:
    assert parse_level({"px": "100.5", "sz": "2.5", "n": 7}) == L2Level(px=100.5, sz=2.5, n=7)


def test_parse_snapshot_plain_and_enveloped() -> None:
    snap = parse_book_snapshot(SAMPLE)
    assert snap.coin == "BTC"
    assert snap.ts_ms == 1694856600000
    assert snap.bids[0].px == 100.0
    assert snap.asks[0].px == 101.0
    # The same record wrapped in the WS channel/data envelope parses identically.
    assert parse_book_snapshot({"channel": "l2Book", "data": SAMPLE}) == snap
    # The requester-pays S3 archive wraps the WS envelope under "raw".
    archive_row = {
        "time": "2023-09-16T09:00:01.039593170",
        "ver_num": 1,
        "raw": {"channel": "l2Book", "data": SAMPLE},
    }
    assert parse_book_snapshot(archive_row) == snap


def test_features() -> None:
    feats = parse_book_snapshot(SAMPLE).features()
    assert feats["mid"] == pytest.approx(100.5)
    assert feats["spread_bps"] == pytest.approx((101.0 - 100.0) / 100.5 * 10_000.0)
    # microprice = (bb*ask_sz + ba*bid_sz) / (bid_sz + ask_sz) = (100*1 + 101*2) / 3
    assert feats["microprice"] == pytest.approx((100.0 * 1.0 + 101.0 * 2.0) / 3.0)
    assert feats["top_imbalance"] == pytest.approx((2.0 - 1.0) / 3.0)


def test_features_empty_side_raises() -> None:
    snap = BookSnapshot(ts_ms=0, coin="BTC", bids=(), asks=(L2Level(1.0, 1.0, 1),))
    with pytest.raises(ValueError, match="empty side"):
        snap.features()


def test_features_zero_size_raises() -> None:
    snap = BookSnapshot(
        ts_ms=0,
        coin="BTC",
        bids=(L2Level(100.0, 0.0, 1),),
        asks=(L2Level(101.0, 0.0, 1),),
    )
    with pytest.raises(ValueError, match="size is zero"):
        snap.features()


def test_parse_ndjson_skips_blank_lines() -> None:
    text = json.dumps(SAMPLE) + "\n\n" + json.dumps(SAMPLE) + "\n"
    assert len(parse_l2_book_ndjson(text)) == 2


def test_archive_load_l2_book_with_injected_io() -> None:
    payload = (json.dumps(SAMPLE) + "\n").encode("utf-8")
    captured: dict[str, str] = {}

    def fake_fetch(key: str) -> bytes:
        captured["key"] = key
        return payload

    archive = HyperliquidArchive(fetch=fake_fetch, decompress=lambda raw: raw)
    snaps = archive.load_l2_book("BTC", "20230916", 9)
    assert captured["key"] == "market_data/20230916/9/l2Book/BTC.lz4"
    assert len(snaps) == 1
    assert snaps[0].coin == "BTC"
