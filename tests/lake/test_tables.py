from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.labels.markout import MarkoutConfig
from marketimmune.lake.gold import build_markout_gold_rows
from marketimmune.lake.tables import (
    HyperliquidLakeLayout,
    bronze_fill_record,
    gold_markout_record,
    leakage_report_path,
    read_parquet_records,
    read_parquet_window,
    silver_asset_ctx_record,
    silver_l2_book_record,
    write_bronze_fills,
    write_gold_markout,
    write_gold_training_rows,
    write_leakage_report,
    write_parquet_records,
    write_silver_asset_ctxs,
    write_silver_fills,
    write_silver_l2_book,
)
from marketimmune.sources.hyperliquid_asset_ctxs import AssetCtx
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot, L2Level
from marketimmune.sources.hyperliquid_node_fills import NodeFill, pair_fill_legs, parse_fill_row


def _leg(side: str, crossed: bool, user: str) -> NodeFill:
    return parse_fill_row(
        {
            "coin": "BTC",
            "px": "100.0",
            "sz": "2.0",
            "side": side,
            "crossed": crossed,
            "time": 1_000,
            "fee": "0.02",
            "feeToken": "USDC",
            "oid": 1,
            "tid": 2,
            "hash": "0xabc",
            "dir": "Open Long",
            "user": user,
        }
    )


def _book(ts_ms: int, bid: float, ask: float) -> BookSnapshot:
    return BookSnapshot(ts_ms=ts_ms, coin="BTC", bids=(L2Level(px=bid, sz=1.0, n=1),), asks=(L2Level(px=ask, sz=1.0, n=1),))


def test_layout_paths_are_layered(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    assert layout.bronze_fills_path("btc", "20260101") == tmp_path / "bronze/hyperliquid/fills/BTC/BTC-20260101.parquet"
    assert layout.silver_fills_path("BTC/USDC", "20260101") == tmp_path / "silver/hyperliquid/fills/BTC-USDC/BTC-USDC-20260101.parquet"
    assert layout.silver_order_events_path("SOL", "20260101") == tmp_path / "silver/hyperliquid/order_events/SOL/SOL-20260101.parquet"
    assert layout.silver_l2_book_path("BTC", "20260101") == tmp_path / "silver/hyperliquid/l2_book/BTC/BTC-20260101.parquet"
    assert layout.silver_asset_ctxs_path("20260101") == tmp_path / "silver/hyperliquid/asset_ctxs/asset-ctxs-20260101.parquet"
    assert layout.gold_markout_path("BTC", "20260101") == tmp_path / "gold/hyperliquid/markout/BTC/BTC-markout-20260101.parquet"
    assert layout.gold_training_path("BTC", "20260101") == tmp_path / "gold/hyperliquid/training/BTC/BTC-training-20260101.parquet"
    assert leakage_report_path(layout, "BTC", "20260101") == tmp_path / "gold/hyperliquid/training/BTC/BTC-training-20260101.leakage.json"


def test_bronze_fill_record_keeps_raw_json() -> None:
    record = bronze_fill_record(_leg("B", False, "0xm"))
    assert json.loads(record["raw_json"])["user"] == "0xm"
    assert record["maker_side"] == 1 and record["hash"] == "0xabc"


def test_silver_l2_book_record_keeps_five_levels() -> None:
    snap = BookSnapshot(
        ts_ms=1,
        coin="BTC",
        bids=tuple(L2Level(px=100.0 - i, sz=1.0 + i, n=i + 1) for i in range(6)),
        asks=(L2Level(px=102.0, sz=1.0, n=1),),
    )
    record = silver_l2_book_record(snap)
    assert (record["bid_px"], record["ask_px"], record["mid"], record["spread_bps"]) == (100.0, 102.0, 101.0, pytest.approx(2 / 101 * 1e4))
    assert record["bid_px_5"] == 96.0 and record["bid_n_5"] == 5 and "bid_px_6" not in record
    assert record["ask_px_1"] == 102.0 and record["ask_px_2"] is None and record["ask_n_5"] is None


def test_silver_asset_ctx_record_has_basis() -> None:
    record = silver_asset_ctx_record(AssetCtx("BTC", 0.01, 10.0, oracle_px=100.0, mark_px=101.0, mid_px=100.5, premium=0.001, ts_ms=1_000))
    assert list(record)[-2:] == ["basis_bps", "ts_ms"]
    assert record["basis_bps"] == pytest.approx(100.0)


def test_gold_markout_record_flattens_horizons() -> None:
    rows = build_markout_gold_rows(
        [_leg("B", False, "0xm")], [_book(2_000, 98.0, 100.0)], MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0, reference="fill_px")
    )
    record = gold_markout_record(rows[0])
    assert record["markout_bps_1s"] == pytest.approx(-100.0) and record["toxic_1s"] is True
    assert list(record)[9:12] == ["markout_bps_1s", "toxic_1s", "mid_before"]


def test_writers_round_trip(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    legs = [_leg("B", True, "0xt"), _leg("A", False, "0xm")]
    assert write_bronze_fills(layout, coin="BTC", date="20260101", fills=legs).rows == 2
    silver = write_silver_fills(layout, coin="BTC", date="20260101", fills=pair_fill_legs(legs))
    (row,) = read_parquet_records(silver.path)
    assert (row["maker_user"], row["taker_user"], row["notional"]) == ("0xm", "0xt", 200.0)
    book = write_silver_l2_book(layout, coin="BTC", date="20260101", snapshots=[_book(2_000, 99.0, 101.0)])
    assert read_parquet_records(book.path, columns=("mid",)) == [{"mid": 100.0}]
    ctxs = write_silver_asset_ctxs(layout, date="20260101", contexts=[AssetCtx("BTC", 0.01, 10.0, 100.0, 101.0, 100.5, 0.001, 0)])
    assert read_parquet_records(ctxs.path)[0]["basis_bps"] == pytest.approx(100.0)
    rows = build_markout_gold_rows(
        [_leg("B", False, "0xm")], [_book(2_000, 98.0, 100.0)], MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0, reference="fill_px")
    )
    gold = write_gold_markout(layout, coin="BTC", date="20260101", rows=rows)
    assert read_parquet_records(gold.path)[0]["markout_bps_1s"] == pytest.approx(-100.0)
    training = write_gold_training_rows(layout, coin="BTC", date="20260101", rows=[{"coin": "BTC", "ts_ms": 1_000, "l2_mid": 100.0}])
    assert training.path == layout.gold_training_path("BTC", "20260101") and training.rows == 1
    report = write_leakage_report(layout, coin="BTC", date="20260101", report={"passed": True})
    assert json.loads(report.read_text()) == {"passed": True}


def test_write_parquet_records_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="empty parquet"):
        write_parquet_records(tmp_path / "empty.parquet", [])


def test_read_parquet_window_sorts_then_slices_latest_or_head(tmp_path: Path) -> None:
    path = tmp_path / "rows.parquet"
    write_parquet_records(path, [{"ts_ms": ts, "v": ts * 2} for ts in (30, 10, 50, 20, 40)])
    assert [row["ts_ms"] for row in read_parquet_window(path, limit=2)] == [40, 50]
    assert [row["ts_ms"] for row in read_parquet_window(path, limit=2, latest=False)] == [10, 20]
    assert [row["ts_ms"] for row in read_parquet_window(path, limit=0)] == [10, 20, 30, 40, 50]
    assert read_parquet_window(path, limit=9)[-1] == {"ts_ms": 50, "v": 100}
