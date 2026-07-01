"""Tests for Hyperliquid Bronze/Silver/Gold parquet writers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.ingest.hyperliquid_api import Candle
from marketimmune.ingest.hyperliquid_archive import BookSnapshot, L2Level
from marketimmune.ingest.hyperliquid_asset_ctxs import AssetCtx
from marketimmune.ingest.hyperliquid_fills import parse_fill_row
from marketimmune.ingest.hyperliquid_gold import build_markout_gold_rows
from marketimmune.ingest.hyperliquid_lake import (
    HyperliquidLakeLayout,
    bronze_fill_record,
    gold_markout_record,
    read_parquet_records,
    silver_asset_ctx_record,
    silver_candle_record,
    silver_fill_record,
    silver_l2_book_record,
    write_bronze_fills,
    write_gold_markout,
    write_gold_training_rows,
    write_parquet_records,
    write_silver_asset_ctxs,
    write_silver_candles,
    write_silver_fills,
    write_silver_l2_book,
)
from marketimmune.labels.markout import MarkoutConfig


def _fill():
    return parse_fill_row({
        "coin": "BTC",
        "px": "100.0",
        "sz": "2.0",
        "side": "B",
        "crossed": False,
        "time": 1_000,
        "fee": "0.02",
        "feeToken": "USDC",
        "oid": 1,
        "tid": 2,
        "hash": "0xabc",
        "dir": "Open Long",
    })


def _book(ts_ms: int, bid: float, ask: float) -> BookSnapshot:
    return BookSnapshot(
        ts_ms=ts_ms,
        coin="BTC",
        bids=(L2Level(px=bid, sz=1.0, n=1),),
        asks=(L2Level(px=ask, sz=1.0, n=1),),
    )


def test_layout_paths_are_layered(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    assert layout.bronze_fills_path("btc", "20260101").as_posix().endswith(
        "bronze/hyperliquid/fills/BTC/BTC-20260101.parquet"
    )
    assert layout.silver_fills_path("BTC/USDC", "20260101").as_posix().endswith(
        "silver/hyperliquid/fills/BTC-USDC/BTC-USDC-20260101.parquet"
    )
    assert layout.silver_l2_book_path("BTC", "20260101").as_posix().endswith(
        "silver/hyperliquid/l2_book/BTC/BTC-20260101.parquet"
    )
    assert layout.silver_asset_ctxs_path("20260101").as_posix().endswith(
        "silver/hyperliquid/asset_ctxs/asset-ctxs-20260101.parquet"
    )
    assert layout.silver_candles_path("BTC", "1m", "20260101").as_posix().endswith(
        "silver/hyperliquid/candles/1m/BTC/BTC-1m-20260101.parquet"
    )
    assert layout.gold_markout_path("BTC", "20260101").as_posix().endswith(
        "gold/hyperliquid/markout/BTC/BTC-markout-20260101.parquet"
    )
    assert layout.gold_training_path("BTC", "20260101").as_posix().endswith(
        "gold/hyperliquid/training/BTC/BTC-training-20260101.parquet"
    )


def test_bronze_fill_record_keeps_raw_json() -> None:
    record = bronze_fill_record(_fill())
    raw = json.loads(record["raw_json"])
    assert raw["coin"] == "BTC"
    assert record["maker_side"] == 1


def test_silver_fill_record_has_conformed_fields() -> None:
    record = silver_fill_record(_fill())
    assert record["notional"] == pytest.approx(200.0)
    assert record["fee_bps"] == pytest.approx(1.0)
    assert record["hash"] == "0xabc"


def test_silver_l2_book_record_has_top_of_book_features() -> None:
    record = silver_l2_book_record(_book(2_000, 99.0, 101.0))
    assert record["coin"] == "BTC"
    assert record["mid"] == pytest.approx(100.0)
    assert record["spread_bps"] == pytest.approx(200.0)
    assert record["top_imbalance"] == pytest.approx(0.0)


def test_silver_asset_ctx_record_has_basis() -> None:
    record = silver_asset_ctx_record(
        AssetCtx(
            coin="BTC",
            funding=0.01,
            open_interest=10.0,
            oracle_px=100.0,
            mark_px=101.0,
            mid_px=100.5,
            premium=0.001,
            ts_ms=1_000,
        )
    )
    assert record["coin"] == "BTC"
    assert record["ts_ms"] == 1_000
    assert record["basis_bps"] == pytest.approx(100.0)


def test_silver_candle_record_is_flat() -> None:
    record = silver_candle_record(
        Candle("BTC", "1m", 1_000, 1_999, 100.0, 101.0, 99.0, 100.5, 12.0, 3)
    )
    assert record["coin"] == "BTC"
    assert record["interval"] == "1m"
    assert record["close"] == pytest.approx(100.5)


def test_gold_markout_record_flattens_horizons() -> None:
    rows = build_markout_gold_rows(
        [_fill()],
        [_book(2_000, 98.0, 100.0)],
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    record = gold_markout_record(rows[0])
    assert record["markout_bps_1s"] == pytest.approx(-100.0)
    assert record["toxic_1s"] is True


def test_write_parquet_records_rejects_empty(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty Hyperliquid parquet"):
        write_parquet_records(tmp_path / "empty.parquet", [])


def test_write_bronze_and_silver_fills(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    fill = _fill()
    bronze = write_bronze_fills(layout, coin="BTC", date="20260101", fills=[fill])
    silver = write_silver_fills(layout, coin="BTC", date="20260101", fills=[fill])
    assert bronze.rows == 1
    assert silver.rows == 1
    assert read_parquet_records(bronze.path)[0]["coin"] == "BTC"
    assert read_parquet_records(silver.path)[0]["notional"] == pytest.approx(200.0)


def test_write_silver_l2_book_and_asset_ctxs(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    book = write_silver_l2_book(
        layout,
        coin="BTC",
        date="20260101",
        snapshots=[_book(2_000, 99.0, 101.0)],
    )
    ctxs = write_silver_asset_ctxs(
        layout,
        date="20260101",
        contexts=[AssetCtx("BTC", 0.01, 10.0, 100.0, 101.0, 100.5, 0.001)],
    )
    assert read_parquet_records(book.path)[0]["mid"] == pytest.approx(100.0)
    assert read_parquet_records(ctxs.path)[0]["basis_bps"] == pytest.approx(100.0)


def test_write_silver_candles(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    result = write_silver_candles(
        layout,
        coin="BTC",
        interval="1m",
        date="20260101",
        candles=[Candle("BTC", "1m", 1_000, 1_999, 100.0, 101.0, 99.0, 100.5, 12.0, 3)],
    )
    records = read_parquet_records(result.path)
    assert result.rows == 1
    assert records[0]["volume"] == pytest.approx(12.0)


def test_write_gold_markout(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    rows = build_markout_gold_rows(
        [_fill()],
        [_book(2_000, 98.0, 100.0)],
        MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    result = write_gold_markout(layout, coin="BTC", date="20260101", rows=rows)
    records = read_parquet_records(result.path)
    assert result.rows == 1
    assert records[0]["markout_bps_1s"] == pytest.approx(-100.0)


def test_write_gold_training_rows(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    result = write_gold_training_rows(
        layout,
        coin="BTC",
        date="20260101",
        rows=[{"coin": "BTC", "ts_ms": 1_000, "l2_mid": 100.0, "toxic_1s": True}],
    )
    records = read_parquet_records(result.path)
    assert result.rows == 1
    assert records[0]["l2_mid"] == pytest.approx(100.0)
