from __future__ import annotations

import json
from pathlib import Path

import lz4.frame
import pytest

from marketimmune.labels.markout import MarkoutConfig
from marketimmune.lake.backfill import parse_hours, run_backfill
from marketimmune.lake.tables import HyperliquidLakeLayout, read_parquet_records

ASSET_CSV = (
    "time,coin,funding,open_interest,prev_day_px,day_ntl_vlm,premium,oracle_px,mark_px,mid_px,impact_bid_px,impact_ask_px\n"
    "1970-01-01T00:00:00Z,BTC,0.01,10.0,99.0,1.0,0.001,100.0,101.0,100.5,100.0,101.0\n"
)


def _book_line(ts_ms: int, bid: float, ask: float) -> str:
    levels = [[{"px": str(bid), "sz": "1.0", "n": 1}], [{"px": str(ask), "sz": "1.0", "n": 1}]]
    return json.dumps(
        {
            "time": "2026-01-01T00:00:00.0",
            "ver_num": 1,
            "raw": {"channel": "l2Book", "data": {"coin": "BTC", "time": ts_ms, "levels": levels}},
        }
    )


def _fills_block(coin: str) -> str:
    leg = {
        "coin": coin,
        "px": "100.0",
        "sz": "2.0",
        "time": 1_000,
        "fee": "0.02",
        "feeToken": "USDC",
        "tid": 2,
        "hash": "0xh",
        "startPosition": "0.0",
        "dir": "Open Long",
    }
    return json.dumps(
        {
            "block_number": 1,
            "events": [["0xm", leg | {"side": "B", "crossed": False, "oid": 1}], ["0xt", leg | {"side": "A", "crossed": True, "oid": 2}]],
        }
    )


def payloads() -> dict[str, bytes]:
    texts = {
        "market_data/20260101/0/l2Book/BTC.lz4": _book_line(999, 99.0, 101.0) + "\n" + _book_line(2_000, 98.0, 100.0) + "\n",
        "asset_ctxs/20260101.csv.lz4": ASSET_CSV,
        "node_fills_by_block/hourly/20260101/0.lz4": _fills_block("BTC") + "\n" + _fills_block("ETH") + "\n",
    }
    return {key: lz4.frame.compress(text.encode()) for key, text in texts.items()}


def test_parse_hours() -> None:
    assert parse_hours(["0-2", "2,5", " 7 "]) == (0, 1, 2, 5, 7)
    with pytest.raises(AssertionError):
        parse_hours(["24"])
    with pytest.raises(AssertionError):
        parse_hours([""])


def test_backfill_writes_every_layer(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path)
    data = payloads()
    result = run_backfill(
        layout,
        archive=data.__getitem__,
        node=data.__getitem__,
        coin="BTC",
        date="20260101",
        hours=[0],
        fill_hours=[0],
        markout_config=MarkoutConfig(horizons_s=(1.0,), fee_bps=1.0),
    )
    assert (result.book_snapshots, result.asset_contexts, result.fills, result.gold_rows, result.training_rows) == (2, 1, 2, 1, 1)
    assert [w.path for w in result.writes] == [
        layout.silver_l2_book_path("BTC", "20260101"),
        layout.silver_asset_ctxs_path("20260101"),
        layout.bronze_fills_path("BTC", "20260101"),
        layout.silver_fills_path("BTC", "20260101"),
        layout.gold_markout_path("BTC", "20260101"),
        layout.gold_training_path("BTC", "20260101"),
    ]
    assert read_parquet_records(layout.silver_l2_book_path("BTC", "20260101"))[0]["mid"] == pytest.approx(100.0)
    assert read_parquet_records(layout.silver_asset_ctxs_path("20260101"))[0]["basis_bps"] == pytest.approx(100.0)
    assert len(read_parquet_records(layout.bronze_fills_path("BTC", "20260101"))) == 2
    (match,) = read_parquet_records(layout.silver_fills_path("BTC", "20260101"))
    assert (match["maker_user"], match["taker_user"], match["notional"]) == ("0xm", "0xt", pytest.approx(200.0))
    assert read_parquet_records(layout.gold_markout_path("BTC", "20260101"))[0]["markout_bps_1s"] == pytest.approx(-100.0)
    (training,) = read_parquet_records(layout.gold_training_path("BTC", "20260101"))
    assert training["l2_mid"] == pytest.approx(100.0) and training["asset_basis_bps"] == pytest.approx(100.0)
    sidecar = layout.gold_training_path("BTC", "20260101").with_suffix(".leakage.json")
    assert json.loads(sidecar.read_text())["passed"] is True


def test_backfill_skips_empty_inputs(tmp_path: Path) -> None:
    def no_fetch(key: str) -> bytes:
        raise AssertionError(f"unexpected fetch: {key}")

    result = run_backfill(
        HyperliquidLakeLayout(tmp_path),
        archive=no_fetch,
        node=no_fetch,
        coin="BTC",
        date="20260101",
        hours=[],
        fill_hours=[],
        include_asset_ctxs=False,
    )
    assert (result.book_snapshots, result.asset_contexts, result.fills, result.gold_rows, result.training_rows, result.writes) == (
        0,
        0,
        0,
        0,
        0,
        (),
    )


def test_a_rerun_over_other_hours_does_not_silently_replace_the_day(tmp_path: Path) -> None:
    # Audit S06: hour 0 then hour 1 used to overwrite the coin-day's files.
    layout = HyperliquidLakeLayout(tmp_path)
    data = payloads()
    kwargs = {"archive": data.__getitem__, "node": data.__getitem__, "coin": "BTC", "date": "20260101", "fill_hours": [0]}
    run_backfill(layout, hours=[0], markout_config=MarkoutConfig(horizons_s=(1.0,)), **kwargs)  # type: ignore[arg-type]
    coverage = json.loads(layout.coverage_path("BTC", "20260101").read_text())
    assert (coverage["hours"], coverage["fill_hours"], coverage["duplicate_legs"]) == ([0], [0], 0)
    run_backfill(layout, hours=[0], markout_config=MarkoutConfig(horizons_s=(1.0,)), **kwargs)  # type: ignore[arg-type]  # same hours: fine
    with pytest.raises(ValueError, match="would replace"):
        run_backfill(layout, hours=[0, 1], markout_config=MarkoutConfig(horizons_s=(1.0,)), **kwargs)  # type: ignore[arg-type]
