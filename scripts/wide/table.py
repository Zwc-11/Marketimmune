"""One row per setting for the 50-market test: both engines, the test hours and the 5.4 h before.

usage: table.py OUT.csv SCORE_DIR

SCORE_DIR holds the paper_report JSONs (audA, audB, regC, preAud, preReg ``_report.json``), and
from scripts/wide/score.py, scripts/latency/markouts.py and scripts/flow/edge.py the per-replay
``_groups.csv``, ``_risk.csv``, ``_markouts.csv`` and ``_edge.csv`` files."""

import json
import sys
from pathlib import Path

import pandas as pd

ORDER = [
    "hush@d=10/quiet=0/tol=0.3",
    "hush@d=10/quiet=0/tol=0.3/stale=30",
    "hush@d=6/quiet=0/tol=0.3",
    "hush@d=8/quiet=0/tol=0.3",
    "hush@d=12/quiet=0/tol=0.3",
    "mm@8",
    "touch",
]
ROLE = {ORDER[0]: "Registered", ORDER[1]: "Registered, quotes kept through 30 s of book silence"}
WHAT = {
    ORDER[0]: "10 bp from the mid",
    ORDER[1]: "10 bp, kept through 30 s of book silence",
    ORDER[2]: "6 bp from the mid",
    ORDER[3]: "8 bp from the mid",
    ORDER[4]: "12 bp from the mid",
    "mm@8": "Market maker, 8 bp",
    "touch": "At the touch",
}


def report(d: Path, name: str) -> dict[str, dict]:
    p = d / f"{name}_report.json"
    return {x["strategy"]: x for x in json.loads(p.read_text())["by_strategy"]} if p.exists() else {}


def csv(d: Path, name: str, kind: str) -> pd.DataFrame:
    p = d / f"{name}_{kind}.csv"
    return pd.read_csv(p).set_index("strategy") if p.exists() else pd.DataFrame()


def main() -> None:
    out, d = sys.argv[1], Path(sys.argv[2])
    aud = {**report(d, "audA"), **report(d, "audB")}
    reg, pre_a, pre_r = report(d, "regC"), report(d, "preAud"), report(d, "preReg")
    groups = pd.concat([csv(d, n, "groups") for n in ("audA", "audB")])
    risk = pd.concat([csv(d, n, "risk") for n in ("audA", "audB")])
    mk = pd.concat([csv(d, n, "markouts") for n in ("audA", "audB")])
    edge = pd.concat([csv(d, n, "edge") for n in ("audA", "audB")])
    hours = json.loads((d / "audA_report.json").read_text())["hours"]
    rows = []
    for s in ORDER:
        a = aud[s]
        c = a["components_bps"]
        row = {
            "setting": s,
            "what": WHAT[s],
            "role": ROLE.get(s, "Reported beside it"),
            "usd_per_hour": a["usd_per_hour"],
            "low": a["usd_per_hour_ci95"][0],
            "high": a["usd_per_hour_ci95"][1],
            "fills": a["fills"],
            "filled_usd_per_hour": round(a["notional_usd"] / hours),
            "bps": round(a["bps"], 2),
            "spread_bps": round(c["spread"], 2),
            "adverse_1s_bps": round(c["adverse_1s"], 2),
            "inventory_bps": round(c["inventory"], 2),
            "fee_bps": round(c["fee"], 2),
            "max_drawdown_usd": a["max_drawdown_usd"],
        }
        if s in edge.index:
            row.update({"edge60": edge.loc[s, "net60"], "edge60_low": edge.loc[s, "net60_low"], "edge60_high": edge.loc[s, "net60_high"]})
        if s in mk.index:
            row.update({f"mk{h}": mk.loc[s, f"mk{h}"] for h in (1, 60, 300, 1800)})
        if s in groups.index:
            g = groups.loc[s]
            row.update({"no_anchor_usd_per_hour": g.no_anchor_usd_per_hour, "other_47_usd_per_hour": g.other_47_usd_per_hour})
        if s in risk.index:
            k = risk.loc[s]
            row.update(
                {
                    "actions_per_filled_usd": k.actions_per_filled_usd,
                    "largest_market_position_usd": k.largest_market_position_usd,
                    "largest_gross_position_usd": k.largest_gross_position_usd,
                }
            )
        for tag, src in (("reg", reg), ("pre_aud", pre_a), ("pre_reg", pre_r)):
            if s in src:
                row.update({f"{tag}_usd_per_hour": src[s]["usd_per_hour"], f"{tag}_low": src[s]["usd_per_hour_ci95"][0], f"{tag}_high": src[s]["usd_per_hour_ci95"][1]})
        rows.append(row)
    T = pd.DataFrame(rows)
    T.to_csv(out, index=False)
    print(T.T.to_string())


if __name__ == "__main__":
    main()
