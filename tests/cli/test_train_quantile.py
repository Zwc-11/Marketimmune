"""End-to-end test of the quantile-ladder trainer on synthetic Gold partitions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.cli import train_quantile
from marketimmune.cli._train_data import use_feature_set
from marketimmune.lake.tables import HyperliquidLakeLayout


def _write_day(layout: HyperliquidLakeLayout, day: int, rng: np.random.Generator) -> None:
    n = 300
    date = f"202512{day:02d}"
    ts = 1_764_547_200_000 + (day - 1) * 86_400_000 + np.sort(rng.uniform(0, 8.6e7, n))
    ofi = rng.normal(size=n)
    side = rng.choice([-1.0, 1.0], n)
    markout = -2.0 * side * ofi + rng.normal(scale=0.5, size=n)
    frame = pd.DataFrame(
        {
            "coin": "SOL",
            "ts_ms": ts,
            "px": 100.0,
            "sz": rng.uniform(0.1, 5, n),
            "maker_side": side,
            "l2_mid": 100.0,
            "l2_spread_bps": 1.0,
            "l2_microprice": 100.0,
            "l2_top_imbalance": rng.normal(size=n),
            "l2_ofi_event": ofi,
            "l2_ofi_1s": ofi,
            "l2_ofi_5s": ofi,
            "l2_ofi_10s": ofi,
            "markout_bps_1s": markout,
            "toxic_1s": markout < -1.0,
            "oid": np.arange(n),
        }
    )
    frame["feature_ts_ms"] = frame["ts_ms"] - 1.0
    path = layout.gold_training_path("SOL", date)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    path.with_suffix(".leakage.json").write_text(json.dumps({"passed": True}))


def test_train_quantile_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    for day in range(1, 5):
        _write_day(layout, day, rng)
    report = tmp_path / "eval" / "q.json"
    try:
        code = train_quantile.main(
            [
                "--dates",
                "20251201..20251204",
                "--lake-root",
                str(tmp_path / "lake"),
                "--feature-set",
                "l0_book",
                "--train-days",
                "2",
                "--n-estimators",
                "40",
                "--min-child-samples",
                "20",
                "--report",
                str(report),
                "--contrib",
            ]
        )
    finally:
        use_feature_set("l0")
    assert code == 0
    payload = json.loads(report.read_text())
    assert payload["leakage_safe"] is True and payload["rows_tested"] == 600
    assert payload["per_tau"]["q50"]["skill"] > 0.3
    oof = pd.read_parquet(tmp_path / "eval" / "q.oof.parquet")
    assert {"q10", "q50", "q90", "clim_q50", "markout_bps", "oid", "contrib_bias"} <= set(oof.columns)
    assert "Wrote" in capsys.readouterr().out
