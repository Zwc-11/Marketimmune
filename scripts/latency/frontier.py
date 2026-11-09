"""The delay frontier in one CSV: every strategy's result by venue and total delay, and its $ an hour
at the maker fees Hyperliquid's volume tiers give.

usage: frontier.py OUT.csv

Reads eval/paper/latency/{majors_D*_cb*,hip3_*}_report.json. Total delay D is feed (after the block)
plus order latency; "here" is the recording as received with 200 ms orders. $ an hour at another
maker fee f: the run's $ an hour plus (1.5 - f) bp on each maker-filled $ (from the fills' fee rates;
taker fills keep their 4.5 bp)."""

import glob
import json
import re
import sys

import pandas as pd

MAJORS_FEES = [1.5, 1.2, 0.8, 0.4, 0.0]


def maker_usd(runs: list[str]) -> dict[str, float]:
    """Filled $ at the maker rate, by strategy, over the runs' fills."""
    F = pd.concat([pd.read_json(d + "/fills.jsonl", lines=True) for d in runs])
    m = F[F.fee_rate <= F.fee_rate.min() + 1e-12]
    return (m.px * m.qty).groupby(m.strategy).sum().to_dict()


def rows_of(path: str, venue: str, delay: str, cb: int | None) -> list[dict]:
    r = json.load(open(path))
    maker = maker_usd(r["runs"]) if venue == "majors" else {}
    hours = r["hours"]
    out = []
    for s in r["by_strategy"]:
        c, cu = s["components_bps"], s["components_usd_per_hour"]
        filled = s["notional_usd"] / hours
        zero = s["usd_per_hour"] - cu.get("fee", 0.0)
        row = {
            "venue": venue,
            "delay": delay,
            "delay_ms": None if delay == "here" else int(delay),
            "coinbase_extra_ms": cb,
            "strategy": s["strategy"],
            "hours": round(hours, 2),
            "usd_per_hour": s["usd_per_hour"],
            "ci_lo": s["usd_per_hour_ci95"][0],
            "ci_hi": s["usd_per_hour_ci95"][1],
            "filled_usd_per_hour": round(filled),
            "bps": s["bps"],
            "spread": c.get("spread"),
            "adverse_1s": c.get("adverse_1s"),
            "inventory": c.get("inventory"),
            "fee": c.get("fee"),
            "break_even_fee_bps": s["break_even_fee_bps"],
            "usd_per_hour_zero_fee": round(zero, 2),
        }
        if venue == "majors":
            mh = maker.get(s["strategy"], 0.0) / hours
            for f in MAJORS_FEES:
                row[f"usd_per_hour_maker_{f}"] = round(s["usd_per_hour"] + (1.5 - f) * mh / 1e4, 2)
        out.append(row)
    return out


def main() -> None:
    rows = []
    for p in sorted(glob.glob("eval/paper/latency/majors_D*_cb*_report.json")):
        d, cb = re.search(r"majors_D(\w+?)_cb(\d+)_report", p).groups()
        rows += rows_of(p, "majors", d, int(cb))
    for p in sorted(glob.glob("eval/paper/latency/hip3_*_report.json")):
        d = re.search(r"hip3_(\w+?)_report", p).group(1)
        rows += rows_of(p, "hip3", d, None)
    R = pd.DataFrame(rows)
    R = R.sort_values(["venue", "strategy", "delay_ms"], na_position="last")
    R.to_csv(sys.argv[1], index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 40, "display.max_rows", 200):
        print(R[["venue", "delay", "coinbase_extra_ms", "strategy", "usd_per_hour", "ci_lo", "ci_hi", "bps", "spread", "adverse_1s", "break_even_fee_bps"]].to_string(index=False))


if __name__ == "__main__":
    main()
