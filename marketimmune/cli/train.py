"""Train the CatBoost toxicity classifier on Gold training rows, out of fold by day.

    python -m marketimmune.cli.train --coin SOL --dates 20251201..20251231 --feature-set l1_book \\
        --horizon 1s --report eval/sol_dec_l1_book.json --model-out data/models/sol_dec_l1_book.cbm

Every tested day is scored by a model trained on the ``--train-days`` before it (rolling
daily walk-forward). Each model fits on the earliest ``1 - calibration_fraction`` of its
window and an isotonic calibrator on the rest, which that model never saw. Writes the
report, ``<report>.oof.parquet`` (one row per tested fill, read by compare_rungs, mcs_rungs
and simulate_policy) and a final model + calibrator fit the same way on every row, which
the server and ``export_web_model`` deploy.
"""

from __future__ import annotations

import json
import time
from collections.abc import Collection, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from catboost import CatBoostClassifier, Pool
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

from marketimmune.cli._train_args import parse_args
from marketimmune.cli._train_data import (
    FEATURE_COLUMNS,
    OOF_EXTRA_COLUMNS,
    TrainingPartition,
    dataset_label,
    load_training_panel,
    parse_date_spec,
    parse_symbol_spec,
    partition_leakage_status,
    partition_row_counts,
    resolve_training_partitions,
    use_feature_set,
)
from marketimmune.logger import init_logger
from marketimmune.models.cross_validation import FoldArrays, temporal_fold_arrays
from marketimmune.models.evaluation import (
    ThresholdSelection,
    evaluate_holdout_predictions,
    evaluate_markout_predictions,
    fold_local_markout_thresholds,
    select_markout_threshold,
)

# NOTE: not __name__, which is "__main__" under ``python -m`` and so outside the package logger.
logger = init_logger(__name__)

BASELINE_NAME = "event_ofi"
BASELINE_FEATURES = ["maker_side", "l2_ofi_10s"]
BASELINE_DESCRIPTION = "Snapshot-derived event OFI over a 10s rolling window, signed to maker side."
# Quoting-policy search: skip thresholds 0.05..0.95 with the quote rate kept in [0.2, 0.95].
THRESHOLD_GRID = tuple(k / 100 for k in range(5, 96))
MIN_QUOTE_RATE = 0.2
MAX_QUOTE_RATE = 0.95
LATENCY_SAMPLE_ROWS = 128
FloatArray = npt.NDArray[np.float64]
IndexArray = npt.NDArray[np.intp]


@dataclass(frozen=True, slots=True)
class CatBoostTrainingResult:
    """Out-of-fold probabilities (NaN where untested) plus the deployable model and calibrator."""

    probabilities: FloatArray
    raw_probabilities: FloatArray
    fold_summaries: list[dict[str, Any]]
    model: CatBoostClassifier
    calibrator: IsotonicRegression | None
    folds: tuple[FoldArrays, ...]


def feature_matrix(frame: pd.DataFrame) -> npt.NDArray[np.float32]:
    """C-contiguous float32 rows (CatBoost quantizes to float32 anyway)."""
    return np.ascontiguousarray(frame[FEATURE_COLUMNS].to_numpy(dtype=np.float32))


