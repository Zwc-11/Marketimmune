"""Gather the 2026-11-06 backtest results into the tables the results page reads.

    python scripts/paper_results_data.py --out eval/paper/results_20261106

Reads the committed evaluations (``eval/paper/tune_guard_home_20261106.json``, the
``report_guard_*`` and ``report_mm_*`` reports, ``factors_20261106.json``, the look-ahead checks)
and the guard replays' minute equity (``data/paper/tune-guard/home/250x4``, not committed), and
writes CSV files: every strategy's numbers, the equity curves, the factors' information
coefficients, the wallet factor's increment, the look-ahead checks, and the latency and fee
scenarios.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

EVAL = Path("eval/paper")
WORK = Path("data/paper/tune-guard/home/250x4")
SEGMENTS = [
    "night/seg2-20261106T0448",
    "night/seg3-20261106T0559",
    "night/seg4-20261106T0757",
    "live/seg-20261106T1606",
    "live/seg-20261106T1806",
    "live/seg-20261106T2003",
]
PICK = "guard@z=0.05/w=1.5/win=5"
CURVES = ("zgap@0.05", PICK, "guard@z=0.05/w=1/win=1", "guard@z=0.05/net=2000", "mm@h=2/skew=6")
SIGNAL_NAMES = {
    "gap_z": "Coinbase gap (A1)",
    "wallet_z": "Wallet factor, 5 s (A1)",
    "wallet_1s_z": "Wallet factor, 1 s (A1)",
    "wallet": "Wallet factor, raw",
    "micro": "Microprice",
    "imbalance": "Taker imbalance, 5 s",
    "burst": "Hawkes burst",
}


def kind(name: str) -> str:
    if name == "touch":
        return "Control: always at the touch"
    if name == "zgap@0.05":
        return "Gap quoter (running now)"
    if name.startswith("mm@"):
        return "Market maker"
    if name == PICK:
        return "Research pick: gap + wallets"
    p = name.partition("@")[2]
    if any(k in p for k in ("net=", "lean=", "stop=")):
        return "Gap quoter + position control"
    if "w=" in p:
        return "Gap + wallets, other setting"
    return "Gap quoter through the risk layer"


def write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def scoreboard() -> list[dict[str, Any]]:
    tune = json.loads((EVAL / "tune_guard_home_20261106.json").read_text())
    per_usd: dict[str, float] = {}
    for fam in tune["families"].values():
        for o in fam["all"]:
            per_usd[o["strategy"]] = o["orders_per_usd"]
    for o in tune["over_limit"]:
        per_usd[o["strategy"]] = o["orders_per_usd"]
    sel = json.loads((EVAL / "report_guard_home_20261106.json").read_text())
    held = json.loads((EVAL / "report_guard_home_heldout_20261106.json").read_text())
    hs = {r["strategy"]: r for r in held["by_strategy"]}
    vs = {r["strategy"]: r for r in sel["vs_baseline"]}
    vh = {r["strategy"]: r for r in held["vs_baseline"]}
    rows = []
    for r in sel["by_strategy"]:
        s, c = r["strategy"], r["components_bps"]
        v, w = vs.get(s, {}), vh.get(s, {})
        rows.append(
            {
                "strategy": s,
                "kind": kind(s),
                "orders_per_usd": per_usd.get(s),
                "usd_per_hour": r["usd_per_hour"],
                "held_out_usd_per_hour": hs[s]["usd_per_hour"],
                "vs_gap_usd_per_hour": v.get("usd_per_hour"),
                "vs_gap_low": (v.get("ci95") or [None, None])[0],
                "vs_gap_high": (v.get("ci95") or [None, None])[1],
                "vs_gap_held_out_usd_per_hour": w.get("usd_per_hour"),
                "vs_gap_held_out_low": (w.get("ci95") or [None, None])[0],
                "vs_gap_held_out_high": (w.get("ci95") or [None, None])[1],
                "spread_bps": c["spread"],
                "adverse_1s_bps": c["adverse_1s"],
                "fee_bps": c["fee"],
                "rest_bps": c["inventory"],
                "total_bps": r["bps"],
                "block_sd_usd": r["block_sd_usd"],
                "max_drawdown_usd": r["max_drawdown_usd"],
                "mean_abs_net_usd": r["mean_abs_net_usd"],
                "btc_corr_1min": r["btc_corr_1min"],
            }
        )
    return sorted(rows, key=lambda x: -x["usd_per_hour"])


def equity() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = dict.fromkeys(CURVES, 0.0)
    for seg in SEGMENTS:
        run = WORK / seg
        eq = pd.read_json(run / "equity.jsonl", lines=True)
        eq = eq[eq["strategy"].isin(CURVES)]
        per = eq.groupby(["strategy", "t_ms"])["equity"].sum().reset_index()
        mids = pq.read_table(run / "mids.parquet").to_pandas()
        btc = mids[mids["coin"] == "BTC"].sort_values("t_ms")
        times = sorted(per["t_ms"].unique())
        for t in times:
            i = btc["t_ms"].searchsorted(t, side="right") - 1
            row: dict[str, Any] = {
                "time": pd.Timestamp(t, unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
                "segment": seg + (" (held out)" if seg.endswith("T2003") else ""),
                "btc": round(float(btc["mid"].iloc[i]), 1) if i >= 0 else None,
            }
            for s in CURVES:
                v = per[(per["strategy"] == s) & (per["t_ms"] == t)]["equity"]
                row[s] = round(float(v.iloc[0]) + offset[s], 2) if len(v) else None
            rows.append(row)
        for s in CURVES:
            last = per[per["strategy"] == s].sort_values("t_ms")["equity"]
            offset[s] += float(last.iloc[-1]) if len(last) else 0.0
    return rows


def factors() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    f = json.loads((EVAL / "factors_20261106.json").read_text())
    ic = []
    for part, by_name in f["ic"].items():
        for name, coins in by_name.items():
            for h, v in coins["_mean"].items():
                ic.append(
                    {"signal": SIGNAL_NAMES.get(name, name), "horizon": h, "part": part, "ic": v["ic"], "coins_positive": v["positive"]}
                )
    inc = [{"coin": c, **v} for c, v in f["incremental_10s_held_out"].items()]
    return ic, inc


def lookahead() -> list[dict[str, Any]]:
    rows = []
    for name, label in (
        ("lookahead_20261106.json", "Clock corrected from earlier timestamps (used)"),
        ("lookahead_interpolated_clock_20261106.json", "Clock interpolated from the next 30 s"),
    ):
        r = json.loads((EVAL / name).read_text())
        for c in r["cuts"]:
            for stream, v in [*c["streams"].items(), ("signals", c["signals"])]:
                rows.append(
                    {"check": label, "cut": f"{c['share']:.0%}", "what": stream, "compared": v["rows"], "different": v["different"]}
                )
    return rows


def scenarios() -> list[dict[str, Any]]:
    rows = []
    for key, label in (
        ("home", "This PC, 200 ms"),
        ("tokyo", "Tokyo server"),
        ("fee0", "0 bp maker fee"),
        ("tokyo_rebate", "Tokyo + top rebate"),
    ):
        r = json.loads((EVAL / f"report_mm_{key}_20261106.json").read_text())
        for s in r["by_strategy"]:
            if s["strategy"] in ("touch", "zgap@0.05", "mm@1.5", "mm@h=2/skew=6", "mm@3"):
                rows.append({"scenario": label, "strategy": s["strategy"], "usd_per_hour": s["usd_per_hour"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write(args.out / "scoreboard.csv", scoreboard())
    write(args.out / "equity.csv", equity())
    ic, inc = factors()
    write(args.out / "factor_ic.csv", ic)
    write(args.out / "wallet_increment.csv", inc)
    write(args.out / "lookahead.csv", lookahead())
    write(args.out / "scenarios.csv", scenarios())
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
