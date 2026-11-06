"""Health of the promoted markout model: artifacts, report metrics and a smoke prediction."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.conf import settings

from marketimmune.serving.scorer import HyperliquidMarkoutScorer

METRIC_KEYS = (
    "n_rows",
    "training_rows",
    "pr_auc",
    "brier",
    "ece",
    "markout_lift_bps",
    "quote_rate",
    "latency_p95_ms",
    "leakage_safe",
    "partition_rows",
    "coins",
    "dates",
)


def configured_path(name: str) -> Path:
    """A path setting, relative to the repository root unless absolute."""
    return Path(settings.BASE_DIR) / getattr(settings, name)


def display_path(path: Path) -> str:
    """Repository-relative when under the repository, else absolute."""
    return str(path.relative_to(settings.BASE_DIR)) if path.is_relative_to(settings.BASE_DIR) else str(path)


def promoted_artifacts() -> dict[str, Path]:
    return {
        "model": configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH"),
        "calibrator": configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH"),
        "report": configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH"),
    }


def promoted_markout_model_health(*, samples: int = 128) -> dict[str, Any]:
    """Artifact status; when all exist, the report's metrics plus a zero-feature smoke prediction and its latency."""
    paths = promoted_artifacts()
    artifacts = {label: {"label": label, "path": display_path(path), "exists": path.exists()} for label, path in paths.items()}
    missing = [status for status in artifacts.values() if not status["exists"]]
    if missing:
        return {
            "available": False,
            "kind": "hyperliquid_markout",
            "message": "Promoted markout artifacts are not complete yet.",
            "artifacts": artifacts,
            "missing_artifacts": missing,
        }
    try:
        scorer = HyperliquidMarkoutScorer.load(paths["model"], paths["calibrator"], paths["report"])
    except ValueError as exc:  # artifacts that do not belong together, or no deployable policy
        return {"available": False, "kind": "hyperliquid_markout", "message": str(exc), "artifacts": artifacts, "missing_artifacts": []}
    smoke_features = scorer.zero_feature_sample()
    report = scorer.report
    holdout = report["holdout_split"]
    return {
        "available": True,
        "kind": "hyperliquid_markout",
        "model_name": scorer.model_name,
        "instrument": "-".join(report["coins"]),
        "horizon": report["horizon"],
        "dataset_label": report["dataset_label"],
        # NOTE: the promoted report predates the cv_scheme field; it was fit with purged k-fold.
        "cv_scheme": report.get("cv_scheme", "purged_kfold"),
        "decision_threshold": scorer.decision_threshold,
        "feature_count": len(scorer.feature_columns),
        "feature_columns": list(scorer.feature_columns),
        "artifacts": artifacts,
        "training": _metric_block(report),
        "holdout": _metric_block(holdout),
        "baseline_comparison": report.get("baseline_comparison"),
        "holdout_baseline_comparison": holdout.get("baseline_comparison"),
        "smoke_prediction": scorer.predict(smoke_features).as_dict(),
        "smoke_latency": scorer.latency_ms(smoke_features, samples=samples),
    }


def _metric_block(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: report[key] for key in METRIC_KEYS if key in report}
