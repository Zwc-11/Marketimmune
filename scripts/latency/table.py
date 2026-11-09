"""One table of the delay frontier: each report's strategies by total delay.

usage: table.py OUT.csv LABEL=REPORT.json [LABEL=REPORT.json ...]

Columns: $ an hour and its interval, filled $ an hour, bp per filled $ (net, and the parts), the
break-even maker fee, and $ an hour at a zero maker fee (the fee part added back)."""

import json
import sys

import pandas as pd


def main() -> None:
    out, specs = sys.argv[1], sys.argv[2:]
    rows = []
    for spec in specs:
        label, path = spec.split("=", 1)
        r = json.load(open(path))
        hours = r["hours"]
        runs = [d for d in r.get("feed_delay_ms_p10_p50_p90") or [] if d and d.get("hl_top")]
        delay = (None, sorted(d["hl_top"][1] for d in runs)[len(runs) // 2]) if runs else None
        for s in r["by_strategy"]:
            c = s["components_bps"]
            cu = s["components_usd_per_hour"]
            rows.append(
                {
                    "run": label,
                    "strategy": s["strategy"],
                    "hours": round(hours, 2),
                    "feed_p50_ms": delay[1] if delay else None,
                    "usd_per_hour": s["usd_per_hour"],
                    "ci_lo": s["usd_per_hour_ci95"][0],
                    "ci_hi": s["usd_per_hour_ci95"][1],
                    "filled_usd_per_hour": round(s["notional_usd"] / hours),
                    "bps": s["bps"],
                    "spread": c.get("spread"),
                    "adverse_1s": c.get("adverse_1s"),
                    "adverse_60s": c.get("adverse_60s"),
                    "inventory": c.get("inventory"),
                    "fee": c.get("fee"),
                    "break_even_fee_bps": s["break_even_fee_bps"],
                    "usd_per_hour_zero_fee": round(s["usd_per_hour"] - cu.get("fee", 0.0), 2),
                }
            )
    R = pd.DataFrame(rows)
    R.to_csv(out, index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(R.drop(columns=["hours"]).to_string(index=False))


if __name__ == "__main__":
    main()
