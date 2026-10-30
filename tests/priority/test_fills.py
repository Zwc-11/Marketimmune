from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from marketimmune.lake import checks
from marketimmune.priority import fills


def fill(coin: str, px: str, sz: str, side: str, oid: int, tid: int, crossed: bool, **extra: object) -> dict:
    return {
        "coin": coin,
        "px": px,
        "sz": sz,
        "side": side,
        "time": 1765800000000,
        "startPosition": "0",
        "dir": "Open Long",
        "closedPnl": "0",
        "hash": "0x0",
        "oid": oid,
        "crossed": crossed,
        "fee": "0.01" if crossed else "-0.001",
        "tid": tid,
        "feeToken": "USDC",
        **extra,
    }


def lines() -> list[str]:
    # Block 100: taker 0xT buys 1 BTC from maker 0xM at 100.0 (taker side "B").
    # Block 101: taker 0xT sells 2 BTC into maker 0xN at 99.0 with priorityGas.
    b100 = {
        "local_time": "2025-12-15T12:00:00.100000000",
        "block_time": "2025-12-15T12:00:00.000000000",
        "block_number": 100,
        "events": [
            ["0xT", fill("BTC", "100.0", "1", "B", 11, 7, True)],
            ["0xM", fill("BTC", "100.0", "1", "A", 21, 7, False)],
        ],
    }
    b101 = {
        "local_time": "2025-12-15T12:00:01.100000000",
        "block_time": "2025-12-15T12:00:01.000000000",
        "block_number": 101,
        "events": [
            ["0xT", fill("BTC", "99.0", "2", "A", 12, 8, True, priorityGas="40000")],
            ["0xN", fill("BTC", "99.0", "2", "B", 22, 8, False)],
        ],
    }
    return [json.dumps(b100), json.dumps(b101), ""]


def test_parse_and_pair() -> None:
    df = fills.parse(lines())
    assert df.height == 4
    assert df.schema["block_time"] == pl.Datetime("ns", "UTC")
    assert fills.dedupe_legs(df).height == 2
    pairs = fills.pair_legs(df).sort("tid")
    assert pairs["maker"].to_list() == ["0xM", "0xN"]
    assert pairs["maker_sigma"].to_list() == [-1, 1]  # maker sold, then maker bought
    assert pairs["priority_gas"].to_list() == [None, 40000.0]
    assert checks.fill_legs(df).ok


def test_fill_legs_flags_missing_leg() -> None:
    df = fills.parse(lines()).filter(~((pl.col("tid") == 8) & ~pl.col("crossed")))
    c = checks.fill_legs(df)
    assert not c.ok and c.detail["bad_matches"] == 1


def test_markouts_match_hand_computation() -> None:
    pairs = fills.pair_legs(fills.parse(lines())).sort("tid")
    t0 = datetime(2025, 12, 15, 12, 0, 0, tzinfo=UTC)
    mids = pl.DataFrame(
        {
            "coin": ["BTC"] * 4,
            "t": [
                t0 - timedelta(milliseconds=1),
                t0 + timedelta(milliseconds=500),
                t0 + timedelta(seconds=1) - timedelta(milliseconds=1),
                t0 + timedelta(seconds=11),
            ],
            "mid": [99.95, 100.5, 99.10, 98.0],
        }
    ).with_columns(pl.col("t").dt.cast_time_unit("ns"))
    out = fills.markouts(pairs, mids, [1.0, 10.0]).sort("tid")
    # Fill 1: maker sold (sigma -1) at 100.0; pre-mid 99.95; mid at t+1s = 99.10 (last <= t+1s).
    m_pre, p = 99.95, 100.0
    assert out["hs_bps"][0] == pytest.approx(-1 * (m_pre - p) / m_pre * 1e4)
    assert out["mo_1s"][0] == pytest.approx(-1 * (99.10 - p) / m_pre * 1e4)
    # Fill 2: maker bought (sigma +1) at 99.0; pre-mid 99.10; mid at t+10s = 98.0.
    assert out["mo_10s"][1] == pytest.approx((98.0 - 99.0) / 99.10 * 1e4)
    assert out["adv_10s"][1] == pytest.approx((98.0 - 99.10) / 99.10 * 1e4)
    # Decomposition: markout = half-spread + adverse move.
    assert (out["mo_10s"] - out["hs_bps"] - out["adv_10s"]).abs().max() < 1e-9


def test_first_priority_day() -> None:
    df = fills.parse(lines())
    quiet = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("priority_gas"))
    days = [(date(2026, 3, 1), quiet), (date(2026, 3, 2), df)]
    assert fills.first_priority_day(days, "BTC") == date(2026, 3, 2)
    assert fills.first_priority_day(days, "ETH") is None
