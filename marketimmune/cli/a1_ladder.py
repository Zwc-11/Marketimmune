"""Train one A1 rung on the pre-registered tested days, one 8-day panel at a time.

    python -m marketimmune.cli.a1_ladder --coin BTC --rung l3_fee --model classifier
    python -m marketimmune.cli.a1_ladder --coin BTC --rung l3_fee --model quantile

A month-plus of BTC rows (about 350,000 a day) does not fit in memory as one training panel, so
each tested day runs ``train`` or ``train_quantile`` on its own window: the 7 days before it plus
the day. The fold is the one the full run would make. Its seed is 42 + the day's place in the
tested list, the ladder's "seed + fold number".

Each day's out-of-fold rows go to ``<out>/folds/<name>_<rung>/<date>.oof.parquet``, so a stopped
run resumes. At the end they are joined into ``<out>/<prefix><name>_<rung>.oof.parquet``, the file
``compare_rungs`` reads, with a summary JSON beside it (``leakage_safe`` only if every day's is).

Tested days: ``docs/preregistration/a1-speed-bids-2026.md``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

from marketimmune.cli import train, train_quantile
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.utils import parse_date_spec, shift_date

DISCOVERY = "20260506,20260513,20260520,20260527,20260603,20260610,20260617,20260624,20260701,20260708,20260715,20260722,20260729,20260805,20260812,20260819,20260826"
CONFIRMATION = "20260901..20261027,20261029..20261031"
FIRST_GOLD = "20260425"
TRAIN_DAYS = 7
SEED = 42


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", required=True)
    parser.add_argument("--rung", required=True)
    parser.add_argument("--model", choices=["classifier", "quantile"], required=True)
    parser.add_argument("--test-dates", default=f"{DISCOVERY},{CONFIRMATION}")
    parser.add_argument("--first-gold", default=FIRST_GOLD, help="no training data before this date (the rollout)")
    parser.add_argument("--horizon", default="10s")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("eval/a1"))
    parser.add_argument("--models-dir", type=Path, default=Path("data/models/a1"))
    parser.add_argument("--extra", default="", help="extra trainer arguments, space separated (tests only)")
    return parser.parse_args(argv)


def window(lake_root: Path, coin: str, date: str, first: str = FIRST_GOLD) -> list[str]:
    """The tested day and the ``TRAIN_DAYS`` before it that have Gold, from ``first``."""
    layout = HyperliquidLakeLayout(lake_root)
    days = [shift_date(date, -k) for k in range(TRAIN_DAYS, -1, -1)]
    return [d for d in days if d >= first and layout.gold_training_path(coin, d).exists()]


def run(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    name = f"a1_{coin.lower()}"
    prefix = "q_" if args.model == "quantile" else ""
    fold_dir = args.out / "folds" / f"{prefix}{name}_{args.rung}"
    fold_dir.mkdir(parents=True, exist_ok=True)
    tested = list(parse_date_spec(args.test_dates))
    days: list[dict[str, Any]] = []
    for k, date in enumerate(tested):
        oof = fold_dir / f"{date}.oof.parquet"
        report = fold_dir / f"{date}.json"
        seconds = None
        if not oof.exists():
            start = time.perf_counter()
            win = window(args.lake_root, coin, date, args.first_gold)
            assert win and win[-1] == date, f"{coin} {date}: no Gold partition for the tested day"
            common = ["--coin", coin, "--dates", ",".join(win), "--test-dates", date, "--horizon", args.horizon]
            common += ["--lake-root", str(args.lake_root), "--feature-set", args.rung, "--seed", str(SEED + k), "--report", str(report)]
            common += args.extra.split() if args.extra else []
            if args.model == "classifier":
                code = train.main([*common, "--model-out", str(args.models_dir / f"{name}_{args.rung}" / f"{date}.cbm")])
            else:
                code = train_quantile.main(common)
            assert code == 0, f"{coin} {args.rung} {args.model} {date}: trainer exited {code}"
            seconds = round(time.perf_counter() - start, 1)
            print(f"{prefix}{name}_{args.rung} {date} ({k + 1}/{len(tested)}): {seconds} s", flush=True)
        r = json.loads(report.read_text(encoding="utf-8"))
        day = {"date": date, "seed": SEED + k, "leakage_safe": bool(r.get("leakage_safe")), "rows": r.get("rows")}
        days.append(day if seconds is None else {**day, "seconds": seconds})
    frame = pd.concat([pd.read_parquet(fold_dir / f"{d['date']}.oof.parquet") for d in days], ignore_index=True)
    final = args.out / f"{prefix}{name}_{args.rung}.oof.parquet"
    frame.to_parquet(final, index=False)
    summary = {
        "coin": coin,
        "rung": args.rung,
        "model": args.model,
        "horizon": args.horizon,
        "tested_days": len(days),
        "rows_tested": len(frame),
        "leakage_safe": all(d["leakage_safe"] for d in days),
        "oof_predictions": str(final),
        "days": days,
    }
    final.with_name(final.name.removesuffix(".oof.parquet") + ".json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    s = run(parse_args(argv))
    print(
        f"{s['coin']} {s['rung']} {s['model']}: {s['tested_days']} days, {s['rows_tested']:,} rows tested, leakage_safe={s['leakage_safe']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
