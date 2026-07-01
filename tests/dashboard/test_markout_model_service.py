"""Tests for promoted markout model dashboard health payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dashboard.services import markout_model_service


class FakeSettings:
    def __init__(self, base_dir: Path, model: Path, calibrator: Path, report: Path) -> None:
        self.BASE_DIR = base_dir
        self.MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH = str(model)
        self.MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH = str(calibrator)
        self.MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH = str(report)


class FakePrediction:
    def as_dict(self) -> dict[str, float | str]:
        return {"raw_score": 0.42, "calibrated_score": 0.39, "action": "quote"}


class FakeScorer:
    def __init__(self) -> None:
        self.model_name = "catboost_markout_SOL_10s"
        self.feature_columns = ("maker_side", "l2_ofi_10s")
        self.decision_threshold = 0.3
        self.report = {
            "model_name": self.model_name,
            "dataset_label": "SOL_20260527-20260531",
            "horizon": "10s",
            "coins": ["SOL"],
            "training_rows": 100,
            "pr_auc": 0.55,
            "brier": 0.22,
            "holdout_split": {
                "n_rows": 20,
                "pr_auc": 0.56,
                "brier": 0.23,
                "markout_lift_bps": 0.86,
                "baseline_comparison": {
                    "event_ofi": {"markout_lift_bps": 0.11},
                },
            },
        }

    def zero_feature_sample(self) -> dict[str, float]:
        return {"maker_side": 0.0, "l2_ofi_10s": 0.0}

    def predict(self, features: dict[str, float]) -> FakePrediction:
        assert features == self.zero_feature_sample()
        return FakePrediction()

    def latency_ms(self, features: dict[str, float], *, samples: int) -> dict[str, float]:
        assert features == self.zero_feature_sample()
        assert samples == 3
        return {"p50_ms": 0.1, "p95_ms": 0.2, "p99_ms": 0.3, "mean_ms": 0.15}


def test_promoted_markout_model_health_reports_loaded_artifact(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    model = tmp_path / "model.cbm"
    calibrator = tmp_path / "model.isotonic.json"
    report = tmp_path / "report.json"
    for path in (model, calibrator, report):
        path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        markout_model_service,
        "settings",
        FakeSettings(tmp_path, model, calibrator, report),
    )

    payload = markout_model_service.promoted_markout_model_health(
        samples=3,
        loader=lambda _model, _calibrator, _report: FakeScorer(),
    )

    assert payload["available"] is True
    assert payload["model_name"] == "catboost_markout_SOL_10s"
    assert payload["instrument"] == "SOL"
    assert payload["feature_count"] == 2
    assert payload["training"]["pr_auc"] == 0.55
    assert payload["holdout"]["markout_lift_bps"] == 0.86
    assert payload["holdout_baseline_comparison"]["event_ofi"]["markout_lift_bps"] == 0.11
    assert payload["smoke_prediction"]["action"] == "quote"
    assert payload["smoke_latency"]["p95_ms"] == 0.2
    assert payload["artifacts"]["model"]["path"] == "model.cbm"


def test_promoted_markout_model_health_reports_missing_artifacts(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        markout_model_service,
        "settings",
        FakeSettings(
            tmp_path,
            tmp_path / "missing.cbm",
            tmp_path / "missing.isotonic.json",
            tmp_path / "missing-report.json",
        ),
    )

    payload = markout_model_service.promoted_markout_model_health()

    assert payload["available"] is False
    assert payload["missing_artifacts"]
    assert {item["label"] for item in payload["missing_artifacts"]} == {
        "model",
        "calibrator",
        "report",
    }
