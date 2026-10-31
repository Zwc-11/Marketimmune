"""Tests for the latency-arb / forced / residual decomposition."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.cli import decompose, train_quantile
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.models.decomposition import (
    contribution_shares,
    feature_group,
    feature_groups,
    group_contributions,
    realised_decomposition,
)
from marketimmune.models.quantile_ladder import LgbParams, train_quantile_oof


def test_groups_by_prefix() -> None:
    cols = ["cex_gap_bps", "race_lost_same_n_250ms", "fc_same_15s", "forced_opp_notional_1000ms", "taker_tox_1s", "l2_spread_bps"]
    assert [feature_group(c) for c in cols] == ["latency_arb", "latency_arb", "forced", "forced", "wallet", "state"]
    assert feature_groups(cols) == {"latency_arb": [0, 1], "forced": [2, 3], "wallet": [4], "state": [5]}


def test_group_contributions_and_shares() -> None:
    raw = np.array([[-1.0, -2.0, 0.5, 9.0], [1.0, 0.0, 0.0, 9.0]])
    g = group_contributions(raw, {"latency_arb": [0], "forced": [1], "wallet": [], "state": [2]})
    assert g["bias"].tolist() == [9.0, 9.0] and g["wallet"].tolist() == [0.0, 0.0]
    contrib = {
        "latency_arb": np.array([-1.0, -3.0, 1.0, -2.0]),
        "forced": np.array([-1.0, 0.0, 0.0, -2.0]),
        "wallet": np.zeros(4),
        "state": np.array([0.0, 1.0, 0.0, 0.0]),
    }
    res = contribution_shares(contrib, ["a", "b", "c", "d"], n_boot=200)
    # fills predicted worse than baseline: 0 (-2), 1 (-2), 3 (-4); total -8
    assert res["fills"] == 3
    sh = res["shares"]
    assert sh["latency_arb"]["share"] == pytest.approx(6 / 8)
    assert sh["forced"]["share"] == pytest.approx(3 / 8)
    assert sh["state"]["share"] == pytest.approx(-1 / 8)
    assert sh["plan_residual"]["share"] == pytest.approx(-1 / 8)
    assert sum(sh[g]["share"] for g in ("latency_arb", "forced", "wallet", "state")) == pytest.approx(1.0)
    assert "bootstrap_ci_95" in sh["forced"]
    assert contribution_shares(contrib, list("abcd"), mask=np.zeros(4, bool))["fills"] == 0


def test_contributions_from_lightgbm_add_up() -> None:
    rng = np.random.default_rng(0)
    n = 3_000
    x = rng.normal(size=(n, 3))
    y = -2.0 * (x[:, 0] > 1.0) + 0.1 * rng.normal(size=n)
    ts = np.repeat(np.arange(3) * 86_400_000.0, n // 3) + np.tile(np.arange(n // 3), 3) * 1000.0
    oof = train_quantile_oof(
        x,
        y,
        ts,
        taus=(0.5,),
        train_days=1,
        params=LgbParams(n_estimators=30, min_child_samples=20),
        contrib_tau=0.5,
        contrib_groups={"latency_arb": [0], "forced": [1], "wallet": [], "state": [2]},
    )
    tested = oof.tested
    c = oof.contributions
    total = c["bias"] + c["latency_arb"] + c["forced"] + c["wallet"] + c["state"]
    assert np.allclose(total[tested], oof.predictions[0.5][tested], atol=1e-6)
    hot = tested & (x[:, 0] > 1.0)
    assert c["latency_arb"][hot].mean() < -1.0 and abs(c["forced"][hot].mean()) < 0.2


def test_realised_decomposition_by_regime() -> None:
    fr = pd.DataFrame(
        {
            "px": [99.99, 100.01, 99.99, 100.0],
            "sz": [10.0, 10.0, 10.0, 10.0],
            "maker_side": [1.0, -1.0, 1.0, 1.0],
            "mid_before": [100.0] * 4,
            "markout_bps_1s": [-5.0, 0.0, -1.0, np.nan],
            "cex_gap_maker_bps": [-3.0, 0.0, 0.0, 0.0],
            "forced_same_notional_60000ms": [0.0, 0.0, 5e3, 0.0],
            "forced_opp_notional_60000ms": [0.0, 0.0, 0.0, 0.0],
        }
    )
    res = realised_decomposition(fr, "1s")
    assert res["fills"] == 3
    r = res["regimes"]
    assert r["stale"]["fill_share"] == pytest.approx(1 / 3)
    assert r["stale"]["adverse_share"] == pytest.approx(5 / 6, rel=1e-3)
    assert r["forced"]["adverse_bps"] == pytest.approx(-1.0)
    assert r["quiet"]["spread_bps"] == pytest.approx(1.0)
    assert r["stale+forced"]["fill_share"] == 0.0


def test_cli_realised_and_model(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    path = layout.gold_training_path("SOL", "20251201")
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "ts_ms": [1.0, 2.0],
            "px": [99.99, 100.01],
            "sz": [1.0, 1.0],
            "maker_side": [1.0, -1.0],
            "mid_before": [100.0, 100.0],
            "oid": [1, 2],
            "tid": [None, None],
            "markout_bps_1s": [-2.0, 1.0],
            "markout_bps_10s": [-2.0, 1.0],
            "markout_bps_60s": [-2.0, 1.0],
            "cex_gap_maker_bps": [-4.0, 0.0],
            "forced_same_notional_60000ms": [0.0, 0.0],
            "forced_opp_notional_60000ms": [0.0, np.nan],
        }
    ).to_parquet(path)
    out = tmp_path / "d.json"
    assert decompose.main(["--dates", "20251201", "--lake-root", str(tmp_path / "lake"), "--horizons", "1s", "--out", str(out)]) == 0
    res = json.loads(out.read_text())
    assert res["1s"]["regimes"]["stale"]["fill_share"] == 0.5
    oof = pd.DataFrame(
        {
            "partition_date": ["d1", "d2", "d3"] * 2,
            "cex_ret_1000ms_bps": [3.0, 0.0, 0.0] * 2,
            **{f"contrib_{g}": [-1.0, -0.5, 0.2] * 2 for g in ("latency_arb", "forced", "wallet", "state")},
        }
    )
    oof_path = tmp_path / "q.oof.parquet"
    oof.to_parquet(oof_path)
    assert decompose.main(["--oof", str(oof_path)]) == 0
    res = json.loads(oof_path.with_suffix(".decomposition.json").read_text())
    assert res["all"]["fills"] == 4 and res["cex_move"]["fills"] == 2
    oof.drop(columns="contrib_forced").to_parquet(oof_path)
    with pytest.raises(SystemExit, match="no contributions"):
        decompose.main(["--oof", str(oof_path)])
    assert train_quantile.parse_args(["--no-contrib"]).no_contrib
