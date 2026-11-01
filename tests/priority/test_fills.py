from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import lz4.frame
import polars as pl
import pytest

from marketimmune.cli import find_first_priority_day
from marketimmune.lake import checks
from marketimmune.priority import fills


def fill(coin: str, px: str, sz: str, side: str, oid: int, tid: int, crossed: bool, **extra: object) -> dict[str, Any]:
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
    return [json.dumps(b100), json.dumps(b101)]


def test_parse_and_pair() -> None:
    df = fills.parse(lines())
    assert df.height == 4
    assert df.schema["block_time"] == pl.Datetime("ns", "UTC")
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


def test_read_lz4_prefilter_and_first_priority_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for day, blocks in (("20260301", lines()[:1]), ("20260302", lines())):
        (tmp_path / day).mkdir()
        (tmp_path / day / "0.lz4").write_bytes(lz4.frame.compress(("\n".join(blocks) + "\n").encode()))
    assert fills.read_lz4(tmp_path / "20260302" / "0.lz4").height == 4
    assert fills.read_lz4(tmp_path / "20260302" / "0.lz4", contains='"priorityGas"')["tid"].to_list() == [8, 8]
    assert [d for d, _ in fills.local_days(tmp_path)] == [date(2026, 3, 1), date(2026, 3, 2)]
    assert find_first_priority_day.main(["first-priority", "--coin", "BTC", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "2026-03-02"
    find_first_priority_day.main(["first-priority", "--coin", "ETH", str(tmp_path)])
    assert capsys.readouterr().out.startswith("no priorityGas > 0 on ETH")


def test_liquidation_details_and_write_day(tmp_path: Path) -> None:
    from marketimmune.cli.pull_node_fills import write_day

    forced = {
        "local_time": "2025-12-15T12:00:02.100000000",
        "block_time": "2025-12-15T12:00:02.000000000",
        "block_number": 102,
        "events": [
            [
                "0xL",
                fill("BTC", "98.0", "1", "A", 13, 9, True, liquidation={"liquidatedUser": "0xL", "markPx": "98.1", "method": "backstop"}),
            ],
            ["0xV", fill("BTC", "98.0", "1", "B", 23, 9, False)],
            ["0xE", fill("ETH", "3000.0", "1", "B", 31, 10, True)],
        ],
    }
    hours = [lines(), [json.dumps(forced)]]  # two hourly files
    expected = fills.parse([*lines(), json.dumps(forced)]).filter(pl.col("coin") == "BTC").sort("block_number", "tid", "crossed")
    for chunk_rows in (1, 3, 1_000):  # a chunk ends at a block, so 3 splits after block 101
        paths = {c: tmp_path / str(chunk_rows) / c / f"{c}-20251215.parquet" for c in ("BTC", "SOL")}
        assert write_day(hours, ["BTC", "SOL"], paths, chunk_rows=chunk_rows) == {"BTC": 6, "SOL": 0}
        btc = pl.read_parquet(paths["BTC"])
        assert btc.equals(expected) and pl.read_parquet(paths["SOL"]).height == 0
        assert not list(tmp_path.rglob("*.part"))
    liq = btc.filter(pl.col("liquidation"))
    assert liq.select("liquidated_user", "liquidation_mark_px", "liquidation_method").row(0) == ("0xL", 98.1, "backstop")
    assert btc.filter(~pl.col("liquidation"))["liquidation_method"].null_count() == 5
    # blocks out of order across hours: the file is sorted again
    late = {c: tmp_path / "late" / c / f"{c}.parquet" for c in ("BTC",)}
    write_day([[json.dumps(forced)], lines()], ["BTC"], late, chunk_rows=1)
    assert pl.read_parquet(late["BTC"]).equals(expected)
    empty = {"BTC": tmp_path / "empty" / "BTC.parquet"}
    assert write_day([], ["BTC"], empty) == {"BTC": 0} and pl.read_parquet(empty["BTC"]).schema == expected.schema
