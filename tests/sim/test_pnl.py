"""Tests for the maker PnL attribution and the policy simulator CLI."""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from marketimmune.cli import simulate_policy
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.sim.pnl import (
    CostModel,
    compare_policies,
    daily_policy_pnl,
    fill_components,
    policy_mask,
    summarise,
)


def _gold() -> pd.DataFrame:
    return pd.DataFrame({
        "px": [99.99, 100.01, 99.98], "maker_side": [1.0, -1.0, 1.0],
        "mid_before": [100.0, 100.0, 100.0], "markout_bps_10s": [-2.0, 0.5, -10.0],
    })


def test_components_add_up() -> None:
    comps = fill_components(_gold(), "10s", CostModel(maker_fee_bps=1.0, hedge_cost_bps=0.5))
    assert comps["spread"].tolist() == pytest.approx([1.0, 1.0, 2.0])
    assert comps["total"].tolist() == pytest.approx([-2.5, 0.0, -9.5])
    with pytest.raises(ValueError, match="missing"):
        fill_components(_gold().drop(columns="mid_before"), "10s", CostModel())


def test_daily_pnl_summary_and_policies() -> None:
    costs = CostModel(notional_usd=1_000.0)
    comps = fill_components(_gold(), "10s", costs)
    days = np.array(["d1", "d1", "d2"])
    all_ = daily_policy_pnl(comps, days, [True, True, True], costs)
    assert all_["fills"].tolist() == [2, 1]
    assert all_["pnl_usd"].tolist() == pytest.approx([0.05, -0.8])
    s = summarise(all_)
    assert s["fills"] == 3 and s["total_bps"] == pytest.approx((-1.0 + 1.5 - 8.0) / 3)
    skip = policy_mask(pd.DataFrame({"q10": [-1.0, np.nan, -9.0]}),
                       {"kind": "quantile", "column": "q10", "limit_bps": 2.0})
    assert skip.tolist() == [True, True, False]
    prob = policy_mask(pd.DataFrame({"p": [0.2, 0.7]}), {"kind": "prob", "column": "p",
                                                         "threshold": 0.6})
    assert prob.tolist() == [True, False]
    assert policy_mask(_gold(), {"kind": "all"}).all()
    gap = pd.DataFrame({"g": [-3.0, -2.0, 0.5, np.nan]})
    assert policy_mask(gap, {"kind": "rule", "column": "g", "op": "le",
                             "threshold": -2.0}).tolist() == [False, False, True, True]
    assert policy_mask(gap, {"kind": "rule", "column": "g", "op": "ge",
                             "threshold": 0.0}).tolist() == [True, True, False, True]
    with pytest.raises(ValueError, match="op must be"):
        policy_mask(gap, {"kind": "rule", "column": "g", "op": "lt", "threshold": 0.0})
    with pytest.raises(ValueError, match="unknown policy"):
        policy_mask(_gold(), {"kind": "magic"})
    pol = daily_policy_pnl(comps, days, skip, costs)
    cmp_ = compare_policies(all_, pol)
    assert cmp_["days"] == 1 and cmp_["mean_daily_usd"] == pytest.approx(0.0)
    assert summarise(daily_policy_pnl(comps, days, [False] * 3, costs)) == {"days": 0, "fills": 0}


