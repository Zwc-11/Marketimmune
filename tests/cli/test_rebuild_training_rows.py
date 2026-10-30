"""Tests for rebuilding Hyperliquid training rows from local lake artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketimmune.cli.rebuild_training_rows import rebuild_training_rows
from marketimmune.lake.tables import (
    HyperliquidLakeLayout,
    read_parquet_records,
    write_parquet_records,
)


def test_rebuild_training_rows_adds_ofi_features(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    write_parquet_records(
        layout.gold_markout_path("BTC", "20260101"),
        [
            {
                "coin": "BTC",
                "ts_ms": 2_000,
                "px": 100.0,
                "sz": 1.0,
                "maker_side": 1,
                "fee_bps": 0.0,
                "markout_bps_10s": -1.0,
                "toxic_10s": True,
            }
        ],
    )
    write_parquet_records(
        layout.silver_l2_book_path("BTC", "20260101"),
        [
            {
                "coin": "BTC",
                "ts_ms": 1_000,
                "bid_px": 99.5,
                "bid_sz": 10.0,
                "ask_px": 100.5,
                "ask_sz": 10.0,
                "mid": 100.0,
                "spread_bps": 100.0,
                "microprice": 100.0,
                "top_imbalance": 0.0,
            },
            {
                "coin": "BTC",
                "ts_ms": 1_500,
                "bid_px": 99.5,
                "bid_sz": 12.0,
                "ask_px": 100.5,
                "ask_sz": 8.0,
                "mid": 100.0,
                "spread_bps": 100.0,
                "microprice": 100.1,
                "top_imbalance": 0.2,
            },
        ],
    )

    result = rebuild_training_rows(lake_root=tmp_path, coin="BTC", date="20260101")

    rows = read_parquet_records(layout.gold_training_path("BTC", "20260101"))
    assert result["training_rows"] == 1
    assert rows[0]["l2_ofi_event"] == pytest.approx(0.1)
    assert rows[0]["l2_ofi_10s"] == pytest.approx(0.1)
    # Fix B3: the rebuild writes the no-look-ahead check beside the partition.
    assert result["leakage_check"] == {"passed": True, "n_checked": 1, "n_mismatched": 0}
    sidecar = Path(str(result["leakage_report"]))
    assert sidecar.name == "BTC-training-20260101.leakage.json"
    assert json.loads(sidecar.read_text())["passed"] is True
