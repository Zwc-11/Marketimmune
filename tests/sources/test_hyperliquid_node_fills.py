from __future__ import annotations

import json

import pytest

from marketimmune.sources.hyperliquid_node_fills import MatchFill, node_fills_key, pair_fill_legs, parse_fill_row, parse_node_fills


def _leg(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "coin": "SOL",
        "px": "150.0",
        "sz": "4.0",
        "side": "B",
        "crossed": True,
        "time": 5_000,
        "tid": 77,
        "oid": 1,
        "hash": "0xh",
        "fee": "0.27",
        "feeToken": "USDC",
        "startPosition": "0.0",
        "dir": "Open Long",
        "closedPnl": "0.0",
    }
    row.update(overrides)
    return row


def _block(*events: tuple[str, dict[str, object]]) -> str:
    return json.dumps(
        {
            "local_time": "2025-07-27T08:50:01.519266138",
            "block_time": "2025-07-27T08:50:01.4",
            "block_number": 1,
            "events": [list(e) for e in events],
        }
    )


def test_node_fills_key() -> None:
    assert node_fills_key("20250727", 8) == "node_fills_by_block/hourly/20250727/8.lz4"


def test_parse_fill_row_promotes_raw_fields() -> None:
    fill = parse_fill_row(
        _leg(user="0xa", priorityGas="12", builderFee="0.002", liquidation={"liquidatedUser": "0xb", "markPx": "149.9", "method": "market"})
    )
    assert (fill.coin, fill.ts_ms, fill.px, fill.sz, fill.side, fill.crossed) == ("SOL", 5_000, 150.0, 4.0, "B", True)
    assert (fill.oid, fill.tid, fill.trade_hash, fill.fee, fill.fee_token, fill.direction) == (1, 77, "0xh", 0.27, "USDC", "Open Long")
    assert (fill.user, fill.start_position, fill.priority_gas, fill.builder_fee, fill.liquidation) == ("0xa", 0.0, 12.0, 0.002, True)
    assert fill.maker_side == -1  # the taker bought, so the maker sold
    assert fill.to_dict()["maker_side"] == -1 and fill.to_dict()["user"] == "0xa"
    plain = parse_fill_row({"coin": "BTC", "px": "100", "sz": "1", "side": "A", "crossed": False, "time": 1})
    assert plain.maker_side == -1 and plain.liquidation is False and plain.fee is None and plain.priority_gas is None
    with pytest.raises(AssertionError, match="side"):
        parse_fill_row(_leg(side="buy"))


def test_parse_node_fills_keeps_one_coin_and_names_the_user() -> None:
    text = "\n".join(
        [
            _block(("0xt", _leg()), ("0xm", _leg(side="A", crossed=False, oid=2))),
            _block(("0xe", _leg(coin="ETH"))),
            _block(("0xe", _leg(coin="ETH", tid=5)), ("0xs", _leg(tid=78, time=6_000))),
        ]
    )
    legs = parse_node_fills(text + "\n", "SOL")
    assert [(leg.user, leg.tid) for leg in legs] == [("0xt", 77), ("0xm", 77), ("0xs", 78)]
    assert legs[0].raw is not None and legs[0].raw["user"] == "0xt"
    assert parse_node_fills(text, "BTC") == []


def test_pair_fill_legs_merges_taker_and_maker() -> None:
    taker = parse_fill_row(_leg(user="0xa", priorityGas="5"))
    maker = parse_fill_row(_leg(side="A", crossed=False, oid=2, fee="-0.03", user="0xm", startPosition="10.0"))
    other_taker = parse_fill_row(_leg(tid=78, side="A", user="0xc"))
    other_maker = parse_fill_row(_leg(tid=78, side="B", crossed=False, user="0xd", liquidation={"method": "market"}))
    m, n = pair_fill_legs([taker, other_maker, maker, other_taker])
    assert isinstance(m, MatchFill) and (m.tid, n.tid) == (77, 78)
    assert (m.taker_user, m.maker_user, m.taker_oid, m.maker_oid) == ("0xa", "0xm", 1, 2)
    assert m.maker_side == -1 and m.side == "B" and m.crossed is True and m.oid == 1
    assert m.maker_fee_bps == pytest.approx(-0.03 / 600.0 * 1e4) and m.taker_fee_bps == pytest.approx(0.27 / 600.0 * 1e4)
    assert (m.maker_start_position, m.taker_start_position, m.priority_gas, m.n_legs) == (10.0, 0.0, 5.0, 2)
    assert n.maker_side == 1 and n.liquidation is True and m.liquidation is False


def test_pair_fill_legs_rejects_anything_but_one_taker_and_one_maker() -> None:
    with pytest.raises(AssertionError, match="1 legs"):
        pair_fill_legs([parse_fill_row(_leg())])
    with pytest.raises(AssertionError, match="disagree"):
        pair_fill_legs([parse_fill_row(_leg()), parse_fill_row(_leg(sz="5.0", crossed=False))])
    with pytest.raises(AssertionError, match="one taker"):
        pair_fill_legs([parse_fill_row(_leg()), parse_fill_row(_leg(user="0xz"))])


def test_match_fill_round_trips_through_a_silver_record() -> None:
    m = pair_fill_legs([parse_fill_row(_leg(user="0xa")), parse_fill_row(_leg(side="A", crossed=False, oid=2, user="0xm"))])[0]
    record = m.to_dict()
    assert record["notional"] == 600.0 and record["hash"] == "0xh"
    assert MatchFill.from_record(record) == m
