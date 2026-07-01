"""Dashboard-facing health summary for promoted Hyperliquid markout artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from django.conf import settings

from marketimmune.models import HyperliquidMarkoutScorer, MarkoutScorerError

ScorerLoader = Callable[[Path, Path, Path], HyperliquidMarkoutScorer]


def promoted_markout_model_health(
    *,
    samples: int = 128,
    loader: ScorerLoader = HyperliquidMarkoutScorer.load,
) -> dict[str, Any]:
    """Return an app-ready status payload for the promoted markout model."""
    model_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH")
    calibrator_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH")
    report_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH")
    missing = [
        _artifact_status("model", model_path),
        _artifact_status("calibrator", calibrator_path),
        _artifact_status("report", report_path),
    ]
    missing = [item for item in missing if not item["exists"]]
    if missing:
        return {
            "available": False,
            "kind": "hyperliquid_markout",
            "message": "Promoted markout artifacts are not complete yet.",
            "artifacts": _artifact_payload(model_path, calibrator_path, report_path),
            "missing_artifacts": missing,
        }

    try:
        scorer = loader(model_path, calibrator_path, report_path)
        smoke_features = scorer.zero_feature_sample()
        smoke_prediction = scorer.predict(smoke_features)
        latency = scorer.latency_ms(smoke_features, samples=samples)
    except (ImportError, FileNotFoundError, MarkoutScorerError, ValueError) as exc:
        return {
            "available": False,
            "kind": "hyperliquid_markout",
            "message": str(exc),
            "artifacts": _artifact_payload(model_path, calibrator_path, report_path),
            "missing_artifacts": [],
        }

    report = scorer.report
    holdout_value = report.get("holdout_split")
    holdout = holdout_value if isinstance(holdout_value, Mapping) else {}
    baseline = report.get("baseline_comparison")
    holdout_baseline = holdout.get("baseline_comparison") if isinstance(holdout, Mapping) else None
    return {
        "available": True,
        "kind": "hyperliquid_markout",
        "model_name": scorer.model_name,
        "instrument": _instrument_label(report),
        "horizon": report.get("horizon"),
        "dataset_label": report.get("dataset_label"),
        "decision_threshold": scorer.decision_threshold,
        "feature_count": len(scorer.feature_columns),
        "feature_columns": list(scorer.feature_columns),
        "artifacts": _artifact_payload(model_path, calibrator_path, report_path),
        "training": _metric_block(report),
        "holdout": _metric_block(holdout) if isinstance(holdout, Mapping) else None,
        "baseline_comparison": baseline,
        "holdout_baseline_comparison": holdout_baseline,
        "smoke_prediction": smoke_prediction.as_dict(),
        "smoke_latency": latency,
    }


def _configured_path(name: str) -> Path:
    raw = str(getattr(settings, name))
    path = Path(raw)
    return path if path.is_absolute() else Path(settings.BASE_DIR) / path


def _artifact_status(label: str, path: Path) -> dict[str, Any]:
    return {"label": label, "path": _display_path(path), "exists": path.exists()}


def _artifact_payload(model_path: Path, calibrator_path: Path, report_path: Path) -> dict[str, Any]:
    return {
        "model": _artifact_status("model", model_path),
        "calibrator": _artifact_status("calibrator", calibrator_path),
        "report": _artifact_status("report", report_path),
    }


def _metric_block(report: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "n_rows",
        "training_rows",
        "pr_auc",
        "brier",
        "ece",
        "markout_lift_bps",
        "quote_rate",
        "latency_p95_ms",
        "leakage_safe",
    )
    block = {key: report.get(key) for key in keys if key in report}
    if "partition_rows" in report:
        block["partition_rows"] = report.get("partition_rows")
    if "coins" in report:
        block["coins"] = report.get("coins")
    if "dates" in report:
        block["dates"] = report.get("dates")
    return block


def _instrument_label(report: Mapping[str, Any]) -> str:
    coins = report.get("coins")
    if isinstance(coins, list) and coins:
        return "-".join(str(item) for item in coins)
    coin = report.get("coin")
    return str(coin) if coin else "Hyperliquid"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(settings.BASE_DIR).resolve()))
    except ValueError:
        return str(path)
