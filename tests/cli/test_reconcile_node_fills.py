from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.cli import reconcile_node_fills
from marketimmune.cli.reconcile_node_fills import node_trades, reconcile_day, runs
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.priority.fills import to_frame

DAY = 1_765_756_800_000  # 2025-12-15 00:00 UTC


def _legs(trades: list[tuple[int, int, int, float]]) -> pl.DataFrame:
    """Node legs for (tid, ts_ms, maker_oid, px): a taker buys 1 from the maker."""
    records = []
    for tid, ts, maker_oid, px in trades:
        for crossed, oid, side in ((True, maker_oid + 1000, "B"), (False, maker_oid, "A")):
            records.append(
                {
                    "block_number": ts,
                    "block_time": "2025-12-15T00:00:00.000000000",
                    "local_time": "2025-12-15T00:00:00.000000000",
                    "user": "0x1",
                    "coin": "SOL",
                    "px": px,
                    "sz": 1.0,
                    "side": side,
                    "time_ms": ts,
                    "start_position": 0.0,
                    "dir": "",
                    "closed_pnl": 0.0,
                    "hash": "0x0",
                    "oid": oid,
                    "crossed": crossed,
                    "fee": 0.0,
                    "fee_token": "USDC",
                    "tid": tid,
                    "cloid": None,
                    "twap_id": None,
                    "liquidation": False,
                    "liquidated_user": None,
                    "liquidation_mark_px": None,
                    "liquidation_method": None,
                    "builder_fee": None,
                    "priority_gas": None,
                }
            )
    return to_frame(records)


def _albers(trades: list[tuple[int, int, float]]) -> pl.DataFrame:
    """Albers Silver rows for (ts_ms, maker_oid, px)."""
    return pl.DataFrame(
        {
            "ts_ms": [t for t, _, _ in trades],
            "maker_oid": [m for _, m, _ in trades],
            "taker_oid": [m + 1000 for _, m, _ in trades],
            "px": [p for _, _, p in trades],
            "sz": [1.0] * len(trades),
            "taker_side": ["B"] * len(trades),
            "liquidation": [False] * len(trades),
        }
    )


def test_runs_split_on_a_minute() -> None:
    assert runs(np.array([5, 1, 60_006, 200_000], dtype=np.int64)) == [(1, 5, 2), (60_006, 60_006, 1), (200_000, 200_000, 1)]
    assert runs(np.zeros(0, dtype=np.int64)) == []


def test_reconcile_day_matches_counts_differences_and_finds_the_gap() -> None:
    gap = [(10 + k, DAY + 3_600_000 + k * 1_000, 500 + k, 100.0) for k in range(3)]  # an hour in, three trades Albers lacks
    late = (99, DAY + 86_400_000 - 200, 900, 101.0)  # 23:59:59.800, filed under the next date by Albers
    node = node_trades(_legs([(1, DAY + 1_000, 1, 100.0), (2, DAY + 2_000, 2, 100.5), *gap, late]))
    albers = _albers([(DAY + 1_000, 1, 100.0), (DAY + 2_000, 2, 100.6)])  # same trade, another price
    l2 = np.array([DAY + 1_000, DAY + 3_601_500], dtype=np.int64)
    r = reconcile_day(node, albers, l2, DAY)
    assert (r["node"], r["albers"], r["matched"], r["node_only"], r["albers_only"]) == (6, 2, 2, 4, 0)
    assert r["differ"] == {"ts_ms": 0, "px": 1, "sz": 0, "taker_side": 0, "liquidation": 0}
    assert r["boundary"] == {"node_only": 1, "albers_only": 0}
    (w,) = r["windows"]
    assert (w["trades"], w["albers_stops_ms"], w["albers_resumes_ms"], w["l2_rows_inside"]) == (3, DAY + 2_000, None, 1)


def test_cli(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    node_dir = tmp_path / "node"
    (node_dir / "SOL").mkdir(parents=True)
    _legs([(1, DAY + 1_000, 1, 100.0), (2, DAY + 9_000, 2, 100.0)]).write_parquet(node_dir / "SOL" / "SOL-20251215.parquet")
    for path, table in (
        (layout.silver_fills_path("SOL", "20251215"), _albers([(DAY + 1_000, 1, 100.0)]).to_arrow()),
        (layout.silver_l2_book_path("SOL", "20251215"), pa.table({"ts_ms": [DAY]})),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
    out = tmp_path / "r.json"
    argv = ["--coins", "SOL", "--dates", "20251215", "--lake-root", str(tmp_path / "lake"), "--node-dir", str(node_dir), "--out", str(out)]
    assert reconcile_node_fills.main(argv) == 0
    total = json.loads(out.read_text())["coins"]["SOL"]["total"]
    assert (total["matched"], total["node_only"], total["windows"], total["window_trades"]) == (1, 1, 1, 1)
