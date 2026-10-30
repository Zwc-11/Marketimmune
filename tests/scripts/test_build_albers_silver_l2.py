"""End-to-end test of the Albers -> Silver L2 script on tiny archives."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from scripts import build_albers_fills, build_albers_gold, run_albers_month
from scripts.build_albers_silver_l2 import build, next_hour, parse_args, parse_hours
from tests.ingest.test_albers import status_records

DEC1 = 1_764_547_200 * 1_000_000_000  # 2025-12-01T00:00:00Z in ns
S = 1_000_000_000


def _add(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))


def _diff(oid: int, sz: float) -> str:
    return json.dumps({"oid": oid, "coin": "SOL", "side": "B", "px": "1",
                       "raw_book_diff": {"new": {"sz": str(sz)}}}, separators=(",", ":"))


def test_build_writes_rows_and_validation(tmp_path: Path) -> None:
    hour0 = status_records([
        {"ts": DEC1 + 1 * S, "status": "open", "oid": 1, "px": 100.00, "sz": 2.0},
        {"ts": DEC1 + 1 * S, "status": "open", "oid": 2, "px": 100.02, "sz": 1.0, "ask": True},
        # opened at the very end of hour 0; its ``new`` diff sits in hour 1's file
        {"ts": DEC1 + 3599 * S, "status": "open", "oid": 3, "px": 100.01, "sz": 4.0, "ask": True},
    ])
    hour1 = status_records([
        {"ts": DEC1 + 3601 * S, "status": "filled", "oid": 3, "px": 100.01, "sz": 0.0, "ask": True},
    ])
    with tarfile.open(tmp_path / "sol_orders_202512.tar.xz", "w:xz") as tar:
        _add(tar, "20251201/sol_00.data.gz", gzip.compress(hour0.tobytes()))
        _add(tar, "20251201/sol_01.data.gz", gzip.compress(hour1.tobytes()))
    with tarfile.open(tmp_path / "book_diffs_202512.tar", "w") as tar:
        _add(tar, "20251201/ex0.gz", gzip.compress(f"{_diff(1, 2.0)}\n{_diff(2, 1.0)}\n".encode()))
        _add(tar, "20251201/ex1.gz", gzip.compress(f"{_diff(3, 4.0)}\n".encode()))

    args = parse_args([
        "--dates", "20251201", "--hours", "0-1", "--albers-dir", str(tmp_path),
        "--lake-root", str(tmp_path / "lake"), "--warmup-minutes", "0",
    ])
    assert build(args)["dates"] == ["20251201"]

    base = tmp_path / "lake/silver/hyperliquid/l2_book/SOL/SOL-20251201"
    table = pq.read_table(base.with_suffix(".parquet"))
    assert table.schema.metadata[b"source"].startswith(b"albers-l4")
    assert str(table.schema.field("bid_n_1").type) == "int64"
    rows = table.to_pylist()
    assert [r["ask_px"] for r in rows] == [100.02, 100.01, 100.02]
    report = json.loads(base.with_suffix(".validation.json").read_text())
    assert [h["hour"] for h in report["hours"]] == [0, 1]
    assert report["hours"][0]["opens_rested"] == 3
    assert report["hours"][1]["fills_at_touch"] == 1

    # fills: one trade at 2 s (the 100.02 ask lifted by 0xt), one for another coin
    trade = {
        "coin": "SOL", "side": "B", "time": "2025-12-01T00:00:02.000000000", "px": "100.02",
        "sz": "0.5", "hash": "0x1",
        "side_info": [{"user": "0xt", "start_pos": "0", "oid": 50},
                      {"user": "0xm", "start_pos": "3", "oid": 2}],
    }
    lines = "\n".join(json.dumps({**trade, "coin": c}) for c in ("SOL", "ETH")) + "\n"
    with tarfile.open(tmp_path / "trades_2025_12.tar", "w") as tar:
        _add(tar, "20251201/0.gz", gzip.compress(lines.encode()))
    lake = ["--lake-root", str(tmp_path / "lake")]
    (fills,) = build_albers_fills.build(
        build_albers_fills.parse_args(["--albers-dir", str(tmp_path), *lake])
    )
    assert fills["matches"] == 1 and fills["liquidation_source"] == "missing"

    binance = tmp_path / "binance" / "SOLUSDT"
    binance.mkdir(parents=True)
    with zipfile.ZipFile(binance / "SOLUSDT-aggTrades-2025-12-01.zip", "w") as zf:
        zf.writestr("x.csv", f"1,100.0,1,1,1,{DEC1 // 10**6 - 5000},true\n"
                             f"2,100.1,1,2,2,{DEC1 // 10**6 + 1800},false\n")
    gold_args = [*lake, "--binance-dir", str(tmp_path / "binance")]
    (gold,) = build_albers_gold.build(build_albers_gold.parse_args(gold_args))
    assert gold["gold_rows"] == 1 and gold["leakage_check"]["passed"] is True
    assert gold["cex"] == {"added": True, "leakage_passed": True, "nan_share": 0.0}
    sidecar = json.loads(
        (tmp_path / "lake/gold/hyperliquid/training/SOL/SOL-training-20251201.leakage.json")
        .read_text()
    )
    assert sidecar["passed"] is True and sidecar["cex"]["n_checked"] == 1
    training = pq.read_table(
        tmp_path / "lake/gold/hyperliquid/training/SOL/SOL-training-20251201.parquet"
    ).to_pylist()[0]
    assert training["maker_user"] == "0xm" and training["maker_side"] == -1
    assert training["mid_before"] == pytest.approx(100.01)
    assert training["l2_mid"] == pytest.approx(100.01)
    # the fill is at 2 s; Binance's 100.1 print at 1.8 s is inside the 300 ms latency
    assert training["cex_ret_1000ms_bps"] == pytest.approx(0.0)
    assert training["cex_ret_5000ms_bps"] == pytest.approx(0.0)

    # the orchestrator reruns a stage; without Binance zips the CEX step reports why
    assert run_albers_month.main(["--stages", "gold", "--dates", "20251201", *lake,
                                  "--binance-dir", str(tmp_path / "none")]) == 0
    with pytest.raises(SystemExit, match="unknown stage"):
        run_albers_month.main(["--stages", "bogus"])


def test_hour_helpers() -> None:
    assert parse_hours("0-2,5") == [0, 1, 2, 5]
    with pytest.raises(ValueError, match="0-23"):
        parse_hours("20-24")
    assert next_hour("20251201", 23) == ("20251202", 0)
    assert next_hour("20251231", 5) == ("20251231", 6)


def test_gold_skips_dates_without_inputs(tmp_path: Path) -> None:
    assert build_albers_gold.build(
        build_albers_gold.parse_args(["--lake-root", str(tmp_path)])
    ) == []
