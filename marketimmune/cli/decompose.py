"""Decompose adverse selection into latency-arb, forced and residual parts.

    python -m marketimmune.cli.decompose --coin SOL --dates 20251201..20251231
    python -m marketimmune.cli.decompose --oof eval/q_sol_dec_l3_book.oof.parquet

Without ``--oof`` it reads Gold and splits the quote-everything maker's realised
spread and adverse selection by regime (stale quote by the CEX gap, forced flow in
the previous 60 s, both, quiet); no model is involved. With ``--oof`` (written by
``train_quantile`` with contributions, the default) it reports each feature group's
share of predicted adverse selection, overall and in the comparison regimes
(``cex_move``, ``forced_60s``, ``quiet``), with day-bootstrap intervals. See
``marketimmune.models.decomposition``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.cli.simulate_policy import load_gold
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.models.decomposition import FORCED_60S, GROUPS, contribution_shares, realised_decomposition
from marketimmune.utils import parse_date_spec, split_csv

REALISED_COLUMNS = ("cex_gap_maker_bps", *FORCED_60S)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--horizons", default="1s,10s,60s")
    parser.add_argument("--cex-move-bps", type=float, default=2.0)
    parser.add_argument("--oof", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def model_based(oof: pd.DataFrame, cex_move_bps: float) -> dict[str, Any]:
    missing = [g for g in GROUPS if f"contrib_{g}" not in oof.columns]
    if missing:
        raise SystemExit(f"OOF has no contributions for {missing}; rerun train_quantile without --no-contrib")
    contrib = {g: oof[f"contrib_{g}"].to_numpy(np.float64) for g in GROUPS}
    days = oof["partition_date"].astype(str).to_numpy()
    regimes: dict[str, Any] = {"all": None}
    if "cex_ret_1000ms_bps" in oof.columns:
        move = np.abs(oof["cex_ret_1000ms_bps"].astype(float).to_numpy()) >= cex_move_bps
        regimes["cex_move"], regimes["quiet"] = move, ~move
    if set(FORCED_60S) <= set(oof.columns):
        regimes["forced_60s"] = oof[list(FORCED_60S)].astype(float).fillna(0.0).sum(axis=1).to_numpy() > 0.0
    return {name: contribution_shares(contrib, days, mask=mask) for name, mask in regimes.items()}


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.oof is not None:
        oof = pd.read_parquet(args.oof)
        return {"source": str(args.oof), "kind": "model_contributions", **model_based(oof, args.cex_move_bps)}
    layout = HyperliquidLakeLayout(args.lake_root)
    gold = load_gold(layout, args.coin.upper(), parse_date_spec(args.dates), REALISED_COLUMNS)
    out: dict[str, Any] = {"coin": args.coin.upper(), "dates": args.dates, "kind": "realised_by_regime", "cex_bps": args.cex_move_bps}
    for h in split_csv(args.horizons):
        out[h] = realised_decomposition(gold, h, cex_bps=args.cex_move_bps)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    out = args.out or (
        args.oof.with_suffix(".decomposition.json") if args.oof else Path("eval") / f"decomposition_{args.coin.lower()}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2)[:2500])
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
