"""Tests for the Hyperliquid requester-pays backfill CLI wrapper."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from marketimmune.ingest.hyperliquid_fills import NODE_DATA_BUCKET


def _load_cli() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_hyperliquid_day.py"
    spec = importlib.util.spec_from_file_location("backfill_hyperliquid_day", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load backfill_hyperliquid_day.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()


def _book_line(ts_ms: int, bid: float, ask: float) -> str:
    return json.dumps({
        "coin": "BTC",
        "time": ts_ms,
        "levels": [
            [{"px": str(bid), "sz": "1.0", "n": 1}],
            [{"px": str(ask), "sz": "1.0", "n": 1}],
        ],
    })


def test_parse_hours_accepts_repeats_ranges_and_commas() -> None:
    assert cli.parse_hours(["0-2", "2,3"]) == [0, 1, 2, 3]


def test_parse_hours_rejects_bad_hour() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_hours(["24"])


def test_fill_suffixes_for_hours_use_confirmed_hourly_partition() -> None:
    assert cli.fill_suffixes_for_hours("20250727", ["8-10"]) == [
        "hourly/20250727/8.lz4",
        "hourly/20250727/9.lz4",
        "hourly/20250727/10.lz4",
    ]


def test_combine_fill_suffixes_preserves_order_and_dedupes() -> None:
    assert cli.combine_fill_suffixes(
        date="20250727",
        explicit_suffixes=["hourly/20250727/8.lz4"],
        fill_hour_values=["8-9"],
    ) == ["hourly/20250727/8.lz4", "hourly/20250727/9.lz4"]


def test_main_runs_with_injected_fetchers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
        "node_fills_by_block/part.json.lz4": json.dumps({
            "nodeFills": [{
                "coin": "BTC",
                "px": "100.0",
                "sz": "2.0",
                "side": "B",
                "crossed": False,
                "time": 1_000,
            }]
        }).encode("utf-8")
    }

    def fake_fetcher(bucket: str = "hyperliquid-archive"):
        payloads = node_payloads if bucket == NODE_DATA_BUCKET else archive_payloads

        def fetch(key: str) -> bytes:
            return payloads[key]

        return fetch

    monkeypatch.setattr(cli, "boto3_requester_pays_fetcher", fake_fetcher)
    monkeypatch.setattr(cli, "lz4_decompress", lambda raw: raw)
    assert cli.main([
        "--coin", "BTC",
        "--date", "20260101",
        "--hour", "0",
        "--fill-suffix", "part.json.lz4",
        "--lake-root", str(tmp_path),
        "--no-resilience",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["book_snapshots"] == 2
    assert output["asset_contexts"] == 1
    assert output["fills"] == 1
    assert output["gold_rows"] == 1
    assert output["training_rows"] == 1
    assert len(output["writes"]) == 6
