"""End-to-end test for the ML risk head: build dataset, train, predict, persist."""

from __future__ import annotations

from pathlib import Path

from marketimmune.models import FEATURE_ORDER, RiskScorer, build_dataset


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

    artifact = tmp_path / "risk_head.joblib"
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
