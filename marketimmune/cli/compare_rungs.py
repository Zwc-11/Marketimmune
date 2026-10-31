"""Day-level test of one ladder rung against another, from two training runs.

    python -m marketimmune.cli.compare_rungs \\
        --base eval/sol_dec_l0_book.oof.parquet \\
        --challenger eval/sol_dec_l1_book.oof.parquet

Each ``.oof.parquet`` is written by ``marketimmune.cli.train`` next to its report.
Rows are matched on the fill key (date, time, price, size, maker side, taker
oid), so a rung that dropped rows (missing features) is compared on the rows both
evaluated. Reports Diebold-Mariano over daily mean losses and a stationary
bootstrap interval, overall and by regime:

* ``cex_move``: Binance moved at least ``--cex-move-bps`` over the second before
  the fill (net of feed latency); ``quiet`` is the rest;
* ``taker_liquidation``: the taker was the liquidation engine;
* ``forced_60s``: a forced (liquidation) fill hit either side in the 60 s before
  the fill (the plan's forced-flow regime).

Positive improvement = the challenger's loss is lower. For quantile-ladder runs
(``marketimmune.cli.train_quantile``) use ``--loss pinball --tau 0.1`` (or 0.5,
0.9): the target is the markout and the prediction the ``q10``/``q50``/``q90``
column.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.models.compare import LOSSES, compare_rungs
from marketimmune.models.decomposition import FORCED_60S
from marketimmune.models.quantile_ladder import quantile_column

REGIME_COLUMNS = ("cex_ret_1000ms_bps", "liquidation", *FORCED_60S)
KEY = ("partition_date", "ts_ms", "px", "sz", "maker_side", "oid", "tid")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--challenger", type=Path, required=True)
    parser.add_argument("--loss", choices=sorted(LOSSES), default="brier")
    parser.add_argument("--tau", type=float, default=0.5, help="quantile for --loss pinball")
    parser.add_argument("--cex-move-bps", type=float, default=2.0)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def keyed_by_fill(frame: pd.DataFrame, key: list[str]) -> pd.DataFrame:
    """A copy with the key columns as strings (dtypes differ between writers) and ``_dup``, the
    occurrence number of a repeated key, so duplicate fills are matched in order."""
    out = frame.copy()
    out[key] = out[key].astype(str)
    out["_dup"] = out.groupby(key, sort=False).cumcount()
    return out


def align(base: pd.DataFrame, challenger: pd.DataFrame, *, target: str = "label", prediction: str = "prob") -> pd.DataFrame:
    """Inner-join two OOF frames on the fill key: ``y_base``/``y_challenger`` hold ``target``
    and ``pred_base``/``pred_challenger`` hold ``prediction``."""
    key = [c for c in KEY if c in base.columns and c in challenger.columns]
    assert "ts_ms" in key, "OOF files need at least ts_ms to align"
    extra = [c for c in REGIME_COLUMNS if c in base.columns]
    b, c = (keyed_by_fill(f, key).rename(columns={target: "y", prediction: "pred"}) for f in (base, challenger))
    merged = b[[*key, "_dup", "y", "pred", *extra]].merge(
        c[[*key, "_dup", "y", "pred"]], on=[*key, "_dup"], suffixes=("_base", "_challenger")
    )
    assert np.allclose(merged["y_base"].astype(float), merged["y_challenger"].astype(float), equal_nan=True), (
        "labels disagree on matched rows: the runs used different horizons"
    )
    return merged


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base = pd.read_parquet(args.base)
    challenger = pd.read_parquet(args.challenger)
    if args.loss == "pinball":
        merged = align(base, challenger, target="markout_bps", prediction=quantile_column(args.tau))
    else:
        merged = align(base, challenger)
    regimes: dict[str, Any] = {}
    if "cex_ret_1000ms_bps" in merged.columns:
        move = np.abs(merged["cex_ret_1000ms_bps"].astype(float).to_numpy()) >= args.cex_move_bps
        regimes["cex_move"] = move
        regimes["quiet"] = ~move
    if "liquidation" in merged.columns:
        regimes["taker_liquidation"] = merged["liquidation"].fillna(False).astype(bool).to_numpy()
    if set(FORCED_60S) <= set(merged.columns):
        forced = merged[list(FORCED_60S)].astype(float).fillna(0.0).sum(axis=1).to_numpy()
        regimes["forced_60s"] = forced > 0.0
    result = compare_rungs(
        merged["partition_date"].to_numpy(),
        merged["y_base"].astype(float).to_numpy(),
        merged["pred_base"].to_numpy(),
        merged["pred_challenger"].to_numpy(),
        loss=args.loss,
        tau=args.tau,
        regimes=regimes,
        seed=args.seed,
    )
    payload = {
        "base": str(args.base),
        "challenger": str(args.challenger),
        "rows_base": len(base),
        "rows_challenger": len(challenger),
        "rows_matched": len(merged),
        "cex_move_bps": args.cex_move_bps,
        **result,
    }
    out = args.out or args.challenger.with_name(
        f"{args.challenger.stem.removesuffix('.oof')}_vs_{args.base.stem.removesuffix('.oof')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    for name in ("all", *regimes):
        entry = result.get(name, {})
        dm = entry.get("diebold_mariano", {})
        print(
            f"{name:<18} rows={entry.get('rows', 0):>9,} days={entry.get('days', 0):>3} "
            f"improved={entry.get('days_improved', 0):>3} "
            f"mean={entry.get('mean_daily_improvement', float('nan')):+.5f} "
            f"DM t={dm.get('t_stat', float('nan')):+.2f} p={dm.get('p_value', float('nan')):.4f} "
            f"CI95={entry.get('bootstrap_ci_95')}"
        )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
