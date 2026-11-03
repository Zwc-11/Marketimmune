"""Simulated makers' PnL at Hyperliquid's maker fee tiers, from the simulator's daily rows.

    python -m marketimmune.cli.fee_tiers --coin SOL --out eval/sim_fee_tiers_sol.json \\
        --inputs data/gold/hyperliquid/sim_frontier/SOL data/gold/hyperliquid/sim_backoff/SOL eval/sim_sol.json

A maker fee moves no quote and no fill, so a day's PnL at fee ``f`` (bps of traded notional; negative
is a rebate) is ``pnl - fee_paid - f * notional``: no rerun is needed. The schedule is Hyperliquid's
perps schedule (docs, Trading > Fees, read 2026-11-03): 1.5 bp at the base tier; 1.2, 0.8 and 0.4 bp
above $5M, $25M and $100M of 14-day volume; 0 above $500M; rebates of 0.1, 0.2 and 0.3 bp above
0.5%, 1.5% and 3% of the venue's maker volume. Staking discounts are left out.

``break_even_fee_bps`` is the maker's whole-period PnL before fees per filled dollar: it breaks even
only if it pays at most that (a negative value is the rebate it needs). Its interval resamples days
(stationary bootstrap, mean block 3 days).

Inputs are ``pull_frontier --day-dir`` directories (one JSON per day) and ``simulate_quotes``
reports (their ``daily`` rows, ``/fifo`` makers only, suffix dropped). Only the first input's days
are used, and the first input to give a maker-day wins.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.models.compare import stationary_bootstrap_ci, stationary_bootstrap_indices

BPS = 10_000.0
TIERS_BPS: dict[str, float] = {
    "base": 1.5,
    "volume_5m": 1.2,
    "volume_25m": 0.8,
    "volume_100m": 0.4,
    "volume_500m": 0.0,
    "rebate_0.5pct": -0.1,
    "rebate_1.5pct": -0.2,
    "rebate_3pct": -0.3,
}
FloatArray = npt.NDArray[np.float64]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", required=True)
    parser.add_argument("--inputs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def read_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_dir():
        return [row for f in sorted(path.glob("*.json")) for row in json.loads(f.read_text(encoding="utf-8"))]
    daily = json.loads(path.read_text(encoding="utf-8"))["daily"]
    return [{**r, "maker": r["maker"].removesuffix("/fifo")} for r in daily if r["maker"].endswith("/fifo")]


def load_days(paths: list[Path]) -> pd.DataFrame:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    days: set[str] = set()
    for i, path in enumerate(paths):
        found = read_rows(path)
        assert found, f"{path}: no rows"
        if i == 0:
            days = {r["day"] for r in found}
        for r in found:
            if r["day"] in days:
                rows.setdefault(
                    (r["day"], r["maker"]),
                    {
                        "day": r["day"],
                        "maker": r["maker"],
                        "fills": r["fills"],
                        "notional_usd": r["notional_usd"],
                        "before_fee_usd": r["pnl_usd"] - r["fee_usd"],
                    },
                )
    return pd.DataFrame(list(rows.values())).sort_values(["maker", "day"], ignore_index=True)


def ratio_ci(num: FloatArray, den: FloatArray, *, seed: int = 0) -> tuple[float, float]:
    """Interval for ``sum(num) / sum(den)`` in bps, resampling days."""
    idx = stationary_bootstrap_indices(num.size, 5_000, 3.0, np.random.default_rng(seed))
    lo, hi = np.quantile(num[idx].sum(axis=1) / den[idx].sum(axis=1) * BPS, [0.025, 0.975])
    return float(lo), float(hi)


def maker_report(group: pd.DataFrame) -> dict[str, Any]:
    notional = group["notional_usd"].to_numpy(dtype=np.float64)
    before = group["before_fee_usd"].to_numpy(dtype=np.float64)
    assert notional.sum() > 0.0, f"{group['maker'].iloc[0]}: no fills"
    out: dict[str, Any] = {
        "days": int(notional.size),
        "fills": int(group["fills"].sum()),
        "notional_usd": float(notional.sum()),
        "break_even_fee_bps": float(before.sum() / notional.sum() * BPS),
        "break_even_fee_ci95": list(ratio_ci(before, notional)),
        "tiers": {},
    }
    for name, fee in TIERS_BPS.items():
        daily = before - fee / BPS * notional
        lo, hi = stationary_bootstrap_ci(daily)
        out["tiers"][name] = {
            "fee_bps": fee,
            "mean_daily_usd": float(daily.mean()),
            "ci95": [lo, hi],
            "days_positive": int((daily > 0.0).sum()),
        }
    # the cheapest tier in the schedule at which the daily PnL interval is above zero
    out["profitable_from"] = next((name for name, t in out["tiers"].items() if t["ci95"][0] > 0.0), None)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frame = load_days(args.inputs)
    makers = {name: maker_report(g) for name, g in frame.groupby("maker") if g["notional_usd"].sum() > 0.0}
    result = {
        "coin": args.coin.upper(),
        "schedule_bps": TIERS_BPS,
        "inputs": [str(p) for p in args.inputs],
        "days": sorted(frame["day"].unique().tolist()),
        "makers": makers,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, m in sorted(makers.items(), key=lambda kv: -kv[1]["break_even_fee_bps"]):
        lo, hi = m["break_even_fee_ci95"]
        base, zero = m["tiers"]["base"]["mean_daily_usd"], m["tiers"]["volume_500m"]["mean_daily_usd"]
        print(
            f"{name:<16} {m['fills']:>9} fills  break-even fee {m['break_even_fee_bps']:+.2f} bps [{lo:+.2f}, {hi:+.2f}]  "
            f"USD/day {base:+,.0f} at 1.5 bp, {zero:+,.0f} at 0  profitable from: {m['profitable_from']}"
        )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
