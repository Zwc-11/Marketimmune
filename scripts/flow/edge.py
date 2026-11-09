"""The edge per fill of one strategy, with an interval: the fills' markout net of the maker fee.

usage: edge.py STRATEGY FEE_BPS SEG_DIR [SEG_DIR ...]

For each fill: side * (mid h seconds later / fill price - 1), in bp, from the segment's own
mids.parquet (as scripts/latency/markouts.py). The statistic is the $-weighted mean at 60 s minus the
fee. Its 95% interval resamples 15-minute blocks of fills with replacement (5,000 draws, seed 0), so
fills of one burst stay together. Also prints 10 s and 5 min."""

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "latency"))
from markouts import segment  # noqa: E402

BLOCK_MS, DRAWS, SEED = 900_000, 5_000, 0


def main() -> None:
    strategy, fee, dirs = sys.argv[1], float(sys.argv[2]), sys.argv[3:]
    F = pd.concat([segment(d) for d in dirs])
    F = F[F.strategy == strategy].copy()
    F["usd"] = F.px * F.qty
    F["block"] = F.t_ms // BLOCK_MS
    out = {"fills": len(F), "usd": round(float(F.usd.sum())), "blocks": int(F.block.nunique())}
    rng = np.random.default_rng(SEED)
    for h in (10, 60, 300):
        col = f"mk{h}"
        g = F.assign(wx=F[col] * F.usd).groupby("block").agg(wx=("wx", "sum"), w=("usd", "sum"))
        wx, w = g.wx.to_numpy(), g.w.to_numpy()
        point = wx.sum() / w.sum() - fee
        idx = rng.integers(0, len(g), size=(DRAWS, len(g)))
        draws = wx[idx].sum(axis=1) / w[idx].sum(axis=1) - fee
        lo, hi = np.percentile(draws, [2.5, 97.5])
        out[f"net{h}"] = (round(float(point), 2), round(float(lo), 2), round(float(hi), 2))
    print(strategy, out)


if __name__ == "__main__":
    main()
