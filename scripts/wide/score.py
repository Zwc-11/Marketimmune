"""Score a replay of the 50-market HIP-3 test (docs/preregistration/paper-hip3-wide-20261109.md).

usage: score.py OUT_PREFIX CARRY SEG_DIR [SEG_DIR ...]

Reads each segment's fills.jsonl, equity.jsonl and summary.json (one strategy set per call is
fine: call it once per replay and concatenate). CARRY is 1 when positions carry from one segment
to the next (the audited engine), 0 when each segment starts flat (the engine as registered).

Writes, per strategy:
- OUT_PREFIX_groups.csv: $ an hour on the three markets with no listed stock behind them
  (io:OAI, io:ANTH, xyz:ANT) and on the other 47, and in US regular hours (14:30-21:00 UTC)
  against the rest;
- OUT_PREFIX_markets.csv: $ an hour, fills and filled $ by market;
- OUT_PREFIX_risk.csv: orders and cancels per filled $ (each instance's ``actions`` over its
  filled $), the largest one-market position and the largest gross position, both in $.

Each segment's equity.jsonl starts at zero (carried positions are valued at the last mid of the
segment before), so a market's PnL in a window is the change in its equity over the part of the
window inside each segment. Hours are the segments' span."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

NO_ANCHOR = {"io:OAI", "io:ANTH", "xyz:ANT"}
US = (14 * 60 + 30, 21 * 60)


def equity_parts(seg: Path) -> pd.DataFrame:
    E = pd.read_json(seg / "equity.jsonl", lines=True)
    t = pd.to_datetime(E.t_ms, unit="ms", utc=True)
    minute = t.dt.hour * 60 + t.dt.minute
    E["us"] = (minute >= US[0]) & (minute < US[1])
    rows = []
    for (s, c), g in E.groupby(["strategy", "coin"]):
        g = g.sort_values("t_ms")
        eq = g.equity.to_numpy()
        d = np.diff(eq, prepend=0.0)
        us = g.us.to_numpy()
        for part in (False, True):
            rows.append({"segment": seg.name, "strategy": s, "coin": c, "us": part, "usd": float(d[us == part].sum())})
    span = (E.t_ms.max() - E.t_ms.min()) / 3.6e6
    us_minutes = E.drop_duplicates("t_ms").us.sum() / 60
    R = pd.DataFrame(rows)
    R["hours"] = span
    R["us_hours"] = us_minutes
    return R


def main() -> None:
    prefix, carry, segs = sys.argv[1], sys.argv[2] == "1", [Path(p) for p in sys.argv[3:]]
    parts = [equity_parts(s) for s in segs]
    R = pd.concat(parts)
    hours = sum(p.hours.iloc[0] for p in parts)
    us_hours = sum(p.us_hours.iloc[0] for p in parts)
    rest_hours = hours - us_hours

    G = []
    for s, g in R.groupby("strategy"):
        na = g.coin.isin(NO_ANCHOR)
        G.append(
            {
                "strategy": s,
                "hours": round(hours, 3),
                "usd_per_hour": round(g.usd.sum() / hours, 2),
                "no_anchor_usd_per_hour": round(g[na].usd.sum() / hours, 2),
                "other_47_usd_per_hour": round(g[~na].usd.sum() / hours, 2),
                "us_hours": round(us_hours, 3),
                "us_usd_per_hour": round(g[g.us].usd.sum() / us_hours, 2) if us_hours > 0 else None,
                "rest_usd_per_hour": round(g[~g.us].usd.sum() / rest_hours, 2),
            }
        )
    pd.DataFrame(G).to_csv(f"{prefix}_groups.csv", index=False)
    print(pd.DataFrame(G).to_string(index=False))

    F = pd.concat([pd.read_json(s / "fills.jsonl", lines=True).assign(segment=i) for i, s in enumerate(segs)])
    F["usd"] = F.px * F.qty
    by = R.groupby(["strategy", "coin"]).usd.sum() / hours
    M = pd.DataFrame({"usd_per_hour": by.round(3)})
    M["fills"] = F.groupby(["strategy", "coin"]).size()
    M["filled_usd"] = F.groupby(["strategy", "coin"]).usd.sum().round(0)
    M = M.fillna(0).reset_index().sort_values(["strategy", "usd_per_hour"])
    M.to_csv(f"{prefix}_markets.csv", index=False)

    actions: dict[str, float] = {}
    for s in segs:
        for inst in json.loads((s / "summary.json").read_text())["instances"]:
            actions[inst["strategy"]] = actions.get(inst["strategy"], 0) + inst.get("actions", 0)
    K = []
    for s, f in F.sort_values(["segment", "t_ms"]).groupby("strategy"):
        if carry:
            f = f.assign(pos=(f.side * f.qty).groupby(f.coin).cumsum())
        else:
            f = f.assign(pos=(f.side * f.qty).groupby([f.segment, f.coin]).cumsum())
        f = f.assign(pos_usd=f.pos * f.px).reset_index(drop=True)
        # gross: every market's latest position after each fill (within a segment when nothing carries)
        windows = [f] if carry else [g for _, g in f.groupby("segment")]
        gross = max(w.pivot_table(index=w.index, columns="coin", values="pos_usd").ffill().fillna(0).abs().sum(axis=1).max() for w in windows)
        K.append(
            {
                "strategy": s,
                "fills": len(f),
                "filled_usd": round(f.usd.sum()),
                "actions": int(actions.get(s, 0)),
                "actions_per_filled_usd": round(actions.get(s, 0) / f.usd.sum(), 2),
                "largest_market_position_usd": round(f.pos_usd.abs().max()),
                "largest_gross_position_usd": round(gross),
            }
        )
    pd.DataFrame(K).to_csv(f"{prefix}_risk.csv", index=False)
    print(pd.DataFrame(K).to_string(index=False))


if __name__ == "__main__":
    main()
