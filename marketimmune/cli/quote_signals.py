"""Quote-time S2/S3 signals for the block simulator: walk-forward markout quantiles on every L2 row.

    python -m marketimmune.cli.quote_signals --coin SOL --dates 20251201..20251231 --report eval/quote_signals_sol.json

For each test day of the ladder's rolling folds (from the 8th date with Gold rows), fit S2 and S3
(``marketimmune.sim.signals``) on the previous 7 days of Gold rows and write, for every Silver L2
row of the day, each model's 0.1/0.5/0.9 markout quantiles for a bid and for an ask to
``<out-dir>/<COIN>/<COIN>-<date>.parquet``. ``simulate_quotes --signals-dir`` reads them.

Before a day is scored, its quote-time features at Gold's fill times are checked against the
matrix the models train on (``check_against_gold``); a mismatch stops the run. The report scores
each model on the Gold rows it did not train on (pinball skill against the training window's
climatology, as ``train_quantile`` reports the ladder rungs) and gives, per day, the share of rows
each model cannot score and the share it would pull at ``--limit-bps``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.features.cex_gap import DEFAULT_LATENCY_MS
from marketimmune.features.training_rows import FEATURE_SETS
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.logger import init_logger
from marketimmune.models.quantile_ladder import DEFAULT_TAUS, PREREGISTERED, LgbParams, QuantileOOF, quantile_report
from marketimmune.sim.signals import (
    FILL_TIME_COLUMNS,
    QUOTE_RUNGS,
    SEED,
    SIDES,
    check_against_gold,
    day_folds,
    fit_quantiles,
    load_day_inputs,
    load_gold_day,
    predict_quantiles,
    predict_rows,
    quote_columns,
    quote_signals_path,
    signal_column,
)
from marketimmune.utils import parse_date_spec, split_csv

logger = init_logger(__name__)

FloatArray = npt.NDArray[np.float64]
DEFAULT_OUT_DIR = Path("data/gold/hyperliquid/quote_signals")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--models", default="s2,s3", help=f"from {sorted(QUOTE_RUNGS)}")
    parser.add_argument(
        "--score-dates", default=None, help="only these test dates (resume, or one day per call); the folds and seeds are the full run's"
    )
    parser.add_argument("--cex-latency-ms", type=float, default=DEFAULT_LATENCY_MS, help="as Gold's L1 columns")
    parser.add_argument("--limit-bps", type=float, default=2.0, help="for the report's pull share only")
    parser.add_argument(
        "--n-estimators", type=int, default=PREREGISTERED.n_estimators, help="tests only; the run uses the pre-registered 300"
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=Path("eval/quote_signals.json"))
    return parser.parse_args(argv)


def write_signals(path: Path, signals: dict[str, npt.NDArray[Any]]) -> None:
    """Write a day's signals, keeping the columns of models an earlier run scored on the same rows
    (``--models s2`` then ``--models s3`` gives the same file as one run)."""
    if path.exists():
        old = pq.read_table(path)
        if np.array_equal(old["ts_ns"].to_numpy(), signals["ts_ns"]):
            signals = {c: old[c].to_numpy() for c in old.column_names} | signals
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    pq.write_table(pa.table(signals), part, compression="zstd")
    part.replace(path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    coin = args.coin.upper()
    names = split_csv(args.models)
    assert names and all(n in QUOTE_RUNGS for n in names), f"{names=}: choose from {sorted(QUOTE_RUNGS)}"
    columns = {n: quote_columns(n) for n in names}
    union = list(dict.fromkeys(c for n in names for c in columns[n]))
    pick = {n: np.array([union.index(c) for c in columns[n]], dtype=np.intp) for n in names}
    layout = HyperliquidLakeLayout(args.lake_root)
    dates = [d for d in parse_date_spec(args.dates) if layout.gold_training_path(coin, d).exists()]
    assert dates, f"no Gold training partitions for {coin} {args.dates}"
    params = LgbParams(n_estimators=args.n_estimators)
    taus = DEFAULT_TAUS

    # The month's Gold rows as float32 (the trainers' dtype), in time order.
    parts = [load_gold_day(args.lake_root, coin, d, union) for d in dates]
    ts = np.concatenate([g.ts_ms for g in parts])
    y = np.concatenate([g.y for g in parts])
    labelled = np.concatenate([g.labelled for g in parts])
    x = np.concatenate([np.column_stack([g.features[c] for c in union]).astype(np.float32) for g in parts])
    del parts
    assert np.all(ts[1:] >= ts[:-1]), "Gold rows out of time order across dates"
    usable = labelled & np.isfinite(ts) & np.isfinite(y)
    rows = {n: np.flatnonzero(usable & np.isfinite(x[:, pick[n]]).all(axis=1)) for n in names}
    folds = {n: day_folds(ts[rows[n]]) for n in names}
    oof = {n: np.full((rows[n].size, len(taus)), np.nan) for n in names}
    clim = {n: np.full((rows[n].size, len(taus)), np.nan) for n in names}
    fold_log: dict[str, list[dict[str, Any]]] = {n: [] for n in names}

    days: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    score = set(parse_date_spec(args.score_dates)) if args.score_dates else set(dates)
    for date in (d for d in dates if d in score and any(d in folds[n] for n in names)):
        inputs = load_day_inputs(args.lake_root, args.binance_dir, coin, date)
        check = check_against_gold(inputs, load_gold_day(args.lake_root, coin, date, union), union, cex_latency_ms=args.cex_latency_ms)
        if not check["passed"]:
            raise SystemExit(f"{coin} {date}: quote-time features differ from Gold: {check}")
        models = {}
        for n in (n for n in names if date in folds[n]):
            fold_id, fold = folds[n][date]
            train, test = rows[n][fold.train], rows[n][fold.test]
            models[n] = fit_quantiles(x[np.ix_(train, pick[n])], y[train], seed=SEED + fold_id, params=params, taus=taus)
            oof[n][fold.test] = predict_quantiles(models[n], x[np.ix_(test, pick[n])])
            clim[n][fold.test] = np.quantile(y[train], taus)
            fold_log[n].append({"date": date, "fold_id": fold_id, "n_train": int(train.size), "n_test": int(test.size)})
        signals = predict_rows(inputs, models, columns, taus=taus, cex_latency_ms=args.cex_latency_ms)
        path = quote_signals_path(args.out_dir, coin, date)
        write_signals(path, signals)
        summary: dict[str, Any] = {"date": date, "l2_rows": int(signals["ts_ns"].size), "gold_check": check}
        for n in models:
            for side in SIDES:
                q10 = signals[signal_column(n, taus[0], side)]
                summary[f"{n}_{side}_unscored"] = float(np.isnan(q10).mean())
                summary[f"{n}_{side}_pull_share"] = float(np.mean(q10 < -args.limit_bps))
        summary["elapsed_s"] = round(time.perf_counter() - t0, 1)
        days.append(summary)
        logger.info(json.dumps({k: v for k, v in summary.items() if k != "gold_check"} | {"gold_check_passed": check["passed"]}))

    report: dict[str, Any] = {"coin": coin, "dates": args.dates, "out_dir": str(args.out_dir), "models": {}, "days": days}
    for n in names:
        tested = ~np.isnan(oof[n][:, 0])
        quantiles = QuantileOOF(
            taus=taus, predictions={t: oof[n][:, k] for k, t in enumerate(taus)}, climatology={t: clim[n][:, k] for k, t in enumerate(taus)}
        )
        report["models"][n] = {
            "rung": QUOTE_RUNGS[n],
            "dropped_fill_time_columns": [c for c in FEATURE_SETS[QUOTE_RUNGS[n]] if c in FILL_TIME_COLUMNS],
            "feature_columns": list(columns[n]),
            "rows": int(rows[n].size),
            "rows_tested": int(tested.sum()),
            "folds": fold_log[n],
            **quantile_report(quantiles, y[rows[n]]),
        }
    report["settings"] = {
        "cex_latency_ms": args.cex_latency_ms,
        "limit_bps": args.limit_bps,
        "n_estimators": args.n_estimators,
        "seed": SEED,
        "taus": list(taus),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    for n, m in report["models"].items():
        skill = " ".join(f"{q} {e['skill']:+.3f}" for q, e in m.get("per_tau", {}).items())
        print(f"{n} ({m['rung']} without fill-time columns): {m['rows_tested']} Gold rows tested, skill {skill}")
    print(f"Wrote {len(report['days'])} days of signals under {report['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
