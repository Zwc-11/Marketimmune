"""Train the v3 quantile ladder: maker markout quantiles per rung, out of fold.

    python -m marketimmune.cli.train_quantile --coin SOL --dates 20251201..20251231 \\
        --feature-set l1_book --horizon 1s --report eval/q_sol_dec_l1_book.json

Same Gold partitions, feature sets, rolling daily folds and leakage gate as
``marketimmune.cli.train``; the target is ``markout_bps_<horizon>`` (bps, maker
side, anchored at the pre-fill mid) instead of the toxic flag. Writes the report
and ``<report>.oof.parquet`` with ``q10``/``q50``/``q90`` (and climatology) per
tested fill, which ``marketimmune.cli.compare_rungs --loss pinball`` compares.

``--contrib`` adds the tau=0.5 model's TreeSHAP contributions per feature group, which
``marketimmune.cli.decompose --oof`` reads. Only the ``l3_book`` rung needs them, and on the
SOL month they cost more than fitting the three boosters (TreeSHAP walks every tree path
for every test row), so they are off by default.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.cli._train_data import (
    FEATURE_COLUMNS,
    OOF_EXTRA_COLUMNS,
    dataset_label,
    load_training_panel,
    partition_leakage_status,
    resolve_training_partitions,
    use_feature_set,
)
from marketimmune.features.training_rows import FEATURE_SETS
from marketimmune.models.cross_validation import CV_SCHEMES
from marketimmune.models.decomposition import feature_groups
from marketimmune.models.quantile_ladder import LgbParams, QuantileOOF, quantile_column, quantile_report, train_quantile_oof
from marketimmune.utils import parse_date_spec, parse_symbol_spec, split_csv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--coins", default="")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--feature-set", choices=sorted(FEATURE_SETS), default="l1_book")
    parser.add_argument("--horizon", default="1s", choices=["1s", "10s", "60s"])
    parser.add_argument("--taus", default="0.1,0.5,0.9")
    parser.add_argument("--cv-scheme", choices=CV_SCHEMES, default="rolling_daily")
    parser.add_argument("--train-days", type=int, default=7)
    parser.add_argument("--purge-ms", type=float, default=60_000.0)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--num-leaves", type=int, default=31)
    parser.add_argument("--min-child-samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report", type=Path, default=Path("eval/quantile_report.json"))
    parser.add_argument(
        "--contrib", action="store_true", help="also write per-group TreeSHAP contributions of the tau=0.5 model (cli.decompose reads them)"
    )
    return parser.parse_args(argv)


def write_quantile_oof(path: Path, frame: pd.DataFrame, oof: QuantileOOF, *, horizon: str, feature_set: str) -> Path:
    """Tested rows only: fill key, regime columns, label, markout and the quantiles."""
    tested = oof.tested
    keep = ["ts_ms", "partition_coin", "partition_date", "px", "sz", "maker_side", *OOF_EXTRA_COLUMNS]
    out = frame.loc[tested, [c for c in keep if c in frame.columns]].copy()
    out["label"] = frame.loc[tested, f"toxic_{horizon}"].to_numpy(dtype=bool)
    out["markout_bps"] = frame.loc[tested, f"markout_bps_{horizon}"].to_numpy(dtype=np.float64)
    for tau in oof.taus:
        out[quantile_column(tau)] = oof.predictions[tau][tested]
        out[f"clim_{quantile_column(tau)}"] = oof.climatology[tau][tested]
    for group, values in oof.contributions.items():
        out[f"contrib_{group}"] = values[tested]
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(out, preserve_index=False).replace_schema_metadata(
        {"feature_set": feature_set, "horizon": horizon, "model": "quantile"}
    )
    pq.write_table(table, path, compression="zstd")
    return path


def run(args: argparse.Namespace) -> dict[str, Any]:
    use_feature_set(args.feature_set)
    coins = parse_symbol_spec(args.coins or args.coin)
    partitions = resolve_training_partitions(args.lake_root, coins=coins, dates=parse_date_spec(args.dates))
    leakage_safe, leakage = partition_leakage_status(partitions)
    frame = load_training_panel(partitions, horizon=args.horizon)
    taus = tuple(float(t) for t in split_csv(args.taus))
    assert not args.contrib or 0.5 in taus, f"--contrib explains the tau=0.5 model: {taus=}"
    params = LgbParams(
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        num_leaves=args.num_leaves,
        min_child_samples=args.min_child_samples,
    )
    start = time.perf_counter()
    oof = train_quantile_oof(
        frame[FEATURE_COLUMNS].to_numpy(dtype=np.float32),
        frame[f"markout_bps_{args.horizon}"].to_numpy(dtype=np.float64),
        frame["ts_ms"].to_numpy(dtype=np.float64),
        taus=taus,
        params=params,
        train_days=args.train_days,
        purge_ms=args.purge_ms,
        seed=args.seed,
        contrib_tau=0.5 if args.contrib else None,
        contrib_groups=feature_groups(FEATURE_COLUMNS),
    )
    oof_path = write_quantile_oof(
        args.report.with_suffix(".oof.parquet"),
        frame,
        oof,
        horizon=args.horizon,
        feature_set=args.feature_set,
    )
    payload = {
        "model": "lightgbm_quantile",
        "dataset": dataset_label(partitions),
        "feature_set": args.feature_set,
        "feature_columns": list(FEATURE_COLUMNS),
        "horizon": args.horizon,
        "target": f"markout_bps_{args.horizon}",
        "cv_scheme": args.cv_scheme,
        "train_days": args.train_days,
        "leakage_safe": leakage_safe,
        "leakage_check": leakage,
        "rows": len(frame),
        "fit_elapsed_s": round(time.perf_counter() - start, 1),
        "folds": oof.fold_summaries,
        "oof_predictions": str(oof_path),
        **quantile_report(oof, frame[f"markout_bps_{args.horizon}"].to_numpy(dtype=np.float64)),
        "params": {
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "num_leaves": args.num_leaves,
            "min_child_samples": args.min_child_samples,
            "seed": args.seed,
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    payload = run(parse_args(argv))
    for name, entry in payload.get("per_tau", {}).items():
        print(
            f"{name}: pinball={entry['pinball']:.4f} climatology={entry['pinball_climatology']:.4f} "
            f"skill={entry['skill']:+.3f} hit_rate={entry['hit_rate']:.3f}"
        )
    if "interval" in payload:
        iv = payload["interval"]
        print(
            f"interval {iv['nominal']:.0%}: coverage={iv['coverage']:.3f} "
            f"width={iv['mean_width_bps']:.2f} bps; leakage_safe={payload['leakage_safe']}"
        )
    print(f"Wrote {payload['oof_predictions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
