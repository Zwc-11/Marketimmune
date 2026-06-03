"""End-to-end test for the ML risk head: build dataset, train, predict, persist."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from marketimmune.models import FEATURE_ORDER, RiskScorer, build_dataset, write_report
from marketimmune.models.risk_head import BenchmarkReport, RiskDecisionPolicy


def test_dataset_shape_and_balance() -> None:
    X, y, names = build_dataset(n_per_scenario=50, seed=7)
    assert X.shape[1] == len(FEATURE_ORDER)
    # The catalog has 3 hostile + 3 benign scenarios so balance must be 50/50.
    assert 0.40 < y.mean() < 0.60
    assert len(names) == X.shape[0]


def test_train_predict_roundtrip(tmp_path: Path) -> None:
    X, y, _ = build_dataset(n_per_scenario=200, seed=7)
    scorer, report = RiskScorer.train(X, y, seed=7)
    assert 0.0 < report.pr_auc <= 1.0
    assert report.n_test > 0

    artifact = tmp_path / "subdir" / "risk_head.joblib"
    scorer.save(artifact)
    reloaded = RiskScorer.load(artifact)
    assert reloaded.feature_order == scorer.feature_order

    sample = dict(zip(FEATURE_ORDER, X[0].tolist(), strict=False))
    a = scorer.predict(sample)
    b = reloaded.predict(sample)
    assert a.label == b.label
    assert abs(a.score - b.score) < 1e-12


def test_predict_returns_top_features() -> None:
    X, y, _ = build_dataset(n_per_scenario=100, seed=7)
    scorer, _ = RiskScorer.train(X, y, seed=7)
    sample = dict(zip(FEATURE_ORDER, X[0].tolist(), strict=False))
    pred = scorer.predict(sample)
    assert 0.0 <= pred.score <= 1.0
    assert pred.label in {"ALLOW", "ALERT", "BLOCK"}
    assert len(pred.top_features) == 3
    assert all(name in FEATURE_ORDER for name, _ in pred.top_features)


# ---------------------------------------------------------------------------
# RiskDecisionPolicy.label — cover BLOCK, ALERT, ALLOW branches
# ---------------------------------------------------------------------------


def test_policy_label_block() -> None:
    policy = RiskDecisionPolicy()
    assert policy.label(0.9) == "BLOCK"


def test_policy_label_alert() -> None:
    policy = RiskDecisionPolicy()
    assert policy.label(0.6) == "ALERT"


def test_policy_label_allow() -> None:
    policy = RiskDecisionPolicy()
    assert policy.label(0.1) == "ALLOW"


# ---------------------------------------------------------------------------
# BenchmarkReport.to_dict
# ---------------------------------------------------------------------------


def test_benchmark_report_to_dict() -> None:
    report = BenchmarkReport(
        pr_auc=0.85,
        roc_auc=0.88,
        f1=0.82,
        precision_at_50=0.90,
        accuracy=0.91,
        n_train=300,
        n_test=100,
        model_name="TestModel",
    )
    d = report.to_dict()
    assert d["pr_auc"] == 0.85
    assert d["model_name"] == "TestModel"
    assert "precision_at_50" in d


# ---------------------------------------------------------------------------
# predict_batch
# ---------------------------------------------------------------------------


def test_predict_batch() -> None:
    X, y, _ = build_dataset(n_per_scenario=100, seed=7)
    scorer, _ = RiskScorer.train(X, y, seed=7)
    samples = [dict(zip(FEATURE_ORDER, X[i].tolist(), strict=False)) for i in range(5)]
    preds = scorer.predict_batch(samples)
    assert len(preds) == 5
    assert all(p.label in {"ALLOW", "ALERT", "BLOCK"} for p in preds)


# ---------------------------------------------------------------------------
# Held-out scenario split training
# ---------------------------------------------------------------------------


def test_train_wrong_feature_count_raises() -> None:
    """Passing wrong number of feature columns raises ValueError (line 195)."""
    import numpy as np
    X = np.zeros((10, 5))  # only 5 columns, not len(FEATURE_ORDER)
    y = np.array([0, 1] * 5)
    with pytest.raises(ValueError, match="columns"):
        RiskScorer.train(X, y, seed=7)



    X, y, names = build_dataset(n_per_scenario=50, seed=7)
    # Use one scenario family as the held-out set
    all_scenarios = list(set(names))
    held_out = all_scenarios[:1]
    scorer, report = RiskScorer.train(
        X, y, feature_order=FEATURE_ORDER, seed=7,
        scenario_names=list(names), held_out_scenarios=held_out,
    )
    assert report.n_train > 0
    assert report.n_test > 0


def test_train_held_out_produces_nan_when_single_class() -> None:
    """When held-out set has only one class, PR-AUC falls back to NaN."""
    X, y, names = build_dataset(n_per_scenario=50, seed=7)
    # Hold out ONE benign scenario only → test set is all-zero (benign), train has both classes
    scorer, report = RiskScorer.train(
        X, y, feature_order=FEATURE_ORDER, seed=7,
        scenario_names=list(names),
        held_out_scenarios=["twap_execution"],  # a single benign scenario
    )
    # Test set is all zeros → NaN for PR-AUC and ROC-AUC
    assert math.isnan(report.pr_auc)
    assert math.isnan(report.roc_auc)


def test_train_held_out_empty_split_raises() -> None:
    X, y, names = build_dataset(n_per_scenario=10, seed=7)
    with pytest.raises(ValueError, match="empty train or test"):
        RiskScorer.train(
            X, y, seed=7,
            scenario_names=list(names),
            held_out_scenarios=list(set(names)),  # all scenarios → empty train
        )


# ---------------------------------------------------------------------------
# _precision_at_top_k edge case: empty scores
# ---------------------------------------------------------------------------


def test_precision_at_top_k_empty() -> None:
    result = RiskScorer._precision_at_top_k(np.array([]), np.array([]), k=50)
    assert result == 0.0


# ---------------------------------------------------------------------------
# save/load with parent dir creation
# ---------------------------------------------------------------------------


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    X, y, _ = build_dataset(n_per_scenario=50, seed=7)
    scorer, _ = RiskScorer.train(X, y, seed=7)
    nested = tmp_path / "deep" / "nested" / "model.joblib"
    scorer.save(nested)
    assert nested.exists()


def test_load_without_policy_in_bundle(tmp_path: Path) -> None:
    """A bundle saved without the 'policy' key should load with defaults."""
    import joblib  # type: ignore[import-untyped]
    from sklearn.ensemble import GradientBoostingClassifier  # type: ignore[import-untyped]

    clf = GradientBoostingClassifier(n_estimators=5, random_state=0)
    clf.fit(
        np.zeros((10, len(FEATURE_ORDER))),
        np.array([0, 1] * 5),
    )
    bundle = {
        "estimator": clf,
        "feature_order": list(FEATURE_ORDER),
        # 'policy' key deliberately omitted
    }
    path = tmp_path / "no_policy.joblib"
    joblib.dump(bundle, path)

    scorer = RiskScorer.load(path)
    sample = {f: 0.0 for f in FEATURE_ORDER}
    pred = scorer.predict(sample)
    assert pred.label in {"ALLOW", "ALERT", "BLOCK"}


# ---------------------------------------------------------------------------
# feature_importances property
# ---------------------------------------------------------------------------


def test_feature_importances_property() -> None:
    X, y, _ = build_dataset(n_per_scenario=50, seed=7)
    scorer, _ = RiskScorer.train(X, y, seed=7)
    importances = scorer.feature_importances
    assert isinstance(importances, dict)
    assert set(importances.keys()) == set(FEATURE_ORDER)
    assert all(v >= 0.0 for v in importances.values())


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def test_write_report(tmp_path: Path) -> None:
    report = BenchmarkReport(
        pr_auc=0.85,
        roc_auc=0.88,
        f1=0.82,
        precision_at_50=0.90,
        accuracy=0.91,
        n_train=300,
        n_test=100,
        model_name="TestModel",
    )
    out = tmp_path / "reports" / "report.json"
    write_report(report, out)
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["pr_auc"] == 0.85
