"""Score the paper-trading runs: PnL by component, per filled dollar and per hour, with intervals.

    python -m marketimmune.cli.paper_report --runs data/paper/seg1-* --out eval/paper/night_20261106.json

Each run (``cli.paper_trade``) starts flat and is marked to the mid at its end, so runs add up. Per
coin and strategy, in USD and in bps of filled notional (as in ``docs/research/block-simulator.md``):

- ``spread``: the fill against the Hyperliquid mid before the fill's block;
- ``adverse_1s``: the mid's move over the next second, against the fill;
- ``fee`` and ``inventory`` (everything else: holding the position past 1 s, marked to the end);
- ``break_even_fee_bps``: PnL before fees per filled dollar, the maker fee that would break even.

Intervals: the PnL of 15-minute blocks (from the minute equity snapshots), stationary bootstrap with
a mean block of 3, 5,000 draws, seed 0. ``vs_touch`` pairs each maker with ``touch`` on the same
coin and blocks.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.models.compare import stationary_bootstrap_ci

BPS = 1e4
BLOCK_MS = 15 * 60_000
HORIZONS_MS = {"1s": 1_000, "10s": 10_000, "60s": 60_000}


def mid_lookup(mids: pd.DataFrame, coin: str, t: np.ndarray, *, before: bool = False) -> np.ndarray:
    """The last mid at or before each block time ``t`` (strictly before with ``before``: the book
    before the fill's own block). NaN before the run's first mid; past its end, the last mid, where
    the run marks its positions."""
    m = mids[mids["coin"] == coin]
    ts, px = m["t_ms"].to_numpy(), m["mid"].to_numpy()
    i = np.searchsorted(ts, t, side="left" if before else "right") - 1
    out: np.ndarray = np.where(i >= 0, px[np.clip(i, 0, None)], np.nan)
    return out


def run_tables(run: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """One run's fills with mids and markouts, its 15-minute block PnL, and its summary."""
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    fills = pd.read_json(run / "fills.jsonl", lines=True) if (run / "fills.jsonl").stat().st_size else pd.DataFrame()
    mids = pq.read_table(run / "mids.parquet").to_pandas().sort_values(["coin", "t_ms"], kind="stable")
    if not fills.empty:
        parts = []
        for coin, f in fills.groupby("coin"):
            f = f.copy()
            t = f["t_ms"].to_numpy()
            f["mid"] = mid_lookup(mids, str(coin), t, before=True)
            for h, ms in HORIZONS_MS.items():
                f[f"mid_{h}"] = mid_lookup(mids, str(coin), t + ms)
            parts.append(f)
        fills = pd.concat(parts, ignore_index=True)
        fills["run"] = run.name
    eq = pd.read_json(run / "equity.jsonl", lines=True)
    eq["block"] = (eq["t_ms"] - eq["t_ms"].min()) // BLOCK_MS
    last = eq.sort_values("t_ms").groupby(["coin", "strategy", "block"])["equity"].last().reset_index()
    last["pnl"] = last.groupby(["coin", "strategy"])["equity"].diff().fillna(last["equity"])
    last["block"] = run.name + "/" + last["block"].astype(str)
    return fills, last[["coin", "strategy", "block", "pnl"]], summary


def ci(x: np.ndarray) -> list[float] | None:
    return [round(v, 2) for v in stationary_bootstrap_ci(x)] if x.size >= 4 else None


def score(runs: list[Path]) -> dict[str, Any]:
    tables = [run_tables(r) for r in runs]
    fills = pd.concat([t[0] for t in tables if not t[0].empty], ignore_index=True)
    blocks = pd.concat([t[1] for t in tables], ignore_index=True)
    final: dict[tuple[str, str], float] = defaultdict(float)
    for _, _, s in tables:
        for inst in s["instances"]:
            final[(inst["coin"], inst["strategy"])] += inst["equity"]
    hours = sum(s["hours"] for _, _, s in tables)
    side, qty = fills["side"].to_numpy(), fills["qty"].to_numpy()
    fills["notional"] = fills["px"] * qty
    fills["spread_usd"] = side * (fills["mid"] - fills["px"]) * qty
    for h in HORIZONS_MS:
        fills[f"adverse_{h}_usd"] = side * (fills[f"mid_{h}"] - fills["mid"]) * qty
    fills["fee_usd"] = -fills["fee_rate"] * fills["notional"]
    rows: list[dict[str, Any]] = []
    for (coin, strategy), total in sorted(final.items()):
        f = fills[(fills["coin"] == coin) & (fills["strategy"] == strategy)]
        b = blocks[(blocks["coin"] == coin) & (blocks["strategy"] == strategy)]["pnl"].to_numpy()
        notional = float(f["notional"].sum())
        comp = {k: float(f[f"{k}_usd"].sum()) for k in ("spread", "adverse_1s", "adverse_10s", "adverse_60s", "fee")}
        comp["inventory"] = total - comp["spread"] - comp["adverse_1s"] - comp["fee"]
        row: dict[str, Any] = {
            "coin": coin,
            "strategy": strategy,
            "fills": int(len(f)),
            "notional_usd": round(notional, 2),
            "total_usd": round(total, 2),
        }
        row["usd_per_hour"] = round(total / hours, 2) if hours else None
        row["usd_per_hour_ci95"] = [round(v * 4, 2) for v in c] if (c := ci(b)) else None
        if notional:
            row["bps"] = {k: round(v / notional * BPS, 3) for k, v in {**comp, "total": total}.items()}
            row["break_even_fee_bps"] = round((total - comp["fee"]) / notional * BPS, 3)
        rows.append(row)
    by_strategy = []
    for strategy in sorted({r["strategy"] for r in rows}):
        rs = [r for r in rows if r["strategy"] == strategy]
        notional = sum(r["notional_usd"] for r in rs)
        total = sum(r["total_usd"] for r in rs)
        b = blocks[blocks["strategy"] == strategy].groupby("block")["pnl"].sum().to_numpy()
        fee = float(fills.loc[fills["strategy"] == strategy, "fee_usd"].sum())
        by_strategy.append(
            {
                "strategy": strategy,
                "fills": sum(r["fills"] for r in rs),
                "notional_usd": round(notional, 2),
                "total_usd": round(total, 2),
                "usd_per_hour": round(total / hours, 2) if hours else None,
                "usd_per_hour_ci95": [round(v * 4, 2) for v in c] if (c := ci(b)) else None,
                "bps": round(total / notional * BPS, 3) if notional else None,
                "break_even_fee_bps": round((total - fee) / notional * BPS, 3) if notional else None,
            }
        )
    vs_touch = []
    for coin in sorted({r["coin"] for r in rows}):
        base = blocks[(blocks["coin"] == coin) & (blocks["strategy"] == "touch")].set_index("block")["pnl"]
        for strategy in sorted({r["strategy"] for r in rows if r["coin"] == coin} - {"touch"}):
            if strategy.startswith("taker"):
                continue
            d = (blocks[(blocks["coin"] == coin) & (blocks["strategy"] == strategy)].set_index("block")["pnl"] - base).dropna().to_numpy()
            vs_touch.append(
                {
                    "coin": coin,
                    "strategy": strategy,
                    "usd_per_hour": round(float(d.mean()) * 4, 2) if d.size else None,
                    "ci95": [round(v * 4, 2) for v in c] if (c := ci(d)) else None,
                    "blocks_better": f"{int((d > 0).sum())}/{d.size}",
                }
            )
    models: dict[str, list[dict[str, Any]]] = {}
    for _, _, s in tables:
        for coin, fits in s["models"].items():
            models.setdefault(coin, []).extend(fits)
    return {
        "runs": [str(r) for r in runs],
        "hours": round(hours, 3),
        "settings": tables[0][2]["settings"] | {"fees_bps": tables[0][2]["settings_fees_bps"]},
        "feed_delay_ms_p10_p50_p90": [s["feed_delay_ms_p10_p50_p90"] for _, _, s in tables],
        "connection_gaps": sum(len(s["connection_gaps"]) for _, _, s in tables),
        "by_strategy": by_strategy,
        "by_coin": rows,
        "vs_touch": vs_touch,
        "model_oos_r2": {
            c: {"fits": len(v), "mean_oos_r2": round(float(np.mean(o)), 4) if (o := [x["oos_r2"] for x in v if "oos_r2" in x]) else None}
            for c, v in models.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = score(sorted(r for r in args.runs if (r / "fills.jsonl").exists()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"{result['hours']} h, {len(result['runs'])} runs")
    for r in sorted(result["by_strategy"], key=lambda r: -r["total_usd"]):
        print(
            f"{r['strategy']:10s} fills {r['fills']:6d}  {r['bps']} bps  USD/h {r['usd_per_hour']} {r['usd_per_hour_ci95']}  break-even fee {r['break_even_fee_bps']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
