from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.cli import simulate_quotes
from marketimmune.lake.tables import L2_DEPTH, HyperliquidLakeLayout
from marketimmune.sim.engine import FILL
from marketimmune.sim.signals import quote_signals_path
from marketimmune.sources.albers_l4 import mbo_table

SECOND = 1_000_000_000
T0 = 1_764_547_201 * SECOND  # 2025-12-01 00:00:01 UTC


def _lake(tmp_path: Path) -> list[str]:
    """Three book rows; a taker sells into an order that joined behind ours, then the mid drops."""
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    books = [(T0, 100.00, 100.01), (T0 + 1 * SECOND, 100.00, 100.01), (T0 + 2 * SECOND, 99.99, 100.00)]
    columns: dict[str, list[object]] = {"ts_ns": [t for t, _, _ in books]}
    for side, k in (("bid", 1), ("ask", 2)):
        for i in range(1, L2_DEPTH + 1):
            columns[f"{side}_px_{i}"] = [b[k] if i == 1 else None for b in books]
            columns[f"{side}_sz_{i}"] = [5.0 if i == 1 else None for _ in books]
    path = layout.silver_l2_book_path("SOL", "20251201")
    path.parent.mkdir(parents=True)
    pq.write_table(pa.table(columns), path)
    mbo = [(T0 + 1_500_000_000, FILL, 9, False, 100 * 10**7, 1.0, T0 + 1_200_000_000, True)]
    path = layout.silver_mbo_path("SOL", "20251201")
    path.parent.mkdir(parents=True)
    pq.write_table(mbo_table(mbo), path)
    binance = tmp_path / "binance" / "SOLUSDT"
    binance.mkdir(parents=True)
    for day, base in (("2025-11-30", T0 // 10**6 - 86_400_000), ("2025-12-01", T0 // 10**6)):
        with zipfile.ZipFile(binance / f"SOLUSDT-aggTrades-{day}.zip", "w") as zf:
            zf.writestr("x.csv", f"1,100.0,1,1,1,{base - 2_000},false\n2,100.0,1,2,2,{base + 500},false\n")
    return ["--coin", "SOL", "--dates", "20251201", "--lake-root", str(tmp_path / "lake"), "--workers", "1"]


def test_simulate_quotes_end_to_end(tmp_path: Path) -> None:
    common = _lake(tmp_path)
    out = tmp_path / "sim.json"
    args = [*common, "--binance-dir", str(tmp_path / "binance"), "--delay-ms", "100", "--out", str(out)]
    assert simulate_quotes.main(args) == 0
    result = json.loads(out.read_text())
    makers = result["makers"]
    # fifo: the 1.0 sold to an order behind ours fills ours; risk-averse still has 5 ahead
    assert makers["S1/fifo"]["fills"] == 1 and makers["S1/risk_averse"]["fills"] == 0
    assert makers["stale/fifo"]["fills"] == 1  # Binance never moved
    fifo = makers["S1/fifo"]
    assert fifo["spread_bps"] == pytest.approx(0.5)  # bought at 100.00, mid 100.005
    assert fifo["adverse_bps"] == pytest.approx(-1.0) and fifo["inventory_bps"] == pytest.approx(0.0)  # mid 99.995 from 2 s
    assert result["stale_vs_S1"]["fifo"]["days"] == 1


def test_model_strategies_pull_on_the_quote_signals(tmp_path: Path) -> None:
    common = _lake(tmp_path)
    path = quote_signals_path(tmp_path / "signals", "SOL", "20251201")
    path.parent.mkdir(parents=True)
    rows = pq.read_table(HyperliquidLakeLayout(tmp_path / "lake").silver_l2_book_path("SOL", "20251201"))["ts_ns"].to_numpy()
    nan = np.full(rows.size, np.nan)
    # S2 expects its bid's next fill to lose more than 2 bps; S3 cannot score any row
    signals = {
        "ts_ns": rows,
        "s2_q10_bid": np.full(rows.size, -5.0),
        "s2_q10_ask": np.zeros(rows.size),
        "s3_q10_bid": nan,
        "s3_q10_ask": nan,
    }
    pq.write_table(pa.table(signals), path)
    out = tmp_path / "sim.json"
    args = [
        *common,
        "--binance-dir",
        str(tmp_path / "binance"),
        "--delay-ms",
        "100",
        "--signals-dir",
        str(tmp_path / "signals"),
        "--out",
        str(out),
    ]
    assert simulate_quotes.main(args) == 0
    result = json.loads(out.read_text())
    assert result["makers"]["S2/fifo"]["fills"] == 0  # the bid that S1 gets filled on is pulled
    assert result["makers"]["S3/fifo"]["fills"] == 1  # unscored rows keep quoting
    assert result["S2_vs_S1"]["fifo"]["days"] == 1 and "S3_vs_S2" in result and result["signals_dir"] == str(tmp_path / "signals")


def test_hft_baseline_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("hftbacktest")
    from marketimmune.cli import hft_baseline

    out = tmp_path / "hft.json"
    argv = [*_lake(tmp_path), "--out", str(out), "--day-dir", str(tmp_path / "days")]
    assert hft_baseline.main(argv) == 0
    day = tmp_path / "days" / "SOL" / "20251201.json"
    assert day.exists()
    first = json.loads(out.read_text())
    assert first["days_done"] == 1 and first["days_missing"] == []
    day.write_text(day.read_text().replace('"fills": 1,', '"fills": 7,', 1))  # a cached day is read, not simulated again
    assert hft_baseline.main(argv) == 0
    assert json.loads(out.read_text())["makers"]["S1/fifo"]["fills"] == 7
    makers = first["makers"]
    assert set(makers) == {
        "S1/fifo",
        "S1/risk_averse",
        "S1/fifo+l2_crossing",
        "S1/risk_averse+l2_crossing",
        "S1/hftbacktest_risk_adverse",
        "S1/hftbacktest_power_prob3",
    }
    assert makers["S1/fifo"]["fills"] == 1


def test_depth_diffs_send_changes_and_levels_gone_inside_the_range() -> None:
    pytest.importorskip("hftbacktest")
    from marketimmune.sim.hft_baseline import _depth_diffs

    asks = np.array([[101, 102, 0], [102, 103, 0]], dtype=np.int64)
    sizes = np.array([[4.0, 2.0, 0.0], [2.0, 1.0, 0.0]])
    ts, px, qty = _depth_diffs(np.array([1, 2], dtype=np.int64), asks, sizes, bid=False)
    # row 2: 102 unchanged, 103 new, 101 gone from inside the visible range
    assert sorted(zip(ts.tolist(), px.tolist(), qty.tolist(), strict=True)) == [(1, 101, 4.0), (1, 102, 2.0), (2, 101, 0.0), (2, 103, 1.0)]


def test_pull_frontier_limits_and_shifted_placebo(tmp_path: Path) -> None:
    from marketimmune.cli import pull_frontier

    common = _lake(tmp_path)
    path = quote_signals_path(tmp_path / "signals", "SOL", "20251201")
    path.parent.mkdir(parents=True)
    rows = pq.read_table(HyperliquidLakeLayout(tmp_path / "lake").silver_l2_book_path("SOL", "20251201"))["ts_ns"].to_numpy()
    # S2's bid q10 is -3 on the row the fill comes after (1 s) and 0 elsewhere; rolled by half the
    # rows it lands on the next row, so the shifted placebo keeps quoting the bid through the fill
    bid = np.zeros(rows.size)
    bid[1] = -3.0
    pq.write_table(pa.table({"ts_ns": rows, "s2_q10_bid": bid, "s2_q10_ask": np.zeros(rows.size)}), path)
    out = tmp_path / "frontier.json"
    argv = [*common, "--signals-dir", str(tmp_path / "signals"), "--limits", "2,5", "--delay-ms", "100", "--back-off"]
    argv += ["--day-dir", str(tmp_path / "days"), "--out", str(out)]
    assert pull_frontier.main(argv) == 0
    report = json.loads(out.read_text())
    makers = report["makers"]
    assert makers["S1"]["fills"] == 1
    assert makers["s2@2"]["fills"] == 0 and makers["s2@5"]["fills"] == 1  # -3 is below -2, not below -5
    assert makers["s2_shifted@2"]["fills"] == 1 and "s3@2" not in makers
    # the synthetic book shows one level, so stepping back stops quoting the bid as S2 does
    assert makers["s2_back@2"]["fills"] == 0 and makers["s2_back@5"]["fills"] == 1
    assert set(report["back_vs_pull"]) == {"s2_back@2", "s2_back@5"}
    assert (tmp_path / "days" / "SOL" / "20251201.json").exists()
