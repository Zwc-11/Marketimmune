"""How likely a backtest's pick is luck from the number of settings tried (``paper.overfit``).

    python -m marketimmune.cli.paper_overfit --work data/paper/tune-guard/home/250x4 data/paper/tune-immune/home/250x4 \\
        --segments night/seg2-20261106T0448,night/seg3-20261106T0559,... --pick guard@z=0.05/w=1.5/win=5 \\
        --extra-trials 31 --out eval/paper/overfit_20261106.json

Every strategy replayed on the same segments in the work directories (the same recordings, so the
same 15-minute blocks; a strategy in several directories counts once) gives a column of block PnL
summed over the coins; ``--exclude`` leaves out controls nobody would pick, whose losses would
otherwise make any pick look good. On that matrix: the probability of backtest overfitting by CSCV, and the
deflated Sharpe ratio of ``--pick`` with every column, and ``--extra-trials`` more tried elsewhere
(as columns with the same spread of Sharpe ratios), counted as trials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.cli.paper_report import run_tables
from marketimmune.paper.overfit import deflated_sharpe, pbo_cscv


def matrix(work: list[Path], segments: list[str]) -> pd.DataFrame:
    cols: dict[str, pd.Series] = {}
    for w in work:
        parts = []
        for seg in segments:
            _, blocks, _ = run_tables(w / seg)
            blocks["block"] = seg + "/" + blocks["block"].str.split("/").str[-1]
            parts.append(blocks)
        b = pd.concat(parts)
        summed = b.groupby(["strategy", "block"])["pnl"].sum()
        for strategy in summed.index.get_level_values(0).unique():
            if strategy not in cols:
                cols[strategy] = summed.xs(strategy, level="strategy")
    return pd.DataFrame(cols).dropna()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--work", type=Path, nargs="+", required=True, help="config directories (e.g. .../250x4) holding <chain>/<segment> runs"
    )
    parser.add_argument("--segments", required=True, help="chain/segment names, comma-separated")
    parser.add_argument("--pick", required=True)
    parser.add_argument("--extra-trials", type=int, default=0, help="settings tried on these hours that are not in the work directories")
    parser.add_argument("--groups", type=int, default=8)
    parser.add_argument("--exclude", default="", help="regular expression: configs left out (controls nobody would pick)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    m = matrix(args.work, args.segments.split(","))
    if args.exclude:
        m = m.loc[:, ~m.columns.str.contains(args.exclude, regex=True)]
    pnl = m.to_numpy(np.float64)
    sharpes = pnl.mean(axis=0) / pnl.std(axis=0, ddof=1)
    trials = np.concatenate([sharpes, np.random.default_rng(0).choice(sharpes, args.extra_trials)]) if args.extra_trials else sharpes
    report: dict[str, Any] = {
        "blocks": int(pnl.shape[0]),
        "configs": list(m.columns),
        "pbo": pbo_cscv(pnl, args.groups),
        "pick": args.pick,
        "pick_usd_per_hour": round(float(m[args.pick].mean()) * 4, 2),
        "deflated": deflated_sharpe(m[args.pick].to_numpy(np.float64), trials),
        "best_in_sample": str(m.columns[int(np.argmax(pnl.mean(axis=0)))]),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "configs"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
