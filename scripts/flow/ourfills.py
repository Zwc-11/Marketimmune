"""Our paper fills against the true pre-trade mid: how far from the mid was the quote when it filled?

usage: ourfills.py PRINTS_DIR STRATEGY NAME=SEG_DIR [NAME=SEG_DIR ...]   (NAME as in the prints dir)

Each fill is matched to the last public print before it (within 3 s) on its side at or through its
price. Distance is from the mid just before that print to our price, in bp. Markouts are against our
fill price (bp, + is good for us), weighted by $."""

import sys

import numpy as np
import pandas as pd
from twap import mid_at

BINS = [-1e9, 0.75, 1.5, 3, 5, 8, 12, 1e9]
LABELS = ["<0.75", "0.75-1.5", "1.5-3", "3-5", "5-8", "8-12", ">12"]


def main() -> None:
    d, strategy = sys.argv[1], sys.argv[2]
    rows = []
    for spec in sys.argv[3:]:
        name, seg = spec.split("=", 1)
        F = pd.read_json(seg + "/fills.jsonl", lines=True)
        F = F[F.strategy == strategy]
        P = pd.read_parquet(f"{d}/{name}.prints.parquet")
        M = pd.read_parquet(f"{d}/{name}.mids.parquet")
        end = M.t_ms.max()
        for coin, f in F.groupby("coin"):
            p, m = P[P.coin == coin], M[M.coin == coin].reset_index(drop=True)
            if p.empty or m.empty:
                continue
            pt, pside, ppx, pzero = p.t_ms.to_numpy(), p.side.to_numpy(), p.px.to_numpy(), p.zero.to_numpy()
            for r in f.itertuples():
                a, b = np.searchsorted(pt, r.t_ms - 3000), np.searchsorted(pt, r.t_ms, side="right")
                hit = None
                for i in range(b - 1, a - 1, -1):
                    if pside[i] == -r.side and (ppx[i] <= r.px if r.side > 0 else ppx[i] >= r.px):
                        hit = i
                        break
                if hit is None:
                    continue
                pre = mid_at(m, np.array([pt[hit]]), before=True)[0]
                res = {
                    "coin": coin,
                    "usd": r.px * r.qty,
                    "dist": r.side * (pre / r.px - 1) * 1e4,
                    "twap": bool(pzero[hit]),
                    "lag_ms": r.t_ms - pt[hit],
                }
                for h in (1, 10, 60, 300):
                    v = mid_at(m, np.array([pt[hit] + h * 1000]))[0] if pt[hit] + h * 1000 <= end else np.nan
                    res[f"mk{h}"] = r.side * (v / r.px - 1) * 1e4
                rows.append(res)
    R = pd.DataFrame(rows)
    R["bucket"] = pd.cut(R.dist, BINS, labels=LABELS)
    w = lambda g, c: float((g[c] * g.usd)[g[c].notna()].sum() / g.usd[g[c].notna()].sum())  # noqa: E731
    T = R.groupby("bucket", observed=True).apply(
        lambda g: pd.Series(
            {
                "fills": len(g),
                "usd": g.usd.sum(),
                "share": g.usd.sum() / R.usd.sum(),
                "mk1": w(g, "mk1"),
                "mk10": w(g, "mk10"),
                "mk60": w(g, "mk60"),
                "mk300": w(g, "mk300"),
                "pnl10_usd": (g.mk10 * g.usd).sum() / 1e4,
            }
        ),
        include_groups=False,
    )
    print(
        f"{strategy}: matched {len(R)} fills, ${R.usd.sum():,.0f}; median lag {R.lag_ms.median():.0f} ms; TWAP share {R[R.twap].usd.sum() / R.usd.sum():.3f}"
    )
    print(T.round(2).to_string())
    tw = R.groupby("twap").apply(
        lambda g: pd.Series({"usd": g.usd.sum(), "mk1": w(g, "mk1"), "mk10": w(g, "mk10"), "mk60": w(g, "mk60")}), include_groups=False
    )
    print(tw.round(2).to_string())


if __name__ == "__main__":
    main()
