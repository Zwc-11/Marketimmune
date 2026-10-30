"""Parity and contract tests for the CatBoost-free oblivious-tree evaluator."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from marketimmune.cli.export_web_model import build_web_artifact
from marketimmune.serving.oblivious_trees import (
    COMPACT_FORMAT,
    ObliviousEnsemble,
    ObliviousTree,
    compact_from_catboost_json,
    load_compact,
)

TINY_EXPORT = {
    "features_info": {"float_features": [{"borders": [0.5]}, {"borders": [1.0]}]},
    "oblivious_trees": [
        {
            "splits": [
                {"float_feature_index": 0, "border": 0.5, "split_type": "FloatFeature"},
                {"float_feature_index": 1, "border": 1.0, "split_type": "FloatFeature"},
            ],
            "leaf_values": [-1.0, 0.5, 0.25, 2.0],
        }
    ],
    "scale_and_bias": [1.0, [0.1]],
}


def test_leaf_index_is_the_split_bit_pattern() -> None:
    model = ObliviousEnsemble.from_catboost_json(TINY_EXPORT)
    rows = [[0.0, 0.0], [0.9, 0.0], [0.0, 2.0], [0.9, 2.0]]

    raw = model.raw_scores(rows)

    assert raw.tolist() == pytest.approx([-0.9, 0.6, 0.35, 2.1])
    proba = model.predict_proba(rows)
    assert proba[:, 1] == pytest.approx(1.0 / (1.0 + np.exp(-raw)))
    assert proba.sum(axis=1) == pytest.approx(np.ones(4))


def test_nan_features_go_left_like_catboost_min_mode() -> None:
    model = ObliviousEnsemble.from_catboost_json(TINY_EXPORT)

    assert model.raw_scores([[np.nan, np.nan]]).tolist() == pytest.approx([-0.9])


def test_compact_round_trip_and_metadata(tmp_path: Path) -> None:
    compact = compact_from_catboost_json(
        TINY_EXPORT, feature_columns=["a", "b"], metadata={"coin": "SOL"}
    )
    path = tmp_path / "model.json"
    path.write_text(json.dumps(compact), encoding="utf-8")

    loaded = load_compact(path)

    assert compact["format"] == COMPACT_FORMAT
    assert compact["coin"] == "SOL"
    assert loaded == ObliviousEnsemble.from_catboost_json(TINY_EXPORT)


def test_rejects_bad_shapes_and_formats() -> None:
    with pytest.raises(ValueError, match="2\\*\\*depth"):
        ObliviousTree(features=(0,), borders=(0.0,), leaves=(1.0,))
    with pytest.raises(ValueError, match="one feature index"):
        ObliviousTree(features=(0, 1), borders=(0.0,), leaves=(1.0, 2.0, 3.0, 4.0))
    with pytest.raises(ValueError, match="format"):
        ObliviousEnsemble.from_compact({"format": "other"})
    with pytest.raises(ValueError, match="feature_columns"):
        compact_from_catboost_json(TINY_EXPORT, feature_columns=["only-one"])
    with pytest.raises(ValueError, match="features"):
        ObliviousEnsemble.from_catboost_json(TINY_EXPORT).raw_scores([[1.0, 2.0, 3.0]])
    categorical = json.loads(json.dumps(TINY_EXPORT))
    categorical["oblivious_trees"][0]["splits"][0]["split_type"] = "OneHotFeature"
    with pytest.raises(ValueError, match="float-feature"):
        ObliviousEnsemble.from_catboost_json(categorical)


def test_web_artifact_carries_policy_and_calibrator() -> None:
    artifact = build_web_artifact(
        TINY_EXPORT,
        {
            "enabled": True,
            "x_thresholds": [0.0, 1.0],
            "y_thresholds": [0.1, 0.9],
            "feature_columns": ["a", "b"],
            "deployment_decision_threshold": 0.3,
        },
        {
            "model_name": "m",
            "coin": "SOL",
            "horizon": "10s",
            "holdout_split": {
                "pr_auc": 0.55,
                "markout_lift_bps": 0.86,
                "baseline_comparison": {"event_ofi": {"markout_lift_bps": 0.109}},
            },
        },
    )

    assert artifact["decision_threshold"] == 0.3
    assert artifact["calibrator"] == {"enabled": True, "x": [0.0, 1.0], "y": [0.1, 0.9]}
    assert artifact["holdout"]["lift_vs_event_ofi_bps"] == 0.109
    assert artifact["cv_scheme"] == "purged_kfold"
    with pytest.raises(ValueError, match="feature_columns"):
        build_web_artifact(TINY_EXPORT, {}, {})


def test_scores_are_batch_invariant_across_both_code_paths() -> None:
    rng = np.random.default_rng(11)
    trees = tuple(
        ObliviousTree(
            features=tuple(int(f) for f in rng.integers(0, 5, depth)),
            borders=tuple(float(b) for b in rng.normal(size=depth)),
            leaves=tuple(float(v) for v in rng.normal(size=1 << depth)),
        )
        for depth in (6, 6, 4, 6, 3) * 20
    )
    model = ObliviousEnsemble(trees=trees, n_features=5)
    rows = rng.normal(size=(600, 5))

    batch = model.raw_scores(rows)  # large-batch path
    single = np.concatenate([model.raw_scores(rows[i : i + 1]) for i in range(600)])

    assert np.array_equal(batch, single)
    assert ObliviousEnsemble(trees=(), n_features=5).raw_scores(rows[:2]).tolist() == [0.0, 0.0]


def test_matches_catboost_predict_proba(tmp_path: Path) -> None:
    catboost = pytest.importorskip("catboost")
    rng = np.random.default_rng(5)
    x = rng.normal(size=(3_000, 6))
    y = (x[:, 0] - 0.7 * x[:, 3] + rng.normal(size=3_000) > 0).astype(int)
    model = catboost.CatBoostClassifier(
        iterations=40, depth=5, verbose=False, random_seed=2, allow_writing_files=False
    )
    model.fit(x, y)
    exported = tmp_path / "m.json"
    model.save_model(str(exported), format="json")

    ensemble = ObliviousEnsemble.from_catboost_json(json.loads(exported.read_text()))
    probe = rng.normal(size=(500, 6))

    assert np.abs(ensemble.predict_proba(probe) - model.predict_proba(probe)).max() < 1e-12