def test_cli_s1_and_policy(tmp_path: Path) -> None:
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    rng = np.random.default_rng(0)
    oof_rows = []
    for day in range(1, 5):
        n = 200
        side = rng.choice([-1.0, 1.0], n)
        markout = rng.normal(-1.0, 2.0, n)
        frame = pd.DataFrame({
            "ts_ms": np.arange(n) * 1000.0 + day * 86_400_000, "px": 100.0 - side * 0.01,
            "sz": 1.0, "maker_side": side, "mid_before": 100.0, "oid": np.arange(n),
            "markout_bps_10s": markout, "markout_bps_1s": markout,
            # a stale-quote signal that sees the worst fills, missing on the first day
            "gap": np.where(markout < -3.0, -5.0, 0.0) if day > 1 else np.nan,
        })
        path = layout.gold_training_path("SOL", f"202512{day:02d}")
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
        if day > 1:  # predictions exist only on test days; q10 is informative
            oof_rows.append(frame.assign(partition_date=f"202512{day:02d}",
                                         q10=np.where(markout < -3.0, -6.0, 0.0)))
    oof = tmp_path / "q.oof.parquet"
    pd.concat(oof_rows).to_parquet(oof)
    out = tmp_path / "pnl.json"
    assert simulate_policy.main(["--dates", "20251201..20251204", "--lake-root",
                                 str(tmp_path / "lake"), "--out", str(out)]) == 0
    s1 = json.loads(out.read_text())["10s"]["S1_quote_all"]
    assert s1["fills"] == 800 and s1["spread_bps"] == pytest.approx(1.0)
    assert simulate_policy.main(["--dates", "20251201..20251204", "--lake-root",
                                 str(tmp_path / "lake"), "--oof", str(oof), "--out", str(out),
                                 "--horizons", "10s"]) == 0
    res = json.loads(out.read_text())["10s"]
    assert res["S1_quote_all"]["fills"] == 600
    assert res["policy_vs_S1"]["days_better"] == 3 and res["policy"]["total_bps"] > 0
    # model-free rule on a Gold column, scored where the column exists
    assert simulate_policy.main(["--dates", "20251201..20251204", "--lake-root",
                                 str(tmp_path / "lake"), "--policy", "rule", "--column", "gap",
                                 "--op", "le", "--threshold", "-2", "--out", str(out),
                                 "--horizons", "10s"]) == 0
    res = json.loads(out.read_text())["10s"]
    assert res["S1_quote_all"]["fills"] == 600 and res["policy_vs_S1"]["days_better"] == 3
    with pytest.raises(SystemExit, match="no column"):
        simulate_policy.main(["--dates", "20251201..20251204", "--lake-root",
                              str(tmp_path / "lake"), "--policy", "rule", "--column", "nope"])
    with pytest.raises(SystemExit):
        simulate_policy.main(["--dates", "20250101", "--lake-root", str(tmp_path / "none")])


def test_recompute_cex_with_a_longer_delay(tmp_path: Path) -> None:
    day0 = 1_764_547_200_000.0  # 2025-12-01 00:00 UTC
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    l2 = layout.silver_l2_book_path("SOL", "20251201")
    l2.parent.mkdir(parents=True)
    pd.DataFrame({"ts_ms": [day0, day0 + 1_000.0], "mid": [100.0, 100.0]}).to_parquet(l2)
    binance = tmp_path / "binance" / "SOLUSDT"
    binance.mkdir(parents=True)
    with zipfile.ZipFile(binance / "SOLUSDT-aggTrades-2025-12-01.zip", "w") as zf:
        zf.writestr("x.csv", "".join(f"{i},{px},1,{i},{i},{int(day0 + dt)},false\n" for i, (px, dt)
                                     in enumerate([(100.0, -5_000), (100.0, 500), (101.0, 1_500)])))
    gold = pd.DataFrame({"ts_ms": [day0 + 2_000.0], "maker_side": [1.0],
                         "partition_date": ["20251201"]})
    fast = simulate_policy.recompute_cex(gold, layout, "SOL", tmp_path / "binance", 300.0)
    slow = simulate_policy.recompute_cex(gold, layout, "SOL", tmp_path / "binance", 1_000.0)
    # Binance rose 1% between the last HL mid change and the fill: seen at 300 ms, not at 1 s
    assert fast["cex_gap_maker_bps"].iloc[0] == pytest.approx(1e4 * math.log(1.01))
    assert slow["cex_gap_maker_bps"].iloc[0] == pytest.approx(0.0)
    none = simulate_policy.recompute_cex(gold, layout, "SOL", tmp_path / "missing", 300.0)
    assert math.isnan(none["cex_gap_maker_bps"].iloc[0])