def train_oof_catboost(
    frame: pd.DataFrame,
    *,
    horizon: str,
    purge_ms: float,
    train_days: int,
    iterations: int,
    learning_rate: float,
    depth: int,
    seed: int,
    calibration_fraction: float = 0.2,
    test_days: Collection[str] | None = None,
) -> CatBoostTrainingResult:
    assert 0.0 <= calibration_fraction < 1.0, f"{calibration_fraction=}"
    timestamps = frame["ts_ms"].to_numpy(dtype=np.float64)
    y = frame[f"toxic_{horizon}"].to_numpy(dtype=np.int8)
    x = feature_matrix(frame)

    def fit(rows: IndexArray, random_seed: int) -> tuple[CatBoostClassifier, IsotonicRegression | None, int, int] | None:
        model_rows, calibration_rows = split_model_calibration_indices(rows, timestamps, calibration_fraction=calibration_fraction)
        if np.unique(y[model_rows]).size < 2:
            return None
        # NOTE: no eval_metric. Without an eval set it changes nothing in the model but costs
        # a PR-AUC over the training rows every iteration (2.5x the fit time).
        model = CatBoostClassifier(
            iterations=iterations,
            learning_rate=learning_rate,
            depth=depth,
            loss_function="Logloss",
            random_seed=random_seed,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(Pool(x[model_rows], y[model_rows], feature_names=FEATURE_COLUMNS))
        calibrator = (
            fit_isotonic_calibrator(model.predict_proba(x[calibration_rows])[:, 1], y[calibration_rows]) if calibration_rows.size else None
        )
        return model, calibrator, int(model_rows.size), int(calibration_rows.size)

    probabilities = np.full(len(frame), np.nan)
    raw_probabilities = np.full(len(frame), np.nan)
    fold_summaries: list[dict[str, Any]] = []
    folds = temporal_fold_arrays(timestamps, purge_ms=purge_ms, train_days=train_days, test_days=test_days)
    for fold_id, fold in enumerate(folds, start=1):
        sizes = {"fold_id": fold_id, "n_train": int(fold.train.size)}
        fitted = fit(fold.train, seed + fold_id)
        if fitted is None:
            fold_summaries.append(
                {
                    **sizes,
                    "n_model_train": 0,
                    "n_calibration": 0,
                    "n_test": int(fold.test.size),
                    "calibrated": False,
                    "skipped": "train slice has one class",
                }
            )
            continue
        model, calibrator, n_model, n_calibration = fitted
        raw = model.predict_proba(x[fold.test])[:, 1]
        raw_probabilities[fold.test] = raw
        probabilities[fold.test] = apply_isotonic_calibrator(calibrator, raw)
        fold_summaries.append(
            {
                **sizes,
                "n_model_train": n_model,
                "n_calibration": n_calibration,
                "n_test": int(fold.test.size),
                "calibrated": calibrator is not None,
            }
        )
    assert not np.all(np.isnan(raw_probabilities)), "no fold model was trained"
    # Fix B4: the deployed calibrator is fit on the final model's own scores for the latest
    # ``calibration_fraction`` of the rows, which that model never saw.
    final = fit(np.arange(len(frame), dtype=np.intp), seed)
    assert final is not None, "the final training slice has one class"
    return CatBoostTrainingResult(probabilities, raw_probabilities, fold_summaries, final[0], final[1], folds)


def split_model_calibration_indices(
    train_indices: npt.ArrayLike,
    timestamps: FloatArray,
    *,
    calibration_fraction: float,
) -> tuple[IndexArray, IndexArray]:
    """Reserve the latest rows (by time, then index) for calibration: at least 2, never all."""
    indices = np.asarray(train_indices, dtype=np.intp)
    if calibration_fraction <= 0.0 or indices.size < 3:
        return indices, np.empty(0, dtype=np.intp)
    ordered = indices[np.lexsort((indices, timestamps[indices]))]
    calibration_size = min(max(2, int(round(ordered.size * calibration_fraction))), ordered.size - 1)
    split_at = ordered.size - calibration_size
    return ordered[:split_at], ordered[split_at:]


def fit_isotonic_calibrator(raw_probabilities: FloatArray, labels: npt.NDArray[Any]) -> IsotonicRegression | None:
    """Isotonic map from raw to calibrated probability; None unless both classes are present."""
    if raw_probabilities.size < 2 or np.unique(labels).size < 2:
        return None
    calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    calibrator.fit(raw_probabilities.astype(float), labels.astype(int))
    return calibrator


def apply_isotonic_calibrator(calibrator: IsotonicRegression | None, raw_probabilities: FloatArray) -> FloatArray:
    if calibrator is None:
        return raw_probabilities.astype(float)
    return np.clip(np.asarray(calibrator.predict(raw_probabilities.astype(float)), dtype=float), 0.0, 1.0)


def write_isotonic_calibrator(path: Path, calibrator: IsotonicRegression | None, *, metadata: Mapping[str, Any]) -> None:
    """The JSON calibrator ``marketimmune.serving.scorer.IsotonicCalibrator`` loads."""
    payload: dict[str, Any] = {"method": "isotonic", "enabled": calibrator is not None, **metadata}
    if calibrator is not None:
        payload["x_thresholds"] = calibrator.X_thresholds_.tolist()
        payload["y_thresholds"] = calibrator.y_thresholds_.tolist()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def event_ofi_probabilities(frame: pd.DataFrame) -> FloatArray:
    """Event-level OFI baseline, signed to the maker's adverse-selection side. Rows with no book
    (the 2026 trade-only rungs) use the taker flow toward the maker over 10 s instead
    (``features.trade_state``), which is already signed to the maker."""
    if "l2_ofi_10s" in frame.columns:
        signed_risk = -(frame["maker_side"].to_numpy(dtype=np.float64) * frame["l2_ofi_10s"].to_numpy(dtype=np.float64))
    else:
        signed_risk = -frame["flow_maker_10000ms"].to_numpy(dtype=np.float64)
    return np.asarray(0.5 + 0.5 * np.tanh(signed_risk), dtype=np.float64)


def write_oof_predictions(
    path: Path,
    frame: pd.DataFrame,
    *,
    horizon: str,
    probabilities: FloatArray,
    raw_probabilities: FloatArray,
    baseline_probabilities: FloatArray,
    feature_set: str,
) -> Path:
    """One row per tested fill: row key, regime columns, label, markout and the three
    probabilities, for day-level rung tests (``marketimmune.cli.compare_rungs``)."""
    keep = ("ts_ms", "partition_coin", "partition_date", "px", "sz", "maker_side", *OOF_EXTRA_COLUMNS)
    out = frame[[c for c in keep if c in frame.columns]].copy()
    out["label"] = frame[f"toxic_{horizon}"].to_numpy(dtype=bool)
    out["markout_bps"] = frame[f"markout_bps_{horizon}"].to_numpy(dtype=np.float64)
    out["prob"] = probabilities
    out["raw_prob"] = raw_probabilities
    out["baseline_prob"] = baseline_probabilities
    out.attrs = {}
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(out, preserve_index=False).replace_schema_metadata({"feature_set": feature_set, "horizon": horizon})
    pq.write_table(table, path, compression="zstd")
    return path


def evaluate_holdout_split(
    holdout_frame: pd.DataFrame,
    *,
    horizon: str,
    train_rows: int,
    model_name: str,
    raw_probabilities: FloatArray,
    probabilities: FloatArray,
    candidate_threshold: float,
    baseline_threshold: float,
) -> dict[str, Any]:
    """The final model and the baseline on later, unseen dates at their deployment thresholds."""
    timestamps = holdout_frame["ts_ms"].to_numpy(dtype=np.float64)
    labels = holdout_frame[f"toxic_{horizon}"].to_numpy(dtype=bool)
    markouts = holdout_frame[f"markout_bps_{horizon}"].to_numpy(dtype=np.float64)

    def evaluate(name: str, values: FloatArray, threshold: float) -> dict[str, Any]:
        return evaluate_holdout_predictions(
            timestamps, labels, values, markouts, model_name=name, train_rows=train_rows, decision_threshold=threshold
        ).to_dict()

    candidate = evaluate(f"{model_name}_holdout", probabilities, candidate_threshold)
    baseline = evaluate(f"{BASELINE_NAME}_{horizon}_holdout", event_ofi_probabilities(holdout_frame), baseline_threshold)
    return {
        **candidate,
        "partition_rows": partition_row_counts(holdout_frame),
        "uncalibrated": evaluate(f"{model_name}_holdout_raw", raw_probabilities, candidate_threshold),
        "baselines": {BASELINE_NAME: {**baseline, "feature_columns": BASELINE_FEATURES, "description": BASELINE_DESCRIPTION}},
        "baseline_comparison": {BASELINE_NAME: metric_deltas(candidate, baseline)},
        "policy": {"candidate_decision_threshold": candidate_threshold, "baseline_decision_threshold": baseline_threshold},
    }


def metric_deltas(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float]:
    """Candidate minus baseline for the headline metrics."""
    return {key: float(candidate[key]) - float(baseline[key]) for key in ("pr_auc", "brier", "ece", "markout_lift_bps", "quote_rate")}


def estimate_prediction_latency_p95_ms(model: CatBoostClassifier, frame: pd.DataFrame) -> float:
    """p95 of single-row float32 predictions, the path the deployed scorer takes per fill."""
    sample = feature_matrix(frame.iloc[:LATENCY_SAMPLE_ROWS])
    durations_ms: list[float] = []
    for row in range(sample.shape[0]):
        start = time.perf_counter()
        model.predict_proba(sample[row : row + 1])
        durations_ms.append((time.perf_counter() - start) * 1000.0)
    return float(np.percentile(durations_ms, 95))


def _policy(
    probabilities: FloatArray, markouts: FloatArray, valid: npt.NDArray[np.bool_], folds: tuple[FoldArrays, ...]
) -> tuple[FloatArray, tuple[dict[str, Any], ...], ThresholdSelection]:
    """Fold-local thresholds for scoring, plus the threshold to deploy (chosen on all OOF rows)."""
    bounds = {"min_quote_rate": MIN_QUOTE_RATE, "max_quote_rate": MAX_QUOTE_RATE}
    thresholds, summaries = fold_local_markout_thresholds(probabilities, markouts, folds=folds, threshold_grid=THRESHOLD_GRID, **bounds)
    return thresholds, summaries, select_markout_threshold(probabilities[valid], markouts[valid], THRESHOLD_GRID, **bounds)


def _partition_list(partitions: tuple[TrainingPartition, ...]) -> list[dict[str, str]]:
    return [{"coin": p.coin, "date": p.date, "path": str(p.path)} for p in partitions]


def _joined(values: tuple[str, ...]) -> str:
    return values[0] if len(values) == 1 else ",".join(values)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    use_feature_set(args.feature_set)
    coins, dates = parse_symbol_spec(args.coins), parse_date_spec(args.dates)
    holdout_dates = parse_date_spec(args.holdout_dates) if args.holdout_dates else ()
    partitions = resolve_training_partitions(args.lake_root, coins=coins, dates=dates)
    holdout_partitions = resolve_training_partitions(args.lake_root, coins=coins, dates=holdout_dates) if holdout_dates else ()
    label = dataset_label(partitions)
    leakage_safe, leakage_details = partition_leakage_status(partitions + holdout_partitions)
    logger.info("loading %d partition(s): %s", len(partitions), label)
    if not leakage_safe:
        logger.warning("not every partition has a passing no-look-ahead report: leakage_safe=false")
    frame = load_training_panel(partitions, horizon=args.horizon)
    labels = frame[f"toxic_{args.horizon}"].to_numpy(dtype=bool)
    markouts = frame[f"markout_bps_{args.horizon}"].to_numpy(dtype=np.float64)
    logger.info("rows=%d toxic_rate=%.3f window=%d->%d", len(frame), labels.mean(), frame["ts_ms"].min(), frame["ts_ms"].max())

    # The holdout read overlaps the CatBoost fits (both release the GIL).
    with ThreadPoolExecutor(max_workers=1) as prefetch:
        holdout_future = prefetch.submit(load_training_panel, holdout_partitions, horizon=args.horizon) if holdout_partitions else None
        start = time.perf_counter()
        result = train_oof_catboost(
            frame,
            horizon=args.horizon,
            purge_ms=args.purge_ms,
            train_days=args.train_days,
            iterations=args.iterations,
            learning_rate=args.learning_rate,
            depth=args.depth,
            seed=args.seed,
            calibration_fraction=args.calibration_fraction,
            test_days=set(parse_date_spec(args.test_dates)) if args.test_dates else None,
        )
        elapsed_s = time.perf_counter() - start
    probabilities, raw_probabilities, folds = result.probabilities, result.raw_probabilities, result.folds
    valid = ~np.isnan(probabilities)
    baseline_probabilities = event_ofi_probabilities(frame)
    baseline_probabilities[~valid] = np.nan
    candidate_thresholds, candidate_folds, candidate_deployment = _policy(probabilities, markouts, valid, folds)
    baseline_thresholds, baseline_folds, baseline_deployment = _policy(baseline_probabilities, markouts, valid, folds)

    def evaluate(name: str, values: FloatArray, thresholds: FloatArray) -> dict[str, Any]:
        return evaluate_markout_predictions(
            labels, values, markouts, model_name=name, folds=folds, thresholds=thresholds, purge_ms=args.purge_ms, leakage_safe=leakage_safe
        ).to_dict()

    model_name = f"catboost_markout_{label}_{args.horizon}"
    report = evaluate(model_name, probabilities, candidate_thresholds)
    raw_report = evaluate(f"{model_name}_raw", raw_probabilities, candidate_thresholds)
    baseline_report = {
        **evaluate(f"{BASELINE_NAME}_{args.horizon}", baseline_probabilities, baseline_thresholds),
        "feature_columns": BASELINE_FEATURES,
        "description": BASELINE_DESCRIPTION,
    }
    calibrator = result.calibrator
    calibrator_out = args.calibrator_out or args.model_out.with_suffix(".isotonic.json")
    tested = frame.loc[valid]
    payload: dict[str, Any] = {
        **report,
        "latency_p95_ms": estimate_prediction_latency_p95_ms(result.model, frame),
        "baselines": {BASELINE_NAME: baseline_report},
        "baseline_comparison": {BASELINE_NAME: metric_deltas(report, baseline_report)},
        "coin": _joined(coins),
        "date": _joined(dates),
        "coins": list(coins),
        "dates": list(dates),
        "dataset_label": label,
        "partitions": _partition_list(partitions),
        "partition_rows": partition_row_counts(tested),
        "horizon": args.horizon,
        "cv_scheme": args.cv_scheme,
        "train_days": args.train_days,
        "feature_set": args.feature_set,
        "leakage_check": leakage_details,
        "training_rows": len(frame),
        "oof_rows": int(valid.sum()),
        "feature_columns": FEATURE_COLUMNS,
        "fold_training": result.fold_summaries,
        "fit_elapsed_s": elapsed_s,
        "uncalibrated": raw_report,
        "policy": {
            "threshold_mode": "auto_fold_local",
            "decision_threshold": None,
            "deployment_decision_threshold": candidate_deployment.threshold,
            "threshold_grid": list(THRESHOLD_GRID),
            "min_quote_rate": MIN_QUOTE_RATE,
            "max_quote_rate": MAX_QUOTE_RATE,
            "candidate_threshold_folds": list(candidate_folds),
            "candidate_deployment_selection": candidate_deployment.to_dict(),
            "baseline_threshold_folds": list(baseline_folds),
            "baseline_deployment_selection": baseline_deployment.to_dict(),
        },
        "calibration": {
            "method": "isotonic",
            "enabled": args.calibration_fraction > 0.0,
            "calibration_fraction": args.calibration_fraction,
            "calibrator_artifact": str(calibrator_out),
            "brier_delta": report["brier"] - raw_report["brier"],
            "ece_delta": report["ece"] - raw_report["ece"],
        },
        "catboost": {"iterations": args.iterations, "learning_rate": args.learning_rate, "depth": args.depth, "seed": args.seed},
    }
    if holdout_future is not None:
        holdout_frame = holdout_future.result()
        holdout_raw = result.model.predict_proba(feature_matrix(holdout_frame))[:, 1]
        payload["holdout_split"] = {
            **evaluate_holdout_split(
                holdout_frame,
                horizon=args.horizon,
                train_rows=len(frame),
                model_name=model_name,
                raw_probabilities=holdout_raw,
                probabilities=apply_isotonic_calibrator(calibrator, holdout_raw),
                candidate_threshold=candidate_deployment.threshold,
                baseline_threshold=baseline_deployment.threshold,
            ),
            "coins": list(coins),
            "dates": list(holdout_dates),
            "dataset_label": dataset_label(holdout_partitions),
            "partitions": _partition_list(holdout_partitions),
        }
    payload["oof_predictions"] = str(
        write_oof_predictions(
            args.report.with_suffix(".oof.parquet"),
            tested,
            horizon=args.horizon,
            probabilities=probabilities[valid],
            raw_probabilities=raw_probabilities[valid],
            baseline_probabilities=baseline_probabilities[valid],
            feature_set=args.feature_set,
        )
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    result.model.save_model(str(args.model_out))
    write_isotonic_calibrator(
        calibrator_out,
        calibrator,
        metadata={
            "coin": payload["coin"],
            "date": payload["date"],
            "coins": list(coins),
            "dates": list(dates),
            "dataset_label": label,
            "horizon": args.horizon,
            "source": "final_model_calibration_tail",
            "policy_threshold_mode": "auto_fold_local",
            "deployment_decision_threshold": candidate_deployment.threshold,
            "feature_columns": FEATURE_COLUMNS,
            "training_rows": len(frame),
            "oof_rows": int(valid.sum()),
        },
    )
    logger.info(
        "PR-AUC=%.3f Brier=%.3f markout_lift_bps=%.3f quote_rate=%.3f threshold=%.3f latency_p95_ms=%.3f baseline_delta_bps=%.3f",
        report["pr_auc"],
        report["brier"],
        report["markout_lift_bps"],
        report["quote_rate"],
        candidate_deployment.threshold,
        payload["latency_p95_ms"],
        payload["baseline_comparison"][BASELINE_NAME]["markout_lift_bps"],
    )
    logger.info("wrote %s, %s, %s and %s", args.report, payload["oof_predictions"], args.model_out, calibrator_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
