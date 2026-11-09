"""Fill markouts before the fee, by strategy, over some paper segment dirs.

usage: markouts.py OUT.csv SEG_DIR [SEG_DIR ...]

For each fill: side * (mid h seconds later / fill price - 1), in bp, at 1 s to 30 min; the mid is the
last one at or before t + h in the same segment (a fill too near the end uses the last mid).
Weighted by filled $."""

import json
import sys

import numpy as np
import pandas as pd

H = [1, 10, 60, 300, 1800]


def segment(path: str) -> pd.DataFrame:
    F = pd.read_json(path + "/fills.jsonl", lines=True)
    if F.empty:
        return F
    M = pd.read_parquet(path + "/mids.parquet")
    parts = []
    for coin, f in F.groupby("coin"):
        m = M[M.coin == coin].sort_values("t_ms")
        t, mid = m.t_ms.to_numpy(), m.mid.to_numpy()
        f = f.copy()
        for h in H:
            i = np.clip(np.searchsorted(t, f.t_ms.to_numpy() + h * 1000, side="right") - 1, 0, len(t) - 1)
            f[f"mk{h}"] = f.side * (mid[i] / f.px - 1) * 1e4
        parts.append(f)
    return pd.concat(parts)


def main() -> None:
    out, dirs = sys.argv[1], sys.argv[2:]
    F = pd.concat([segment(d) for d in dirs])
    F["usd"] = F.px * F.qty
    rows = []
    for s, f in F.groupby("strategy"):
        w = f.usd / f.usd.sum()
        rows.append({"strategy": s, "fills": len(f), "usd": round(f.usd.sum()), **{f"mk{h}": round(float((f[f"mk{h}"] * w).sum()), 2) for h in H}})
    R = pd.DataFrame(rows).sort_values("strategy")
    R.to_csv(out, index=False)
    print(R.to_string(index=False))
    json.dumps(rows)


if __name__ == "__main__":
    main()
