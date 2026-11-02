"""Gold from node fills, the wallet stage, one A1 rung, and the A1 scorer, on a tiny lake."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from marketimmune.cli import a1_ladder, a1_report, build_node_gold, score_a1
from marketimmune.cli._train_data import use_feature_set
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.priority.fills import to_frame
from marketimmune.utils import parse_date_spec

DATES = parse_date_spec("20260601..20260609")


def _day_legs(date: str, rng: np.random.Generator, block0: int) -> pl.DataFrame:
    start = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    px = 100.0
    for k in range(300):
        t = start + timedelta(seconds=5 + k * 0.25)
        stamp = t.strftime("%Y-%m-%dT%H:%M:%S.%f000")
        buy = bool(rng.random() < 0.5)
        px = round(px + (0.01 if buy else -0.01) * rng.integers(0, 3), 2)
        tid = block0 + k
        gas = float(rng.uniform(0, 1e-5)) if rng.random() < 0.2 else None
        for crossed in (True, False):
            rows.append({
                "block_number": block0 + k, "block_time": stamp, "local_time": stamp, "user": f"0x{rng.integers(0, 12) if crossed else 99}",
                "coin": "SOL", "px": px, "sz": 1.0, "side": ("B" if buy else "A") if crossed else ("A" if buy else "B"),
                "time_ms": int(t.timestamp() * 1000), "start_position": 0.0, "dir": "", "closed_pnl": 0.0, "hash": "0x0",
                "oid": tid * 2 + crossed, "crossed": crossed, "fee": 0.0, "fee_token": "USDC", "tid": tid, "cloid": None,
                "twap_id": None, "liquidation": crossed and k % 97 == 0, "liquidated_user": None, "liquidation_mark_px": None,
                "liquidation_method": None, "builder_fee": None, "priority_gas": gas if crossed else None,
            })  # fmt: skip
    return to_frame(rows)


def _lake(tmp_path: Path) -> list[str]:
    rng = np.random.default_rng(0)
    node = tmp_path / "node" / "SOL"
    node.mkdir(parents=True)
    for i, date in enumerate(DATES):
        _day_legs(date, rng, 1_000 * (i + 1)).write_parquet(node / f"SOL-{date}.parquet")
    candles = tmp_path / "candles"
    candles.mkdir()
    t0 = int(datetime(2026, 5, 31, tzinfo=UTC).timestamp() * 1000)
    pl.DataFrame({"t": [t0 + h * 3_600_000 for h in range(24 * 11)], "o": 40.0, "h": 41.0, "l": 39.0, "c": 40.0}).write_parquet(
        candles / "HYPE-1h.parquet"
    )
    binance = tmp_path / "binance" / "SOLUSDT"
    binance.mkdir(parents=True)
    for date in ("20260531", *DATES):
        day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC)
        ms = [int((day + timedelta(seconds=s)).timestamp() * 1000) for s in range(0, 120, 2)]
        csv = "".join(f"{i},{100 + 0.01 * (i % 7):.2f},1,{i},{i},{m},false\n" for i, m in enumerate(ms))
        with zipfile.ZipFile(binance / f"SOLUSDT-aggTrades-{date[:4]}-{date[4:6]}-{date[6:]}.zip", "w") as zf:
            zf.writestr("x.csv", csv)
    return [
        "--coin",
        "SOL",
        "--lake-root",
        str(tmp_path / "lake"),
        "--node-dir",
        str(tmp_path / "node"),
        "--candles-dir",
        str(candles),
        "--binance-dir",
        str(tmp_path / "binance"),
    ]


def test_day_and_wallet_stages_then_one_rung(tmp_path: Path) -> None:
    common = _lake(tmp_path)
    assert build_node_gold.main([*common, "--dates", "20260601..20260609"]) == 0
    assert build_node_gold.main([*common, "--dates", "20260601..20260609", "--stage", "wallet"]) == 0
    layout = HyperliquidLakeLayout(tmp_path / "lake")
    gold = pl.read_parquet(layout.gold_training_path("SOL", "20260605"))
    assert gold.height == 300 and {"fp_same_10b", "cex_gap_maker_bps", "taker_tox_10s", "markout_bps_10s", "toxic_10s", "l2_mid"} <= set(
        gold.columns
    )
    assert float(gold["taker_fee_prio_bps"].fill_null(0).sum()) > 0 and (gold["fp_same_30b"] > 0).any()
    report = json.loads(layout.gold_training_path("SOL", "20260605").with_suffix(".leakage.json").read_text())
    assert report["passed"] and report["trade"]["passed"] and report["cex"]["passed"] and report["wallet"]["passed"]
    out = tmp_path / "eval"
    argv = [
        "--coin",
        "SOL",
        "--rung",
        "l3_fee",
        "--test-dates",
        "20260608,20260609",
        "--first-gold",
        "20260601",
        "--lake-root",
        str(tmp_path / "lake"),
    ]
    argv += ["--out", str(out), "--models-dir", str(tmp_path / "models")]
    try:
        assert a1_ladder.main([*argv, "--model", "quantile", "--extra", "--n-estimators 2"]) == 0
        summary = json.loads((out / "q_a1_sol_l3_fee.json").read_text())
        assert summary["tested_days"] == 2 and summary["leakage_safe"] and [d["seed"] for d in summary["days"]] == [42, 43]
        oof = pl.read_parquet(out / "q_a1_sol_l3_fee.oof.parquet")
        assert oof["partition_date"].unique().sort().to_list() == ["20260608", "20260609"]
        # a rerun resumes from the per-day files
        assert a1_ladder.main([*argv, "--model", "quantile", "--extra", "--n-estimators 2"]) == 0
    finally:
        use_feature_set("l0")  # the training CLIs select the rung's columns in place


def _report(improvement: float, p: float, lo: float, placebo_p: float = 0.5) -> dict[str, Any]:
    regime = {
        "mean_daily_improvement": improvement,
        "days": 60,
        "days_improved": 40,
        "diebold_mariano": {"t_stat": 3.0, "p_value": p},
        "bootstrap_ci_95": [lo, lo + 1],
    }
    return {"all": regime, "cex_move": regime, "quiet": {**regime, "diebold_mariano": {"t_stat": 0.1, "p_value": placebo_p}}}


def test_score_a1_claims(tmp_path: Path) -> None:
    good, flat = _report(0.01, 1e-6, 0.005), _report(-0.001, 0.4, -0.01)
    for prefix in ("", "q_"):
        for coin, a2 in (("BTC", good), ("ETH", good), ("SOL", flat)):
            for (c, b), rep in (
                (("l3_fee", "l2_trade"), a2), (("l1_trade", "l0_trade"), good), (("l2_trade", "l1_trade"), good), (("l3_fee_placebo", "l2_trade"), flat),
            ):  # fmt: skip
                (tmp_path / score_a1.report_name(prefix, coin, c, b)).write_text(json.dumps(rep))
    r = score_a1.score(tmp_path, ("BTC", "ETH", "SOL"))
    assert r["held"]["A2"] == {"BTC": True, "ETH": True, "SOL": False}
    assert not r["claims"]["fees_beyond_cex_gap_and_wallet"]  # SOL's point estimate is negative
    assert r["claims"]["gate_a1_passes"] and r["claims"]["replication_a3_coins"] == 3
    # a significant placebo blocks A1 and A2
    (tmp_path / score_a1.report_name("", "BTC", "l3_fee_placebo", "l2_trade")).write_text(
        json.dumps(_report(0.01, 1e-6, 0.005, placebo_p=0.01))
    )
    assert not score_a1.score(tmp_path, ("BTC", "ETH", "SOL"))["held"]["A2"]["BTC"]


@pytest.mark.parametrize("coin", ["SOL"])
def test_report_names(coin: str) -> None:
    assert score_a1.report_name("q_", coin, "l3_fee", "l2_trade") == "q_a1_sol_l3_fee_vs_q_a1_sol_l2_trade.json"


def test_a1_report_renders_every_section(tmp_path: Path) -> None:
    good, flat = _report(0.01, 1e-6, 0.005), _report(-0.001, 0.4, -0.01)
    coins = ("BTC", "ETH", "SOL")
    for period in ("confirmation", "discovery"):
        d = tmp_path / period
        d.mkdir()
        for prefix in ("", "q_"):
            for coin in coins:
                for (c, b), rep in (
                    (("l3_fee", "l2_trade"), good), (("l1_trade", "l0_trade"), good), (("l2_trade", "l1_trade"), good), (("l3_fee_placebo", "l2_trade"), flat),
                ):  # fmt: skip
                    (d / score_a1.report_name(prefix, coin, c, b)).write_text(json.dumps(rep))
        for coin in coins:
            models = [
                {"name": f"a1_{coin.lower()}_{r}", "in_mcs": r == "l3_fee", "mcs_p_value": 1.0 if r == "l3_fee" else 0.01}
                for r in a1_report.RUNGS
            ]
            for m in ("brier", "pinball_q10"):
                (d / f"mcs_{m}_a1_{coin.lower()}.json").write_text(json.dumps({"models": models}))
        out = "a1_verdicts.json" if period == "confirmation" else "a1_discovery_exploratory.json"
        (tmp_path / out).write_text(json.dumps(score_a1.score(d, coins)))
    (tmp_path / "a1_sol_l3_fee.json").write_text(json.dumps({"tested_days": 77, "rows_tested": 1234, "leakage_safe": True}))
    text = a1_report.render(tmp_path, coins)
    assert "`gate_a1_passes`: True" in text and text.count("| A1: `l3_fee` vs `l2_trade`, cex_move |") == 6
    assert "**+10.000 [+5.000, +1005.000], 40/60, p <1e-4 (Holm <1e-4), placebo min p 0.4**" in text  # Brier x1e-3
    assert "| SOL | brier | `l3_fee` (1.00) |" in text and "| SOL | classifier | `l3_fee` | 77 | 1,234 | True |" in text
    assert "(no `a1_verdicts.json` yet)" not in text and "(no discovery scoring yet)" not in text


def test_a1_lead_time_counts_blocks_since_a_fee_on_the_same_side() -> None:
    from marketimmune.cli import a1_lead_time

    block = np.array([10, 11, 12, 12, 13, 50], dtype=np.int64)
    side = np.array([1.0, 1.0, -1.0, 1.0, 1.0, 1.0])
    fees = {1.0: np.array([9, 12], dtype=np.int64), -1.0: np.zeros(0, dtype=np.int64)}
    lag = a1_lead_time.lags(block, side, fees)
    # the other side never had a fee; the fee in block 12 counts from block 13, not for block 12's own fill
    assert lag[[0, 1, 3, 4, 5]].tolist() == [1.0, 2.0, 3.0, 1.0, 38.0] and np.isinf(lag[2])
    assert [a1_lead_time.LABELS[k] for k in a1_lead_time.bucket(lag)] == ["1", "2-3", "none", "2-3", "1", "31-100"]
