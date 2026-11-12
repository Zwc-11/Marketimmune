"""One row per setting for the weekday test of the volatility-scaled deep quotes.

usage: table.py OUT.csv SCORE_DIR

SCORE_DIR holds, per replay NAME (A: audited engine; L: audited engine, orders 700 ms late;
R: engine as registered), the paper_report JSON ``NAME_report.json`` and the ``NAME_edge.csv``,
``NAME_risk.csv``, ``NAME_groups.csv``, ``NAME_markouts.csv`` and ``NAME_exit.csv`` files of
scripts/flow/edge.py, scripts/wide/score.py, scripts/latency/markouts.py and
scripts/wide/final_exit.py (docs/preregistration/paper-hip3-farsweep-20261109.md)."""

import json
import sys
from pathlib import Path

import pandas as pd

PICK = "hush@d=12/quiet=0/k=10/tol=0.3"
ROWS = [  # (replay, strategy, role, what)
    ("A", PICK, "Registered", "10 x the 1 s volatility, at least 12 bp"),
    ("A", "hush@d=8/quiet=0/tol=0.3", "Control", "8 bp from the mid"),
    ("A", PICK + "/stale=30", "Pick, quotes kept through 30 s of book silence", "as the pick"),
    ("A", "hush@d=8/quiet=0/k=10/tol=0.3", "Other setting", "10 x the 1 s volatility, at least 8 bp"),
    ("A", "hush@d=8/quiet=0/k=6/tol=0.3", "Other setting", "6 x the 1 s volatility, at least 8 bp"),
    ("L", PICK, "Pick, orders 700 ms late", "as the pick"),
]


def read(d: Path, name: str, kind: str) -> pd.DataFrame:
    p = d / f"{name}_{kind}.csv"
    return pd.read_csv(p).set_index("strategy") if p.exists() else pd.DataFrame()


def far_share(d: Path, name: str) -> dict[str, float]:
    """Share of filled $ at 5 bp or more from the true mid, from scripts/flow/ourfills.py's printout."""
    p = d / f"{name}_ourfills.txt"
    out: dict[str, float] = {}
    if not p.exists():
        return out
    strategy, total = None, 0.0
    for line in p.read_text().splitlines():
        if ": matched " in line:
            strategy = line.split(": matched ")[0]
            total = float(line.split("$")[1].split(";")[0].replace(",", ""))
            out[strategy] = 0.0
        elif strategy and line.split()[:1] and line.split()[0] in ("5-8", "8-12", ">12"):
            out[strategy] += float(line.split()[2]) / total
    return out


def report(d: Path, name: str) -> tuple[dict[str, dict], float]:
    p = d / f"{name}_report.json"
    if not p.exists():
        return {}, float("nan")
    r = json.loads(p.read_text())
    return {x["strategy"]: x for x in r["by_strategy"]}, r["hours"]


def main() -> None:
    out, d = sys.argv[1], Path(sys.argv[2])
    R, _ = report(d, "R")
    rows = []
    for name, strategy, role, what in ROWS:
        rep, hours = report(d, name)
        x = rep.get(strategy)
        if x is None:
            continue
        edge, risk, groups, mk, ex = (read(d, name, k) for k in ("edge", "risk", "groups", "markouts", "exit"))
        get = lambda t, c: t.loc[strategy, c] if strategy in t.index and c in t.columns else None  # noqa: E731
        c = x["components_bps"]
        share = far_share(d, name).get(strategy)
        reg = R.get(strategy) if name == "A" else None
        rows.append(
            {
                "setting": strategy if name == "A" else f"{strategy} @700ms",
                "role": role,
                "what": what,
                "hours": round(hours, 2),
                "usd_per_hour": x["usd_per_hour"],
                "usd_per_hour_low": x["usd_per_hour_ci95"][0],
                "usd_per_hour_high": x["usd_per_hour_ci95"][1],
                "fills": x["fills"],
                "filled_usd": round(x["notional_usd"]),
                "filled_usd_per_hour": round(x["notional_usd"] / hours),
                "bps": x["bps"],
                "spread_bps": c["spread"],
                "move_1s_bps": c["adverse_1s"],
                "position_bps": c["inventory"],
                "fee_bps": c["fee"],
                "edge60": get(edge, "net60"),
                "edge60_low": get(edge, "net60_low"),
                "edge60_high": get(edge, "net60_high"),
                "share_5bp_plus": round(share, 3) if share is not None else None,
                "mk1": get(mk, "mk1"),
                "mk60": get(mk, "mk60"),
                "mk1800": get(mk, "mk1800"),
                "us_usd_per_hour": get(groups, "us_usd_per_hour"),
                "rest_usd_per_hour": get(groups, "rest_usd_per_hour"),
                "actions_per_filled_usd": get(risk, "actions_per_filled_usd"),
                "largest_market_position_usd": get(risk, "largest_market_position_usd"),
                "largest_gross_position_usd": get(risk, "largest_gross_position_usd"),
                "max_drawdown_usd": x["max_drawdown_usd"],
                "final_exit_cost_usd": get(ex, "cost_usd"),
                "registered_engine_usd_per_hour": reg["usd_per_hour"] if reg else None,
                "registered_engine_low": reg["usd_per_hour_ci95"][0] if reg else None,
                "registered_engine_high": reg["usd_per_hour_ci95"][1] if reg else None,
            }
        )
    T = pd.DataFrame(rows)
    T.to_csv(out, index=False)
    print(T[["setting", "usd_per_hour", "edge60", "edge60_low", "edge60_high", "fills", "registered_engine_usd_per_hour"]].to_string())


if __name__ == "__main__":
    main()
