"""Train a CatBoost toxicity model on Hyperliquid Gold training rows."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # Executed as `python scripts/train_hyperliquid_markout.py`: put the repo root on
    # sys.path so the `scripts.*` imports below resolve the same way `-m` does.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

from marketimmune.models.markout_evaluation import (
    evaluate_holdout_predictions,
    evaluate_markout_predictions,
    fold_local_markout_thresholds,
    select_markout_threshold,
)
from marketimmune.models.walk_forward import CvScheme, FoldArrays, temporal_fold_arrays
from scripts.hyperliquid_markout_args import parse_args
from scripts.hyperliquid_markout_data import (
    FEATURE_COLUMNS,
    dataset_label,
    load_training_panel,
    parse_date_spec,
    parse_symbol_spec,
    parse_threshold_grid,
    partition_leakage_status,
    partition_row_counts,
    requested_training_partitions,
    resolve_training_partitions,
    split_existing_missing_partitions,
    use_feature_set,
)

BASELINE_NAME = "event_ofi"


@dataclass(frozen=True, slots=True)
class CatBoostTrainingResult:
    """Out-of-fold CatBoost predictions plus deployable artifacts."""

    probabilities: np.ndarray
    raw_probabilities: np.ndarray
    fold_summaries: list[dict[str, Any]]
    model: Any
    calibrator: Any | None
    folds: tuple[FoldArrays, ...]


def feature_matrix(frame: pd.DataFrame) -> np.ndarray:
    """Contiguous float32 feature matrix (CatBoost quantizes to float32 anyway)."""
    return np.ascontiguousarray(frame[FEATURE_COLUMNS].to_numpy(dtype=np.float32))


def train_oof_catboost(
    frame: pd.DataFrame,
    *,
    horizon: str,
    n_splits: int,
    purge_ms: float,
    embargo_ms: float,
    iterations: int,
    learning_rate: float,
    depth: int,
    seed: int,
    calibration_fraction: float = 0.2,
    scheme: CvScheme = "walk_forward",
    train_days: int | None = None,
) -> CatBoostTrainingResult:
    try:
        from catboost import CatBoostClassifier, Pool
    except ImportError as exc:  # pragma: no cover - environment boundary.
        raise RuntimeError("Install CatBoost first: python -m pip install catboost") from exc

    if calibration_fraction < 0.0 or calibration_fraction >= 1.0:
        raise ValueError("calibration_fraction must be in [0, 1)")

    timestamps = frame["ts_ms"].to_numpy(dtype=np.float64)
    y = frame[f"toxic_{horizon}"].to_numpy(dtype=np.int8)
    x = feature_matrix(frame)
    probabilities = np.full(len(frame), np.nan, dtype=np.float64)
    raw_probabilities = np.full(len(frame), np.nan, dtype=np.float64)
    fold_summaries: list[dict[str, Any]] = []

    def classifier(random_seed: int) -> Any:
        return CatBoostClassifier(
            iterations=iterations,
            learning_rate=learning_rate,
            depth=depth,
            loss_function="Logloss",
            eval_metric="PRAUC",
            random_seed=random_seed,
            verbose=False,
            allow_writing_files=False,
        )

    folds = temporal_fold_arrays(
        timestamps,
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        scheme=scheme,
        train_days=train_days,
    )
    for fold_id, fold in enumerate(folds, start=1):
        model_indices, calibration_indices = split_model_calibration_indices(
            fold.train,
            timestamps,
            calibration_fraction=calibration_fraction,
        )
        if np.unique(y[model_indices]).size < 2:
            fold_summaries.append(_skipped_fold(fold_id, fold, "train slice has one class"))
            continue
        model = classifier(seed + fold_id)
        model.fit(Pool(x[model_indices], y[model_indices], feature_names=FEATURE_COLUMNS))
        test_raw = model.predict_proba(x[fold.test])[:, 1]
        raw_probabilities[fold.test] = test_raw
        calibrator = None
        if calibration_indices.size:
            calibration_raw = model.predict_proba(x[calibration_indices])[:, 1]
            calibrator = fit_isotonic_calibrator(calibration_raw, y[calibration_indices])
        probabilities[fold.test] = apply_isotonic_calibrator(calibrator, test_raw)
        fold_summaries.append({
            "fold_id": fold_id,
            "n_train": int(fold.train.size),
            "n_model_train": int(model_indices.size),
            "n_calibration": int(calibration_indices.size),
            "n_test": int(fold.test.size),
            "calibrated": calibrator is not None,
        })

    valid_raw = ~np.isnan(raw_probabilities)
    if not np.any(valid_raw):
        raise ValueError("no model was trained")
    # Fix B4: the deployed calibrator is fit on the final model's own scores for the
    # latest ``calibration_fraction`` of the window, which that model never saw.
    # (It used to be fit on the fold models' out-of-fold scores and then applied to
    # a different model trained on every row.)
    final_model_idx, final_cal_idx = split_model_calibration_indices(
        np.arange(len(frame), dtype=np.intp),
        timestamps,
        calibration_fraction=calibration_fraction,
    )
    final_model = classifier(seed)
    final_model.fit(Pool(x[final_model_idx], y[final_model_idx], feature_names=FEATURE_COLUMNS))
    final_calibrator = (
        fit_isotonic_calibrator(
            final_model.predict_proba(x[final_cal_idx])[:, 1], y[final_cal_idx]
        )
        if final_cal_idx.size
        else None
    )
    return CatBoostTrainingResult(
        probabilities=probabilities,
        raw_probabilities=raw_probabilities,
        fold_summaries=fold_summaries,
        model=final_model,
        calibrator=final_calibrator,
        folds=folds,
    )


def _skipped_fold(fold_id: int, fold: FoldArrays, reason: str) -> dict[str, Any]:
    return {
        "fold_id": fold_id,
        "n_train": int(fold.train.size),
        "n_model_train": 0,
        "n_calibration": 0,
        "n_test": int(fold.test.size),
        "calibrated": False,
        "skipped": reason,
    }


def split_model_calibration_indices(
    train_indices: Sequence[int] | np.ndarray,
    timestamps: np.ndarray,
    *,
    calibration_fraction: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Reserve the latest training rows for fold-local calibration."""
    indices = np.asarray(train_indices, dtype=np.intp)
    if calibration_fraction <= 0.0 or indices.size < 3:
        return indices, np.empty(0, dtype=np.intp)
    # lexsort sorts by the last key first: time, then index for deterministic ties.
    ordered = indices[np.lexsort((indices, timestamps[indices]))]
    calibration_size = max(2, int(round(ordered.size * calibration_fraction)))
    calibration_size = min(calibration_size, ordered.size - 1)
    split_at = ordered.size - calibration_size
    return ordered[:split_at], ordered[split_at:]


