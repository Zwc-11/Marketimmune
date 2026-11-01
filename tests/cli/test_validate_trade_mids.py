from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from marketimmune.cli import validate_trade_mids
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.priority.fees import fill_markouts
from tests.priority.test_fees import _legs


def test_joins_gold_and_compares(tmp_path: Path) -> None:
    legs = _legs()
    node = tmp_path / "node" / "SOL"
    node.mkdir(parents=True)
    legs.write_parquet(node / "SOL-20260501.parquet")
    trades = fill_markouts(legs, None, validate_trade_mids.HORIZONS_S)
    # Gold as if the book agreed with the trade-implied mid, plus a row with no node trade
    gold = trades.select(
        pl.col("time_ms").alias("ts_ms"), "px", "sz", pl.col("taker_oid").cast(pl.Int64).alias("oid"),
        pl.lit(-1.0).alias("cex_gap_maker_bps"),
        *(pl.col(f"{k}_{h:g}s").alias(f"markout{g}_bps_{h:g}s") for h in validate_trade_mids.HORIZONS_S for k, g in (("adv", ""), ("mo", "_px"))),
    )  # fmt: skip
    gold = pl.concat([gold, gold.head(1).with_columns(pl.col("oid") + 999)])
    path = HyperliquidLakeLayout(tmp_path / "lake").gold_training_path("SOL", "20260501")
    path.parent.mkdir(parents=True)
    gold.write_parquet(path)
    out = tmp_path / "v.json"
    argv = [
        "--coins",
        "SOL",
        "--dates",
        "20260501",
        "--lake-root",
        str(tmp_path / "lake"),
        "--node-dir",
        str(tmp_path / "node"),
        "--out",
        str(out),
    ]
    assert validate_trade_mids.main(argv) == 0
    r = json.loads(out.read_text())["coins"]["SOL"]
    assert r["trades"] == trades.height
    assert r["mo_10s"]["mean_abs_diff"] == 0.0 and r["by_cex_gap"][1]["trades"] == trades.height
