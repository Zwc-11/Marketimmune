"""The difference in edge per fill between two strategies replayed together, with a paired interval.

usage: edge_diff.py STRATEGY_A STRATEGY_B SEG_DIR [SEG_DIR ...]

Edge per fill as in edge.py: the $-weighted 60 s markout against the fill price (the fee is the
same for both, so it cancels). The interval resamples the same 15-minute blocks for both strategies
(5,000 draws, seed 0), so an hour that is bad for both does not widen the difference. Blocks where
only one strategy filled are kept; a draw with no fills for one strategy is dropped. Also prints
10 s and 5 min."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "latency"))

from markouts import segment  # noqa: E402

BLOCK_MS, DRAWS, SEED = 900_000, 5_000, 0


def main() -> None:
    a, b, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
    F = pd.concat([segment(d) for d in dirs])
    F = F[F.strategy.isin([a, b])].copy()
    F["usd"] = F.px * F.qty
    F["block"] = F.t_ms // BLOCK_MS
    blocks = np.sort(F.block.unique())
    out: dict[str, object] = {"blocks": len(blocks)}
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(blocks), size=(DRAWS, len(blocks)))
    for h in (10, 60, 300):
        sums = {}
        for s in (a, b):
            g = F[F.strategy == s].assign(wx=lambda x, c=f"mk{h}": x[c] * x.usd).groupby("block").agg(wx=("wx", "sum"), w=("usd", "sum"))
            g = g.reindex(blocks, fill_value=0.0)
            sums[s] = (g.wx.to_numpy(), g.w.to_numpy())
        (wxa, wa), (wxb, wb) = sums[a], sums[b]
        point = wxa.sum() / wa.sum() - wxb.sum() / wb.sum()
        da, db = wa[idx].sum(axis=1), wb[idx].sum(axis=1)
        ok = (da > 0) & (db > 0)
        draws = wxa[idx].sum(axis=1)[ok] / da[ok] - wxb[idx].sum(axis=1)[ok] / db[ok]
        lo, hi = np.percentile(draws, [2.5, 97.5])
        out[f"diff{h}"] = (round(float(point), 2), round(float(lo), 2), round(float(hi), 2))
    print(f"{a} minus {b}", out)


if __name__ == "__main__":
    main()