def fit_isotonic_calibrator(
    raw_probabilities: np.ndarray,
    labels: np.ndarray,
) -> Any | None:
    """Fit an isotonic calibrator when the calibration slice has both classes."""
    if len(raw_probabilities) < 2 or len(set(labels.astype(int).tolist())) < 2:
        return None
    calibrator = IsotonicRegression(
        y_min=0.0,
        y_max=1.0,
        out_of_bounds="clip",
    )
    calibrator.fit(raw_probabilities.astype(float), labels.astype(int))
    return calibrator


def apply_isotonic_calibrator(
    calibrator: Any | None,
    raw_probabilities: np.ndarray,
) -> np.ndarray:
    """Apply isotonic calibration, falling back to raw probabilities."""
    if calibrator is None:
        return raw_probabilities.astype(float)
    calibrated = calibrator.predict(raw_probabilities.astype(float))
    return np.clip(np.asarray(calibrated, dtype=float), 0.0, 1.0)


def write_isotonic_calibrator(
    path: Path,
    calibrator: Any | None,
    *,
    metadata: Mapping[str, Any],
) -> None:
    """Persist a small JSON calibrator artifact for deployment wiring."""
    payload: dict[str, Any] = {
        "method": "isotonic",
        "enabled": calibrator is not None,
        **dict(metadata),
    }
    if calibrator is not None:
        payload["x_thresholds"] = [
            float(value) for value in calibrator.X_thresholds_.tolist()
        ]
        payload["y_thresholds"] = [
            float(value) for value in calibrator.y_thresholds_.tolist()
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def event_ofi_probabilities(frame: pd.DataFrame) -> np.ndarray:
    """Event-level OFI baseline, signed to the maker's adverse-selection side."""
    signed_risk = -(
        frame["maker_side"].astype(float).to_numpy()
        * frame["l2_ofi_10s"].astype(float).to_numpy()
    )
    return 0.5 + 0.5 * np.tanh(signed_risk)


def evaluate_baseline(
    frame: pd.DataFrame,
    *,
    horizon: str,
    n_splits: int,
    purge_ms: float,
    embargo_ms: float,
    decision_threshold: float | None = 0.5,
    decision_thresholds: Sequence[float] | None = None,
    scheme: CvScheme = "walk_forward",
    folds: Sequence[FoldArrays] | None = None,
    prediction_mask: np.ndarray | None = None,
    train_days: int | None = None,
    leakage_safe: bool = False,
) -> dict[str, Any]:
    """Evaluate the deterministic event-level OFI baseline."""
    probabilities = event_ofi_probabilities(frame)
    if prediction_mask is not None:
        probabilities[~prediction_mask] = np.nan
    report = evaluate_markout_predictions(
        frame["ts_ms"].to_numpy(dtype=np.float64),
        frame[f"toxic_{horizon}"].to_numpy(dtype=bool),
        probabilities,
        frame[f"markout_bps_{horizon}"].to_numpy(dtype=np.float64),
        model_name=f"{BASELINE_NAME}_{horizon}",
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=decision_thresholds,
        scheme=scheme,
        folds=folds,
        train_days=train_days,
        leakage_safe=leakage_safe,
    )
    return {
        **report.to_dict(),
        "feature_columns": ["maker_side", "l2_ofi_10s"],
        "description": (
            "Snapshot-derived event OFI over a 10s rolling window, signed to maker side."
        ),
    }


def evaluate_holdout_split(
    holdout_frame: pd.DataFrame,
    *,
    horizon: str,
    train_rows: int,
    model_name: str,
    raw_probabilities: np.ndarray,
    probabilities: np.ndarray,
    candidate_threshold: float,
    baseline_threshold: float,
) -> dict[str, Any]:
    """Evaluate final model predictions on an unseen holdout panel."""
    timestamps = holdout_frame["ts_ms"].to_numpy(dtype=np.float64)
    labels = holdout_frame[f"toxic_{horizon}"].to_numpy(dtype=bool)
    markouts = holdout_frame[f"markout_bps_{horizon}"].to_numpy(dtype=np.float64)
    candidate = evaluate_holdout_predictions(
        timestamps,
        labels,
        probabilities,
        markouts,
        model_name=f"{model_name}_holdout",
        train_rows=train_rows,
        decision_threshold=candidate_threshold,
    )
    raw = evaluate_holdout_predictions(
        timestamps,
        labels,
        raw_probabilities,
        markouts,
        model_name=f"{model_name}_holdout_raw",
        train_rows=train_rows,
        decision_threshold=candidate_threshold,
    )
    baseline_probabilities = event_ofi_probabilities(holdout_frame)
    baseline = evaluate_holdout_predictions(
        timestamps,
        labels,
        baseline_probabilities,
        markouts,
        model_name=f"{BASELINE_NAME}_{horizon}_holdout",
        train_rows=train_rows,
        decision_threshold=baseline_threshold,
    )
    candidate_payload = candidate.to_dict()
    return {
        **candidate_payload,
        "partition_rows": partition_row_counts(holdout_frame),
        "uncalibrated": raw.to_dict(),
        "baselines": {
            BASELINE_NAME: {
                **baseline.to_dict(),
                "feature_columns": ["maker_side", "l2_ofi_10s"],
                "description": (
                    f"Snapshot-derived event OFI over a {horizon} rolling window, "
                    "signed to maker side."
                ),
            },
        },
        "baseline_comparison": {
            BASELINE_NAME: metric_deltas(candidate_payload, baseline.to_dict()),
        },
        "policy": {
            "candidate_decision_threshold": candidate_threshold,
            "baseline_decision_threshold": baseline_threshold,
        },
    }


def metric_deltas(candidate: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, float]:
    """Return candidate minus baseline for headline model metrics."""
    return {
        key: float(candidate[key]) - float(baseline[key])
        for key in ("pr_auc", "brier", "ece", "markout_lift_bps", "quote_rate")
        if key in candidate and key in baseline
    }


def estimate_prediction_latency_p95_ms(
    model: Any,
    frame: pd.DataFrame,
    *,
    sample_size: int = 128,
) -> float:
    """Estimate single-row prediction p95 latency for promotion checks.

    Rows are scored one at a time as a float32 vector, the same path the deployed
    scorer takes for a single fill.
    """
    if frame.empty:
        return float("nan")
    sample = feature_matrix(frame.iloc[: min(sample_size, len(frame))])
    durations_ms: list[float] = []
    for row_idx in range(sample.shape[0]):
        start = time.perf_counter()
        model.predict_proba(sample[row_idx : row_idx + 1])
        durations_ms.append((time.perf_counter() - start) * 1000.0)
    return float(np.percentile(durations_ms, 95))


def main() -> int:
    args = parse_args()
    use_feature_set(args.feature_set)
    coins = parse_symbol_spec(args.coins or args.coin)
    dates = parse_date_spec(args.dates or args.date)
    holdout_dates = (
        parse_date_spec(args.holdout_dates or args.holdout_date)
        if args.holdout_dates or args.holdout_date
        else ()
    )
    holdout_coins = parse_symbol_spec(args.holdout_coins) if args.holdout_coins else coins
    requested_partitions = requested_training_partitions(
        args.lake_root,
        coins=coins,
        dates=dates,
    )
    _existing_partitions, missing_partitions = split_existing_missing_partitions(
        requested_partitions
    )
    partitions = resolve_training_partitions(
        args.lake_root,
        coins=coins,
        dates=dates,
        allow_missing=args.allow_missing_partitions,
    )
    holdout_partitions = (
        resolve_training_partitions(
            args.lake_root,
            coins=holdout_coins,
            dates=holdout_dates,
            allow_missing=False,
        )
        if holdout_dates
        else ()
    )
    label = dataset_label(partitions)
    leakage_safe, leakage_details = partition_leakage_status(partitions + holdout_partitions)
    print(f"Loading {len(partitions)} partition(s): {label}")
    if not leakage_safe:
        print("WARNING: no passing no-look-ahead report for every partition; "
              "the report will say leakage_safe=false")
    if holdout_partitions:
        print(
            f"Loading {len(holdout_partitions)} holdout partition(s): "
            f"{dataset_label(holdout_partitions)}"
        )
    if missing_partitions and args.allow_missing_partitions:
        print(
            f"Skipping {len(missing_partitions)} missing partition(s): "
            f"{', '.join(partition.label for partition in missing_partitions[:8])}"
        )
    frame = load_training_panel(
        partitions,
        horizon=args.horizon,
        max_rows=args.max_rows,
    )
    print(
        f"Rows={len(frame):,} toxic_rate={frame[f'toxic_{args.horizon}'].mean():.3f} "
        f"window={int(frame['ts_ms'].min())}->{int(frame['ts_ms'].max())}"
    )

    # Overlap the holdout read with CatBoost fitting (both release the GIL).
    prefetch = ThreadPoolExecutor(max_workers=1)
    holdout_future = (
        prefetch.submit(
            load_training_panel,
            holdout_partitions,
            horizon=args.horizon,
            max_rows=args.max_rows,
        )
        if holdout_partitions
        else None
    )
    prefetch.shutdown(wait=False)
    start = time.perf_counter()
    calibration_fraction = 0.0 if args.disable_calibration else args.calibration_fraction
    training_result = train_oof_catboost(
        frame,
        horizon=args.horizon,
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        iterations=args.iterations,
        learning_rate=args.learning_rate,
        depth=args.depth,
        seed=args.seed,
        calibration_fraction=calibration_fraction,
        scheme=args.cv_scheme,
        train_days=args.train_days,
    )
    elapsed_s = time.perf_counter() - start
    probabilities = training_result.probabilities
    raw_probabilities = training_result.raw_probabilities
    model = training_result.model
    valid = ~np.isnan(probabilities)
    eval_frame = frame.loc[valid].reset_index(drop=True)
    # Keep the training row order and fold assignments, including unscored blocks.
    eval_timestamps = frame["ts_ms"].to_numpy(dtype=np.float64)
    eval_labels = frame[f"toxic_{args.horizon}"].to_numpy(dtype=bool)
    eval_markouts = frame[f"markout_bps_{args.horizon}"].to_numpy(dtype=np.float64)
    eval_probabilities = probabilities
    folds = training_result.folds
    threshold_grid = parse_threshold_grid(args.threshold_grid)
    if args.decision_threshold is None:
        decision_threshold = None
        candidate_thresholds, candidate_threshold_folds = fold_local_markout_thresholds(
            eval_timestamps,
            eval_probabilities,
            eval_markouts,
            n_splits=args.n_splits,
            purge_ms=args.purge_ms,
            embargo_ms=args.embargo_ms,
            threshold_grid=threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
            scheme=args.cv_scheme,
            folds=folds,
            train_days=args.train_days,
        )
        candidate_deployment_selection = select_markout_threshold(
            eval_probabilities[valid],
            eval_markouts[valid],
            threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
        )
    else:
        decision_threshold = args.decision_threshold
        candidate_thresholds = None
        candidate_threshold_folds = ()
        candidate_deployment_selection = select_markout_threshold(
            eval_probabilities[valid],
            eval_markouts[valid],
            (decision_threshold,),
            min_quote_rate=0.0,
            max_quote_rate=1.0,
        )
    baseline_probabilities = event_ofi_probabilities(frame)
    baseline_probabilities[~valid] = np.nan
    if args.decision_threshold is None:
        baseline_thresholds, baseline_threshold_folds = fold_local_markout_thresholds(
            eval_timestamps,
            baseline_probabilities,
            eval_markouts,
            n_splits=args.n_splits,
            purge_ms=args.purge_ms,
            embargo_ms=args.embargo_ms,
            threshold_grid=threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
            scheme=args.cv_scheme,
            folds=folds,
            train_days=args.train_days,
        )
        baseline_deployment_selection = select_markout_threshold(
            baseline_probabilities[valid],
            eval_markouts[valid],
            threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
        )
    else:
        baseline_thresholds = None
        baseline_threshold_folds = ()
        baseline_deployment_selection = select_markout_threshold(
            baseline_probabilities[valid],
            eval_markouts[valid],
            (decision_threshold,),
            min_quote_rate=0.0,
            max_quote_rate=1.0,
        )
    report = evaluate_markout_predictions(
        eval_timestamps,
        eval_labels,
        eval_probabilities,
        eval_markouts,
        model_name=f"catboost_markout_{label}_{args.horizon}",
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=candidate_thresholds,
        scheme=args.cv_scheme,
        folds=folds,
        train_days=args.train_days,
        leakage_safe=leakage_safe,
    )
    raw_report = evaluate_markout_predictions(
        eval_timestamps,
        eval_labels,
        raw_probabilities,
        eval_markouts,
        model_name=f"catboost_markout_{label}_{args.horizon}_raw",
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=candidate_thresholds,
        scheme=args.cv_scheme,
        folds=folds,
        train_days=args.train_days,
        leakage_safe=leakage_safe,
    )
    baseline_report = evaluate_baseline(
        frame,
        horizon=args.horizon,
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=baseline_thresholds,
        scheme=args.cv_scheme,
        folds=folds,
        prediction_mask=valid,
        train_days=args.train_days,
        leakage_safe=leakage_safe,
    )
    holdout_payload = None
    if holdout_future is not None:
        holdout_frame = holdout_future.result()
        holdout_raw = model.predict_proba(feature_matrix(holdout_frame))[:, 1]
        holdout_probabilities = apply_isotonic_calibrator(
            training_result.calibrator if not args.disable_calibration else None,
            holdout_raw,
        )
        holdout_payload = {
            **evaluate_holdout_split(
                holdout_frame,
                horizon=args.horizon,
                train_rows=len(frame),
                model_name=f"catboost_markout_{label}_{args.horizon}",
                raw_probabilities=holdout_raw,
                probabilities=holdout_probabilities,
                candidate_threshold=candidate_deployment_selection.threshold,
                baseline_threshold=baseline_deployment_selection.threshold,
            ),
            "coins": list(holdout_coins),
            "dates": list(holdout_dates),
            "dataset_label": dataset_label(holdout_partitions),
            "partitions": [
                {
                    "coin": partition.coin,
                    "date": partition.date,
                    "path": str(partition.path),
                }
                for partition in holdout_partitions
            ],
        }
    latency_p95_ms = estimate_prediction_latency_p95_ms(model, frame)
    calibrator_out = args.calibrator_out or args.model_out.with_suffix(".isotonic.json")

    report_payload = report.to_dict()
    payload = {
        **report_payload,
        "latency_p95_ms": latency_p95_ms,
        "baselines": {
            BASELINE_NAME: baseline_report,
        },
        "baseline_comparison": {
            BASELINE_NAME: metric_deltas(report_payload, baseline_report),
        },
        "coin": coins[0] if len(coins) == 1 else ",".join(coins),
        "date": dates[0] if len(dates) == 1 else ",".join(dates),
        "coins": list(coins),
        "dates": list(dates),
        "dataset_label": label,
        "partitions": [
            {
                "coin": partition.coin,
                "date": partition.date,
                "path": str(partition.path),
            }
            for partition in partitions
        ],
        "requested_partitions": [
            {
                "coin": partition.coin,
                "date": partition.date,
                "path": str(partition.path),
                "exists": partition.path.exists(),
            }
            for partition in requested_partitions
        ],
        "missing_partitions": [
            {
                "coin": partition.coin,
                "date": partition.date,
                "path": str(partition.path),
            }
            for partition in missing_partitions
        ],
        "partition_rows": partition_row_counts(eval_frame),
        "horizon": args.horizon,
        "cv_scheme": args.cv_scheme,
        "train_days": args.train_days if args.cv_scheme == "rolling_daily" else None,
        "feature_set": args.feature_set,
        "leakage_check": leakage_details,
        "training_rows": len(frame),
        "oof_rows": int(valid.sum()),
        "feature_columns": FEATURE_COLUMNS,
        "fold_training": training_result.fold_summaries,
        "fit_elapsed_s": elapsed_s,
        "uncalibrated": raw_report.to_dict(),
        "policy": {
            "threshold_mode": (
                "auto_fold_local" if args.decision_threshold is None else "fixed"
            ),
            "decision_threshold": decision_threshold,
            "deployment_decision_threshold": candidate_deployment_selection.threshold,
            "threshold_grid": list(threshold_grid),
            "min_quote_rate": args.min_quote_rate,
            "max_quote_rate": args.max_quote_rate,
            "candidate_threshold_folds": list(candidate_threshold_folds),
            "candidate_deployment_selection": candidate_deployment_selection.to_dict(),
            "baseline_threshold_folds": list(baseline_threshold_folds),
            "baseline_deployment_selection": baseline_deployment_selection.to_dict(),
        },
        "calibration": {
            "method": "isotonic",
            "enabled": not args.disable_calibration,
            "calibration_fraction": calibration_fraction,
            "calibrator_artifact": str(calibrator_out),
            "brier_delta": report.brier - raw_report.brier,
            "ece_delta": report.ece - raw_report.ece,
        },
        "catboost": {
            "iterations": args.iterations,
            "learning_rate": args.learning_rate,
            "depth": args.depth,
            "seed": args.seed,
        },
    }
    if holdout_payload is not None:
        payload["holdout_split"] = holdout_payload
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(args.model_out))
    write_isotonic_calibrator(
        calibrator_out,
        training_result.calibrator if not args.disable_calibration else None,
        metadata={
            "coin": coins[0] if len(coins) == 1 else ",".join(coins),
            "date": dates[0] if len(dates) == 1 else ",".join(dates),
            "coins": list(coins),
            "dates": list(dates),
            "dataset_label": label,
            "horizon": args.horizon,
            "source": "out_of_fold_raw_probabilities",
            "policy_threshold_mode": payload["policy"]["threshold_mode"],
            "deployment_decision_threshold": payload["policy"][
                "deployment_decision_threshold"
            ],
            "feature_columns": FEATURE_COLUMNS,
            "training_rows": len(frame),
            "oof_rows": int(valid.sum()),
        },
    )
    baseline_delta_bps = payload["baseline_comparison"][BASELINE_NAME]["markout_lift_bps"]
    calibration_brier_delta = payload["calibration"]["brier_delta"]
    print(
        f"PR-AUC={report.pr_auc:.3f} Brier={report.brier:.3f} "
        f"markout_lift_bps={report.markout_lift_bps:.3f} "
        f"quote_rate={report.quote_rate:.3f} "
        f"threshold={payload['policy']['deployment_decision_threshold']:.3f} "
        f"latency_p95_ms={latency_p95_ms:.3f} "
        f"baseline_delta_bps={baseline_delta_bps:.3f} "
        f"calibration_brier_delta={calibration_brier_delta:.3f}"
    )
    if holdout_payload is not None:
        holdout_delta = holdout_payload["baseline_comparison"][BASELINE_NAME][
            "markout_lift_bps"
        ]
        print(
            f"Holdout PR-AUC={holdout_payload['pr_auc']:.3f} "
            f"markout_lift_bps={holdout_payload['markout_lift_bps']:.3f} "
            f"baseline_delta_bps={holdout_delta:.3f}"
        )
    print(f"Wrote report {args.report}")
    print(f"Wrote model {args.model_out}")
    print(f"Wrote calibrator {calibrator_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
