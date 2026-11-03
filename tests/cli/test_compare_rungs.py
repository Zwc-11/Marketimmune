"""Tests for the OOF export and the rung-comparison CLI."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.cli import compare_rungs, mcs_rungs
from marketimmune.cli.train import write_oof_predictions


def _gold_frame(n_days: int = 4, per_day: int = 50, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = n_days * per_day
    return pd.DataFrame(
        {
            "ts_ms": np.arange(n) * 1000.0,
            "partition_coin": "SOL",
            "partition_date": np.repeat([f"202512{d + 1:02d}" for d in range(n_days)], per_day),
            "px": 100.0,
            "sz": 1.0,
            "maker_side": rng.choice([-1, 1], n),
            "oid": np.arange(n) // 2,  # two fills per taker order: duplicates on the key
            "liquidation": np.arange(n) % 10 == 0,
            "cex_ret_1000ms_bps": rng.normal(scale=3.0, size=n),
            "forced_same_notional_60000ms": np.where(np.arange(n) % 7 == 0, 5e3, 0.0),
            "forced_opp_notional_60000ms": 0.0,
            "toxic_1s": rng.random(n) < 0.4,
            "markout_bps_1s": rng.normal(size=n),
        }
    )


def test_oof_export_and_comparison(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frame = _gold_frame()
    y = frame["toxic_1s"].to_numpy()
    good = np.where(y, 0.8, 0.2)
    paths = {}
    for name, prob in (("base", np.full(len(frame), 0.4)), ("chal", good)):
        paths[name] = write_oof_predictions(
            tmp_path / f"{name}.oof.parquet",
            frame,
            horizon="1s",
            probabilities=prob,
            raw_probabilities=prob,
            baseline_probabilities=prob,
            feature_set=name,
        )
    oof = pd.read_parquet(paths["chal"])
    assert {"oid", "liquidation", "cex_ret_1000ms_bps", "label", "prob"} <= set(oof.columns)

    # the challenger dropped a few rows (missing features): compare on the overlap
    pd.read_parquet(paths["chal"]).iloc[5:].to_parquet(paths["chal"])
    assert compare_rungs.main(["--base", str(paths["base"]), "--challenger", str(paths["chal"])]) == 0
    out = json.loads((tmp_path / "chal_vs_base.json").read_text())
    assert out["rows_matched"] == len(frame) - 5
    assert out["all"]["days_improved"] == 4 and out["all"]["diebold_mariano"]["t_stat"] > 0
    assert {"cex_move", "quiet", "taker_liquidation", "forced_60s"} <= set(out)
    assert out["forced_60s"]["rows"] == sum(1 for i in range(len(frame)) if i % 7 == 0) - 1
    assert "Wrote" in capsys.readouterr().out


def test_align_rejects_mismatched_labels() -> None:
    a = pd.DataFrame({"partition_date": ["d"], "ts_ms": [1.0], "label": [True], "prob": [0.5]})
    b = a.assign(label=[False])
    with pytest.raises(AssertionError, match="labels disagree"):
        compare_rungs.align(a, b)
    with pytest.raises(AssertionError, match="ts_ms"):
        compare_rungs.align(a.drop(columns="ts_ms"), b.drop(columns="ts_ms"))


def test_pinball_comparison_on_quantile_oof(tmp_path: Path) -> None:
    frame = _gold_frame()
    paths = {}
    for name, q10 in (("base", 5.0), ("chal", -1.3)):
        out = frame[["ts_ms", "partition_date", "px", "sz", "maker_side", "oid"]].copy()
        out["label"] = frame["toxic_1s"]
        out["markout_bps"] = frame["markout_bps_1s"]
        out["q10"] = q10
        paths[name] = tmp_path / f"{name}.oof.parquet"
        out.to_parquet(paths[name])
    assert compare_rungs.main(["--loss", "pinball", "--tau", "0.1", "--base", str(paths["base"]), "--challenger", str(paths["chal"])]) == 0
    result = json.loads((tmp_path / "chal_vs_base.json").read_text())
    assert result["tau"] == 0.1 and result["all"]["days_improved"] == 4


def test_mcs_rungs_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frame = _gold_frame(n_days=6, per_day=80, seed=3)
    y = frame["toxic_1s"].to_numpy()
    rng = np.random.default_rng(4)
    probs = {
        "good": np.clip(np.where(y, 0.8, 0.2) + rng.normal(0, 0.05, y.size), 0.01, 0.99),
        "good_too": np.clip(np.where(y, 0.8, 0.2) + rng.normal(0, 0.05, y.size), 0.01, 0.99),
        "flat": np.full(y.size, 0.4),
    }
    paths = []
    for name, prob in probs.items():
        paths.append(
            write_oof_predictions(
                tmp_path / f"{name}.oof.parquet",
                frame,
                horizon="1s",
                probabilities=prob,
                raw_probabilities=prob,
                baseline_probabilities=prob,
                feature_set=name,
            )
        )
    assert mcs_rungs.main([*map(str, paths), "--n-boot", "500"]) == 0
    out = json.loads((tmp_path / "mcs_brier.json").read_text())
    assert out["days"] == 6 and out["elimination_order"][0] == "flat"
    assert "flat" not in out["included"]
    assert "IN " in capsys.readouterr().out
    with pytest.raises(AssertionError, match="at least two"):
        mcs_rungs.main([str(paths[0])])


def test_mcs_common_rows_rejects_mismatched_targets() -> None:
    a = pd.DataFrame({"partition_date": ["d"], "ts_ms": [1.0], "label": [True], "prob": [0.5]})
    with pytest.raises(AssertionError, match="targets disagree"):
        mcs_rungs.common_rows({"a": a, "b": a.assign(label=[False])}, target="label", prediction="prob")
