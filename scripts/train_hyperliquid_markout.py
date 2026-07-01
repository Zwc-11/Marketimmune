"""Train a CatBoost toxicity model on Hyperliquid Gold training rows."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

from marketimmune.features.hyperliquid_features import (
    HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    HYPERLIQUID_OFI_COLUMNS,
)
from marketimmune.models.markout_evaluation import (
    evaluate_holdout_predictions,
    evaluate_markout_predictions,
    fold_local_markout_thresholds,
    select_markout_threshold,
)
from marketimmune.models.walk_forward import purged_walk_forward_splits
from scripts.hyperliquid_markout_args import parse_args

FEATURE_COLUMNS = list(HYPERLIQUID_MARKOUT_FEATURE_COLUMNS)
OFI_COLUMNS = HYPERLIQUID_OFI_COLUMNS
BASELINE_NAME = "event_ofi"


@dataclass(frozen=True, slots=True)
class CatBoostTrainingResult:
    """Out-of-fold CatBoost predictions plus deployable artifacts."""

    probabilities: np.ndarray
    raw_probabilities: np.ndarray
    fold_summaries: list[dict[str, Any]]
    model: Any
    calibrator: Any | None


@dataclass(frozen=True, slots=True)
class TrainingPartition:
    """One local Gold training parquet partition."""

    coin: str
    date: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.coin}:{self.date}"


def training_path(lake_root: Path, coin: str, date: str) -> Path:
    symbol = coin.strip().upper().replace("/", "-")
    return (
        lake_root
        / "gold"
        / "hyperliquid"
        / "training"
        / symbol
        / f"{symbol}-training-{date}.parquet"
    )


def parse_symbol_spec(value: str) -> tuple[str, ...]:
    symbols = tuple(_normalize_symbol(item) for item in _split_csv(value))
    if not symbols:
        raise ValueError("at least one coin is required")
    return tuple(dict.fromkeys(symbols))


def parse_date_spec(value: str) -> tuple[str, ...]:
    dates: list[str] = []
    for token in _split_csv(value):
        if ".." in token:
            dates.extend(_expand_date_range(token))
        else:
            dates.append(_validate_date(token))
    if not dates:
        raise ValueError("at least one date is required")
    return tuple(dict.fromkeys(dates))


def parse_threshold_grid(value: str) -> tuple[float, ...]:
    """Parse a comma list or inclusive start:end:step threshold range."""
    token = value.strip()
    if not token:
        raise ValueError("threshold grid cannot be empty")
    if ":" in token and "," not in token:
        parts = token.split(":")
        if len(parts) != 3:
            raise ValueError("threshold range must use start:end:step")
        start, end, step = (float(part) for part in parts)
        if step <= 0.0:
            raise ValueError("threshold step must be positive")
        values: list[float] = []
        current = start
        while current <= end + (step / 2.0):
            values.append(round(current, 10))
            current += step
    else:
        values = [float(item) for item in _split_csv(token)]
    if not values:
        raise ValueError("threshold grid cannot be empty")
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("threshold grid values must be in [0, 1]")
    return tuple(dict.fromkeys(values))


def resolve_training_partitions(
    lake_root: Path,
    *,
    coins: tuple[str, ...],
    dates: tuple[str, ...],
    allow_missing: bool = False,
) -> tuple[TrainingPartition, ...]:
    partitions = requested_training_partitions(lake_root, coins=coins, dates=dates)
    existing, missing = split_existing_missing_partitions(partitions)
    if missing and not allow_missing:
        available = ", ".join(partition.label for partition in existing) or "(none)"
        missing_labels = ", ".join(partition.label for partition in missing[:8])
        if len(missing) > 8:
            missing_labels += f", ... (+{len(missing) - 8} more)"
        message = (
            f"missing {len(missing)} local Hyperliquid training partition(s): "
            f"{missing_labels}. Available requested partitions: {available}. "
            "Backfill the missing dates first, or pass --allow-missing-partitions "
            "to train only on files already present."
        )
        raise FileNotFoundError(message)
    if not existing:
        raise FileNotFoundError("no requested Hyperliquid training partitions exist locally")
    return existing


def requested_training_partitions(
    lake_root: Path,
    *,
    coins: tuple[str, ...],
    dates: tuple[str, ...],
) -> tuple[TrainingPartition, ...]:
    return tuple(
        TrainingPartition(
            coin=coin,
            date=date,
            path=training_path(lake_root, coin, date),
        )
        for coin in coins
        for date in dates
    )


def split_existing_missing_partitions(
    partitions: tuple[TrainingPartition, ...],
) -> tuple[tuple[TrainingPartition, ...], tuple[TrainingPartition, ...]]:
    existing = tuple(partition for partition in partitions if partition.path.exists())
    missing = tuple(partition for partition in partitions if not partition.path.exists())
    return existing, missing


def dataset_label(partitions: tuple[TrainingPartition, ...]) -> str:
    coins = "-".join(dict.fromkeys(partition.coin for partition in partitions))
    dates = "-".join(dict.fromkeys(partition.date for partition in partitions))
    return f"{coins}_{dates}"


def load_training_frame(path: Path, *, horizon: str, max_rows: int = 0) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    label_col = f"toxic_{horizon}"
    markout_col = f"markout_bps_{horizon}"
    requested_columns = [
        "ts_ms",
        "px",
        "sz",
        "maker_side",
        "fee_bps",
        label_col,
        markout_col,
        "l2_mid",
        "l2_spread_bps",
        "l2_microprice",
        "l2_top_imbalance",
        *OFI_COLUMNS,
        "asset_basis_bps",
        "asset_funding",
        "asset_open_interest",
        "asset_premium",
    ]
    available_columns = set(pq.read_schema(path).names)
    columns = [column for column in requested_columns if column in available_columns]
    frame = pq.read_table(path, columns=columns).to_pandas()
    if max_rows > 0 and len(frame) > max_rows:
        frame = frame.sort_values("ts_ms").iloc[:max_rows].copy()
    return prepare_training_frame(frame, horizon=horizon)


def load_training_panel(
    partitions: tuple[TrainingPartition, ...],
    *,
    horizon: str,
    max_rows: int = 0,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for partition in partitions:
        frame = load_training_frame(partition.path, horizon=horizon, max_rows=0)
        frame["partition_coin"] = partition.coin
        frame["partition_date"] = partition.date
        frame["partition_path"] = str(partition.path)
        frames.append(frame)
    if not frames:
        raise ValueError("no training partitions were provided")
    panel = pd.concat(frames, ignore_index=True).sort_values("ts_ms").reset_index(drop=True)
    if max_rows > 0 and len(panel) > max_rows:
        panel = panel.iloc[:max_rows].copy()
    return panel


def partition_row_counts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "partition_coin" not in frame.columns or "partition_date" not in frame.columns:
        return []
    counts = (
        frame.groupby(["partition_coin", "partition_date"], sort=True)
        .size()
        .reset_index(name="rows")
    )
    return [
        {
            "coin": str(row.partition_coin),
            "date": str(row.partition_date),
            "rows": int(row.rows),
        }
        for row in counts.itertuples(index=False)
    ]


def prepare_training_frame(frame: pd.DataFrame, *, horizon: str) -> pd.DataFrame:
    label_col = f"toxic_{horizon}"
    markout_col = f"markout_bps_{horizon}"
    frame = frame.copy()
    if "fee_bps" not in frame.columns:
        frame["fee_bps"] = 0.0
    else:
        frame["fee_bps"] = frame["fee_bps"].fillna(0.0)
    for column in OFI_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0
        else:
            frame[column] = frame[column].fillna(0.0)
    frame["l2_microprice_offset_bps"] = (
        (frame["l2_microprice"] - frame["l2_mid"]) / frame["l2_mid"] * 10_000.0
    )
    frame["fill_vs_mid_bps"] = (
        (frame["px"] - frame["l2_mid"]) / frame["l2_mid"] * 10_000.0 * frame["maker_side"]
    )
    needed = ["ts_ms", label_col, markout_col, *FEATURE_COLUMNS]
    numeric_needed = ["ts_ms", markout_col, *FEATURE_COLUMNS]
    frame[numeric_needed] = frame[numeric_needed].apply(pd.to_numeric, errors="coerce")
    frame[numeric_needed] = frame[numeric_needed].where(
        np.isfinite(frame[numeric_needed]),
        np.nan,
    )
    frame = frame.dropna(subset=needed)
    frame[label_col] = frame[label_col].astype(bool)
    return frame.sort_values("ts_ms").reset_index(drop=True)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace("/", "-")


def _validate_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid YYYYMMDD date: {value}") from exc
    return value


def _expand_date_range(value: str) -> list[str]:
    start_text, end_text = value.split("..", 1)
    start = datetime.strptime(_validate_date(start_text), "%Y%m%d").date()
    end = datetime.strptime(_validate_date(end_text), "%Y%m%d").date()
    if end < start:
        raise ValueError("date range end must be >= start")
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


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
) -> CatBoostTrainingResult:
    try:
        from catboost import CatBoostClassifier
    except ImportError as exc:  # pragma: no cover - environment boundary.
        raise RuntimeError("Install CatBoost first: python -m pip install catboost") from exc

    if calibration_fraction < 0.0 or calibration_fraction >= 1.0:
        raise ValueError("calibration_fraction must be in [0, 1)")

    timestamps = frame["ts_ms"].astype(float).to_numpy()
    y = frame[f"toxic_{horizon}"].astype(int).to_numpy()
    x = frame[FEATURE_COLUMNS]
    probabilities = np.full(len(frame), np.nan, dtype=float)
    raw_probabilities = np.full(len(frame), np.nan, dtype=float)
    fold_summaries: list[dict[str, Any]] = []

    for fold_id, fold in enumerate(
        purged_walk_forward_splits(
            timestamps,
            n_splits=n_splits,
            purge_ms=purge_ms,
            embargo_ms=embargo_ms,
        ),
        start=1,
    ):
        model_indices, calibration_indices = split_model_calibration_indices(
            fold.train_indices,
            timestamps,
            calibration_fraction=calibration_fraction,
        )
        model = CatBoostClassifier(
            iterations=iterations,
            learning_rate=learning_rate,
            depth=depth,
            loss_function="Logloss",
            eval_metric="PRAUC",
            random_seed=seed + fold_id,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(x.iloc[model_indices], y[model_indices])
        test_raw = model.predict_proba(
            x.iloc[list(fold.test_indices)]
        )[:, 1]
        raw_probabilities[list(fold.test_indices)] = test_raw
        calibrator = None
        if calibration_indices:
            calibration_raw = model.predict_proba(x.iloc[calibration_indices])[:, 1]
            calibrator = fit_isotonic_calibrator(
                calibration_raw,
                y[calibration_indices],
            )
        probabilities[list(fold.test_indices)] = apply_isotonic_calibrator(
            calibrator,
            test_raw,
        )
        fold_summaries.append({
            "fold_id": fold_id,
            "n_train": len(fold.train_indices),
            "n_model_train": len(model_indices),
            "n_calibration": len(calibration_indices),
            "n_test": len(fold.test_indices),
            "calibrated": calibrator is not None,
        })

    valid_raw = ~np.isnan(raw_probabilities)
    if not np.any(valid_raw):
        raise ValueError("no model was trained")
    final_model = CatBoostClassifier(
        iterations=iterations,
        learning_rate=learning_rate,
        depth=depth,
        loss_function="Logloss",
        eval_metric="PRAUC",
        random_seed=seed,
        verbose=False,
        allow_writing_files=False,
    )
    final_model.fit(x, y)
    final_calibrator = fit_isotonic_calibrator(raw_probabilities[valid_raw], y[valid_raw])
    return CatBoostTrainingResult(
        probabilities=probabilities,
        raw_probabilities=raw_probabilities,
        fold_summaries=fold_summaries,
        model=final_model,
        calibrator=final_calibrator,
    )


def split_model_calibration_indices(
    train_indices: tuple[int, ...],
    timestamps: np.ndarray,
    *,
    calibration_fraction: float,
) -> tuple[list[int], list[int]]:
    """Reserve the latest training rows for fold-local calibration."""
    if calibration_fraction <= 0.0 or len(train_indices) < 3:
        return list(train_indices), []
    ordered = sorted(train_indices, key=lambda idx: (float(timestamps[idx]), idx))
    calibration_size = max(2, int(round(len(ordered) * calibration_fraction)))
    calibration_size = min(calibration_size, len(ordered) - 1)
    split_at = len(ordered) - calibration_size
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
    decision_thresholds: tuple[float, ...] | None = None,
) -> dict[str, Any]:
    """Evaluate the deterministic event-level OFI baseline."""
    probabilities = event_ofi_probabilities(frame)
    report = evaluate_markout_predictions(
        frame["ts_ms"].astype(float).tolist(),
        frame[f"toxic_{horizon}"].astype(bool).tolist(),
        probabilities.tolist(),
        frame[f"markout_bps_{horizon}"].astype(float).tolist(),
        model_name=f"{BASELINE_NAME}_{horizon}",
        n_splits=n_splits,
        purge_ms=purge_ms,
        embargo_ms=embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=decision_thresholds,
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
    timestamps = holdout_frame["ts_ms"].astype(float).tolist()
    labels = holdout_frame[f"toxic_{horizon}"].astype(bool).tolist()
    markouts = holdout_frame[f"markout_bps_{horizon}"].astype(float).tolist()
    candidate = evaluate_holdout_predictions(
        timestamps,
        labels,
        probabilities.astype(float).tolist(),
        markouts,
        model_name=f"{model_name}_holdout",
        train_rows=train_rows,
        decision_threshold=candidate_threshold,
    )
    raw = evaluate_holdout_predictions(
        timestamps,
        labels,
        raw_probabilities.astype(float).tolist(),
        markouts,
        model_name=f"{model_name}_holdout_raw",
        train_rows=train_rows,
        decision_threshold=candidate_threshold,
    )
    baseline_probabilities = event_ofi_probabilities(holdout_frame)
    baseline = evaluate_holdout_predictions(
        timestamps,
        labels,
        baseline_probabilities.astype(float).tolist(),
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
    """Estimate single-row prediction p95 latency for promotion checks."""
    if frame.empty:
        return float("nan")
    sample = frame[FEATURE_COLUMNS].iloc[: min(sample_size, len(frame))]
    durations_ms: list[float] = []
    for row_idx in range(len(sample)):
        start = time.perf_counter()
        model.predict_proba(sample.iloc[[row_idx]])
        durations_ms.append((time.perf_counter() - start) * 1000.0)
    return float(np.percentile(durations_ms, 95))


def main() -> int:
    args = parse_args()
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
    print(f"Loading {len(partitions)} partition(s): {label}")
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
    )
    elapsed_s = time.perf_counter() - start
    probabilities = training_result.probabilities
    raw_probabilities = training_result.raw_probabilities
    model = training_result.model
    valid = ~np.isnan(probabilities)
    eval_frame = frame.loc[valid].reset_index(drop=True)
    eval_timestamps = eval_frame["ts_ms"].astype(float).tolist()
    eval_labels = eval_frame[f"toxic_{args.horizon}"].astype(bool).tolist()
    eval_markouts = eval_frame[f"markout_bps_{args.horizon}"].astype(float).tolist()
    eval_probabilities = probabilities[valid].tolist()
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
        )
        candidate_deployment_selection = select_markout_threshold(
            eval_probabilities,
            eval_markouts,
            threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
        )
    else:
        decision_threshold = args.decision_threshold
        candidate_thresholds = None
        candidate_threshold_folds = ()
        candidate_deployment_selection = select_markout_threshold(
            eval_probabilities,
            eval_markouts,
            (decision_threshold,),
            min_quote_rate=0.0,
            max_quote_rate=1.0,
        )
    baseline_probabilities = event_ofi_probabilities(eval_frame).tolist()
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
        )
        baseline_deployment_selection = select_markout_threshold(
            baseline_probabilities,
            eval_markouts,
            threshold_grid,
            min_quote_rate=args.min_quote_rate,
            max_quote_rate=args.max_quote_rate,
        )
    else:
        baseline_thresholds = None
        baseline_threshold_folds = ()
        baseline_deployment_selection = select_markout_threshold(
            baseline_probabilities,
            eval_markouts,
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
    )
    raw_report = evaluate_markout_predictions(
        eval_timestamps,
        eval_labels,
        raw_probabilities[valid].tolist(),
        eval_markouts,
        model_name=f"catboost_markout_{label}_{args.horizon}_raw",
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=candidate_thresholds,
    )
    baseline_report = evaluate_baseline(
        eval_frame,
        horizon=args.horizon,
        n_splits=args.n_splits,
        purge_ms=args.purge_ms,
        embargo_ms=args.embargo_ms,
        decision_threshold=decision_threshold,
        decision_thresholds=baseline_thresholds,
    )
    holdout_payload = None
    if holdout_partitions:
        holdout_frame = load_training_panel(
            holdout_partitions,
            horizon=args.horizon,
            max_rows=args.max_rows,
        )
        holdout_raw = model.predict_proba(holdout_frame[FEATURE_COLUMNS])[:, 1]
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
