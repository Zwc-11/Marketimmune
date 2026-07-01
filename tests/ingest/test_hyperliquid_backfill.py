"""Tests for Hyperliquid daily backfill orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.ingest.hyperliquid_archive import HyperliquidArchive
from marketimmune.ingest.hyperliquid_backfill import (
    HyperliquidBackfillResult,
    HyperliquidDailyBackfill,
)
from marketimmune.ingest.hyperliquid_fills import HyperliquidNodeFills
from marketimmune.ingest.hyperliquid_lake import HyperliquidLakeLayout, read_parquet_records
from marketimmune.labels.markout import MarkoutConfig


def _book_line(ts_ms: int, bid: float, ask: float) -> str:
    return json.dumps({
        "coin": "BTC",
        "time": ts_ms,
        "levels": [
            [{"px": str(bid), "sz": "1.0", "n": 1}],
            [{"px": str(ask), "sz": "1.0", "n": 1}],
        ],
    })


def _fill(coin: str = "BTC") -> dict[str, object]:
    return {
        "coin": coin,
        "px": "100.0",
        "sz": "2.0",
        "side": "B",
        "crossed": False,
        "time": 1_000,
        "fee": "0.02",
        "feeToken": "USDC",
        "oid": 1,
        "tid": 2,
    }


def test_daily_backfill_writes_nonempty_artifacts(tmp_path: Path) -> None:
    archive_payloads = {
        "market_data/20260101/0/l2Book/BTC.lz4": (
            _book_line(1_000, 99.0, 101.0) + "\n" + _book_line(2_000, 98.0, 100.0)
        ).encode("utf-8"),
        "asset_ctxs/20260101.csv.lz4": (
            b"coin,funding,openInterest,oraclePx,markPx,midPx,premium\n"
            b"BTC,0.01,10.0,100.0,101.0,100.5,0.001\n"
        ),
    }
    node_payloads = {
        "node_fills_by_block/part-000.json.lz4": json.dumps({
            "nodeFills": [_fill("BTC"), _fill("ETH")]
        }).encode("utf-8")
    }

    def archive_fetch(key: str) -> bytes:
        return archive_payloads[key]

    def node_fetch(key: str) -> bytes:
        return node_payloads[key]

    backfill = HyperliquidDailyBackfill(
        layout=HyperliquidLakeLayout(tmp_path),
        archive=HyperliquidArchive(fetch=archive_fetch, decompress=lambda raw: raw),
        node_fills=HyperliquidNodeFills(fetch=node_fetch, decompress=lambda raw: raw),
        markout_config=MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    result = backfill.run(
        coin="BTC",
        date="20260101",
        hours=[0],
        fill_suffixes=["part-000.json.lz4"],
    )
    assert isinstance(result, HyperliquidBackfillResult)
    assert result.book_snapshots == 2
    assert result.asset_contexts == 1
    assert result.fills == 1
    assert result.gold_rows == 1
    assert result.training_rows == 1
    assert len(result.writes) == 6

    layout = HyperliquidLakeLayout(tmp_path)
    book_rows = read_parquet_records(layout.silver_l2_book_path("BTC", "20260101"))
    ctx_rows = read_parquet_records(layout.silver_asset_ctxs_path("20260101"))
    bronze_rows = read_parquet_records(layout.bronze_fills_path("BTC", "20260101"))
    silver_rows = read_parquet_records(layout.silver_fills_path("BTC", "20260101"))
    gold_rows = read_parquet_records(layout.gold_markout_path("BTC", "20260101"))
    training_rows = read_parquet_records(layout.gold_training_path("BTC", "20260101"))
    assert book_rows[0]["mid"] == pytest.approx(100.0)
    assert ctx_rows[0]["basis_bps"] == pytest.approx(100.0)
    assert bronze_rows[0]["coin"] == "BTC"
    assert silver_rows[0]["notional"] == pytest.approx(200.0)
    assert gold_rows[0]["markout_bps_1s"] == pytest.approx(-100.0)
    assert training_rows[0]["l2_mid"] == pytest.approx(100.0)
    assert training_rows[0]["asset_basis_bps"] == pytest.approx(100.0)


def test_daily_backfill_reports_progress(tmp_path: Path) -> None:
    archive_payloads = {
        "market_data/20260101/0/l2Book/BTC.lz4": (
            _book_line(1_000, 99.0, 101.0) + "\n" + _book_line(2_000, 98.0, 100.0)
        ).encode("utf-8"),
        "asset_ctxs/20260101.csv.lz4": (
            b"coin,funding,openInterest,oraclePx,markPx,midPx,premium\n"
            b"BTC,0.01,10.0,100.0,101.0,100.5,0.001\n"
        ),
    }
    node_payloads = {
        "node_fills_by_block/hourly/20260101/0.lz4": json.dumps({
            "nodeFills": [_fill("BTC")]
        }).encode("utf-8")
    }
    backfill = HyperliquidDailyBackfill(
        layout=HyperliquidLakeLayout(tmp_path),
        archive=HyperliquidArchive(
            fetch=lambda key: archive_payloads[key],
            decompress=lambda raw: raw,
        ),
        node_fills=HyperliquidNodeFills(
            fetch=lambda key: node_payloads[key],
            decompress=lambda raw: raw,
        ),
        markout_config=MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    messages: list[str] = []

    result = backfill.run(
        coin="BTC",
        date="20260101",
        hours=[0],
        fill_suffixes=["hourly/20260101/0.lz4"],
        progress=messages.append,
    )

    assert result.training_rows == 1
    assert messages == [
        "loaded 2 L2 snapshots",
        "loaded 1 asset-context rows",
        "loaded 1 raw fills",
        "filtered 1 BTC fills",
        "built 1 Gold markout rows",
        "built 1 Gold training rows",
        "wrote 6 parquet artifacts",
    ]


def test_daily_backfill_skips_empty_inputs(tmp_path: Path) -> None:
    def fail_fetch(key: str) -> bytes:
        raise AssertionError(f"unexpected fetch: {key}")

    backfill = HyperliquidDailyBackfill(
        layout=HyperliquidLakeLayout(tmp_path),
        archive=HyperliquidArchive(fetch=fail_fetch, decompress=lambda raw: raw),
        node_fills=HyperliquidNodeFills(fetch=fail_fetch, decompress=lambda raw: raw),
        markout_config=MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    result = backfill.run(
        coin="BTC",
        date="20260101",
        hours=[],
        fill_suffixes=[],
        include_asset_ctxs=False,
    )
    assert result.book_snapshots == 0
    assert result.asset_contexts == 0
    assert result.fills == 0
    assert result.gold_rows == 0
    assert result.training_rows == 0
    assert result.writes == ()
