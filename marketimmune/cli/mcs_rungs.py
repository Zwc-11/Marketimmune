"""Model Confidence Set over several rungs' out-of-fold predictions.

    python -m marketimmune.cli.mcs_rungs eval/sol_dec_l0_book.oof.parquet \\
        eval/sol_dec_l1_book.oof.parquet eval/sol_dec_l2_book.oof.parquet ...
    python -m marketimmune.cli.mcs_rungs --loss pinball --tau 0.1 eval/q_sol_dec_*.oof.parquet

Rows are restricted to fills every run evaluated (same key as ``compare_rungs``),
losses are averaged per day, and the MCS (T_max, stationary bootstrap over days)
reports which rungs are indistinguishable from the best at ``--alpha``.
Model names default to the file stems without ``.oof``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.cli.compare_rungs import KEY
from marketimmune.models.compare import LOSSES, daily_means, make_loss
from marketimmune.models.mcs import model_confidence_set
from marketimmune.models.quantile_ladder import quantile_column


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("oofs", nargs="+", type=Path)
    parser.add_argument("--loss", choices=sorted(LOSSES), default="brier")
    parser.add_argument("--tau", type=float, default=0.5)
    parser.add_argument("--alpha", type=float, default=0.10)
    parser.add_argument("--n-boot", type=int, default=5_000)
    parser.add_argument("--mean-block", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def common_rows(
    frames: dict[str, pd.DataFrame], *, target: str, prediction: str
) -> pd.DataFrame:
    """One row per fill every run evaluated: the key, the target, one column per model."""
    key = [c for c in KEY if all(c in f.columns for f in frames.values())]
    merged: pd.DataFrame | None = None
    for name, frame in frames.items():
        f = frame[[*key, target, prediction]].copy()
        for col in key:
            f[col] = f[col].astype(str)
        f["_dup"] = f.groupby(key, sort=False).cumcount()
        f = f.rename(columns={prediction: name, target: f"_y_{name}"})
        merged = f if merged is None else merged.merge(f, on=[*key, "_dup"])
    assert merged is not None
    ys = merged[[f"_y_{n}" for n in frames]].astype(float).to_numpy()
    if not np.allclose(ys, ys[:, :1], equal_nan=True):
        raise ValueError("targets disagree on matched rows: the runs used different horizons")
    merged["y"] = ys[:, 0]
    return merged.drop(columns=[f"_y_{n}" for n in frames])


def run(args: argparse.Namespace) -> dict[str, Any]:
    if len(args.oofs) < 2:
        raise SystemExit("give at least two .oof.parquet files")
    frames = {p.stem.removesuffix(".oof"): pd.read_parquet(p) for p in args.oofs}
    if args.loss == "pinball":
        target, prediction = "markout_bps", quantile_column(args.tau)
    else:
        target, prediction = "label", "prob"
    rows = common_rows(frames, target=target, prediction=prediction)
    fn = make_loss(args.loss, args.tau)
    days: list[Any] = []
    columns = []
    for name in frames:
        days, means, _counts = daily_means(fn(rows["y"].to_numpy(), rows[name].to_numpy()),
                                           rows["partition_date"].to_numpy())
        columns.append(means)
    result = model_confidence_set(
        np.column_stack(columns), list(frames), alpha=args.alpha, n_boot=args.n_boot,
        mean_block=args.mean_block, seed=args.seed,
    )
    return {
        "loss": args.loss,
        **({"tau": args.tau} if args.loss == "pinball" else {}),
        "files": [str(p) for p in args.oofs],
        "rows_common": len(rows),
        "days": len(days),
        **result.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run(args)
    out = args.out or args.oofs[0].with_name(
        f"mcs_{args.loss}{'_q' + str(round(args.tau * 100)) if args.loss == 'pinball' else ''}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"{payload['rows_common']:,} common rows over {payload['days']} days, "
          f"loss={payload['loss']}, alpha={payload['alpha']}")
    for m in payload["models"]:
        mark = "IN " if m["in_mcs"] else "out"
        print(f"  {mark} {m['name']:<28} mean_loss={m['mean_loss']:.6f} p={m['mcs_p_value']:.3f}")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
