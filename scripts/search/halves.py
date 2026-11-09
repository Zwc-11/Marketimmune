"""Per strategy and coin: $ an hour in each half of a run and in total, from equity.jsonl (marked
PnL after fees). Writes /tmp/search/halves.csv and prints the totals by strategy.

usage: halves.py RUN_DIR [RUN_DIR ...]"""

import sys

import pandas as pd

rows = []
for run in sys.argv[1:]:
    E = pd.read_json(run + "/equity.jsonl", lines=True)
    t0, t1 = E.t_ms.min(), E.t_ms.max()
    mid = (t0 + t1) / 2
    hrs = (t1 - t0) / 3.6e6
    for (s, c), g in E.groupby(["strategy", "coin"]):
        g = g.sort_values("t_ms")
        first = g[g.t_ms <= mid]
        a = first.equity.iloc[-1] if len(first) else 0.0
        end = g.equity.iloc[-1]
        rows.append({"run": run, "strategy": s, "coin": c, "h1": a / (hrs / 2), "h2": (end - a) / (hrs / 2), "all": end / hrs})
R = pd.DataFrame(rows)
R.to_csv("/tmp/search/halves.csv", index=False)
print(R.groupby("strategy")[["h1", "h2", "all"]].sum().round(2).sort_values("all", ascending=False).to_string())
