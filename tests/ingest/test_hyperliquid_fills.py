"""Tests for Hyperliquid fill parsing and maker-side conversion."""

from __future__ import annotations

import json

import pytest

from marketimmune.ingest.hyperliquid_fills import (
    HyperliquidNodeFills,
    iter_fill_mappings,
    node_fills_by_block_key,
    normalize_side,
    parse_fill_row,
    parse_node_fills_json,
    side_sign,
)

SAMPLE_FILL = {
    "closedPnl": "0.0",
    "coin": "AVAX",
    "crossed": False,
    "dir": "Open Long",
    "hash": "0xabc",
    "oid": 90542681,
    "px": "18.435",
    "side": "B",
    "startPosition": "26.86",
    "sz": "93.53",
    "time": 1681222254710,
    "fee": "0.01",
    "feeToken": "USDC",
    "builderFee": "0.002",
    "tid": 118906512037719,
}


def test_node_fills_by_block_key() -> None:
    assert node_fills_by_block_key() == "node_fills_by_block"
    assert node_fills_by_block_key("/2026/01/01/") == "node_fills_by_block/2026/01/01"


def test_normalize_side_and_sign() -> None:
    assert normalize_side("buy") == "B"
    assert normalize_side("ASK") == "A"
    assert side_sign("B") == 1
    assert side_sign("sell") == -1


def test_normalize_side_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown Hyperliquid fill side"):
        normalize_side("middle")


def test_parse_fill_row_documented_shape() -> None:
    fill = parse_fill_row(SAMPLE_FILL)
    assert fill.coin == "AVAX"
    assert fill.ts_ms == 1681222254710
    assert fill.px == pytest.approx(18.435)
    assert fill.sz == pytest.approx(93.53)
    assert fill.side == "B"
    assert fill.crossed is False
    assert fill.maker_side == 1
    assert fill.to_maker_fill().side == 1
    assert fill.fee_bps == pytest.approx(0.01 / (18.435 * 93.53) * 10_000.0)
    assert fill.to_dict()["maker_side"] == 1


def test_parse_crossed_taker_flips_to_maker_side() -> None:
    fill = parse_fill_row({**SAMPLE_FILL, "side": "B", "crossed": True})
    assert fill.user_side_sign == 1
    assert fill.maker_side == -1


def test_parse_crossed_string_booleans() -> None:
    true_fill = parse_fill_row({**SAMPLE_FILL, "crossed": "yes"})
    false_fill = parse_fill_row({**SAMPLE_FILL, "crossed": "0"})
    assert true_fill.crossed is True
    assert false_fill.crossed is False


def test_parse_sell_maker_side_and_missing_optional_fields() -> None:
    fill = parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "2.0",
        "side": "A",
        "time": 10,
    })
    assert fill.crossed is None
    assert fill.maker_side == -1
    assert fill.fee_bps is None


def test_parse_fill_envelope() -> None:
    fill = parse_fill_row({"fill": SAMPLE_FILL})
    assert fill.trade_hash == "0xabc"


def test_bad_bool_rejected() -> None:
    with pytest.raises(ValueError, match="unknown boolean"):
        parse_fill_row({**SAMPLE_FILL, "crossed": "maybe"})


def test_iter_fill_mappings_handles_nested_shapes() -> None:
    payload = {
        "block": 123,
        "fills": [
            {"fill": SAMPLE_FILL},
            {**SAMPLE_FILL, "tid": 2},
        ],
    }
    rows = list(iter_fill_mappings(payload))
    assert len(rows) == 2
    assert rows[0]["coin"] == "AVAX"


def test_iter_fill_mappings_handles_hourly_block_events() -> None:
    payload = {
        "local_time": "2025-07-27T08:50:01.519266138",
        "block_number": 676607012,
        "events": [["0xabc", SAMPLE_FILL]],
    }
    rows = list(iter_fill_mappings(payload))
    assert rows == [{**SAMPLE_FILL, "user": "0xabc"}]


def test_iter_fill_mappings_ignores_non_fill_objects() -> None:
    assert list(iter_fill_mappings({"block": 1, "events": []})) == []
    assert list(iter_fill_mappings({"block": 1})) == []
    assert list(iter_fill_mappings("not json object")) == []


def test_parse_node_fills_json_array() -> None:
    fills = parse_node_fills_json(json.dumps([SAMPLE_FILL, {"fill": SAMPLE_FILL}]))
    assert len(fills) == 2


def test_parse_node_fills_json_ndjson() -> None:
    text = "\n".join([
        json.dumps({"fills": [SAMPLE_FILL]}),
        "",
        json.dumps({"userFills": [{**SAMPLE_FILL, "tid": 2}]}),
    ])
    fills = parse_node_fills_json(text)
    assert [fill.tid for fill in fills] == [118906512037719, 2]


def test_parse_node_fills_json_empty() -> None:
    assert parse_node_fills_json(" \n ") == []


def test_loader_uses_injected_io() -> None:
    captured: dict[str, str] = {}

    def fake_fetch(key: str) -> bytes:
        captured["key"] = key
        return json.dumps({"nodeFills": [SAMPLE_FILL]}).encode("utf-8")

    loader = HyperliquidNodeFills(fetch=fake_fetch, decompress=lambda raw: raw)
    fills = loader.load_by_block_suffix("part-000.json.lz4")
    assert captured["key"] == "node_fills_by_block/part-000.json.lz4"
    assert len(fills) == 1
