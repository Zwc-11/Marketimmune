"""Dependency-free evaluator for CatBoost oblivious-tree classifiers.

CatBoost's symmetric trees use one ``(feature, border)`` split per depth level, so a
row's leaf index is just the bit pattern ``sum_d [x[f_d] > b_d] << d``. That makes
scoring a gather over a ``(rows, depth)`` boolean matrix per tree, which NumPy (and
the browser, see ``frontend/src/lib/obliviousTrees.ts``) evaluates without the
CatBoost runtime.

The compact artifact written by :func:`compact_from_catboost_json` is what the web
terminal loads. ``tests/models/test_oblivious_trees.py`` pins parity with
``CatBoostClassifier.predict_proba``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

COMPACT_FORMAT = "marketimmune.oblivious.v1"
# Below this many rows, gathering all trees at once beats looping over trees.
SMALL_BATCH_ROWS = 256
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ObliviousTree:
    """One symmetric tree: ``depth`` splits and ``2**depth`` leaf values."""

    features: tuple[int, ...]
    borders: tuple[float, ...]
    leaves: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.features) != len(self.borders):
            raise ValueError("each split needs one feature index and one border")
        if len(self.leaves) != 1 << len(self.features):
            raise ValueError("leaf count must equal 2**depth")


@dataclass(frozen=True)
class ObliviousEnsemble:
    """Binary-logloss ensemble: ``p = sigmoid(scale * sum(leaves) + bias)``.

    Trees are packed once into ``(trees, depth)`` feature/border arrays and a
    ``(trees, 2**depth)`` leaf table (shallower trees padded with never-true
    splits), so a batch is scored for all trees at once in row chunks.
    """

    trees: tuple[ObliviousTree, ...]
    n_features: int
    scale: float = 1.0
    bias: float = 0.0
    _features: npt.NDArray[np.intp] = field(init=False, repr=False, compare=False)
    _borders: npt.NDArray[np.float32] = field(init=False, repr=False, compare=False)
    _leaves: FloatArray = field(init=False, repr=False, compare=False)
    _weights: npt.NDArray[np.int64] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        depth = max((len(tree.features) for tree in self.trees), default=0)
        count = len(self.trees)
        features = np.zeros((count, depth), dtype=np.intp)
        borders = np.full((count, depth), np.inf, dtype=np.float32)
        leaves = np.zeros((count, 1 << depth), dtype=np.float64)
        for i, tree in enumerate(self.trees):
            d = len(tree.features)
            features[i, :d] = tree.features
            borders[i, :d] = np.asarray(tree.borders, dtype=np.float32)
            leaves[i, : 1 << d] = tree.leaves
        object.__setattr__(self, "_features", features)
        object.__setattr__(self, "_borders", borders)
        object.__setattr__(self, "_leaves", leaves)
        object.__setattr__(self, "_weights", (1 << np.arange(depth, dtype=np.int64)))

    @classmethod
    def from_catboost_json(cls, payload: Mapping[str, Any]) -> ObliviousEnsemble:
        """Build from ``model.save_model(path, format="json")`` output."""
        trees = []
        for tree in payload["oblivious_trees"]:
            splits = tree["splits"]
            if any(split.get("split_type", "FloatFeature") != "FloatFeature" for split in splits):
                raise ValueError("only float-feature splits are supported")
            trees.append(ObliviousTree(
                features=tuple(int(split["float_feature_index"]) for split in splits),
                borders=tuple(float(split["border"]) for split in splits),
                leaves=tuple(float(value) for value in tree["leaf_values"]),
            ))
        scale, bias = _scale_and_bias(payload.get("scale_and_bias"))
        n_features = len(payload["features_info"]["float_features"])
        return cls(trees=tuple(trees), n_features=n_features, scale=scale, bias=bias)

    @classmethod
    def from_compact(cls, payload: Mapping[str, Any]) -> ObliviousEnsemble:
        if payload.get("format") != COMPACT_FORMAT:
            raise ValueError(f"expected format {COMPACT_FORMAT!r}")
        trees = tuple(
            ObliviousTree(
                features=tuple(int(item) for item in tree["f"]),
                borders=tuple(float(item) for item in tree["b"]),
                leaves=tuple(float(item) for item in tree["v"]),
            )
            for tree in payload["trees"]
        )
        return cls(
            trees=trees,
            n_features=len(payload["feature_columns"]),
            scale=float(payload.get("scale", 1.0)),
            bias=float(payload.get("bias", 0.0)),
        )

    def raw_scores(self, rows: Sequence[Sequence[float]] | npt.ArrayLike) -> FloatArray:
        # CatBoost compares float32 features against float32 borders; NaN fails every
        # split, matching CatBoost's default "Min" missing-value mode.
        matrix = np.asarray(rows, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self.n_features:
            raise ValueError(f"expected rows with {self.n_features} features")
        total: FloatArray
        if not self.trees:
            total = np.zeros(matrix.shape[0], dtype=np.float64)
        elif matrix.shape[0] <= SMALL_BATCH_ROWS:
            # Few rows (the live path): every tree in one gather, ~20 us per fill.
            bits = matrix[:, self._features] > self._borders  # (rows, trees, depth)
            index = bits.astype(np.int64) @ self._weights  # (rows, trees)
            # cumsum adds trees left to right, the same order as the loop below, so a
            # fill scores bit-identically alone or inside a large batch.
            total = np.cumsum(self._leaves[np.arange(len(self.trees)), index], axis=1)[:, -1]
        else:
            # Many rows: one pass per tree keeps the working set to a column at a time.
            total = np.zeros(matrix.shape[0], dtype=np.float64)
            for tree_id in range(len(self.trees)):
                index = np.zeros(matrix.shape[0], dtype=np.int64)
                for depth, feature in enumerate(self._features[tree_id]):
                    index |= (matrix[:, feature] > self._borders[tree_id, depth]).astype(
                        np.int64
                    ) << depth
                total += self._leaves[tree_id, index]
        scores: FloatArray = self.scale * total + self.bias
        return scores

    def predict_proba(self, rows: Sequence[Sequence[float]] | npt.ArrayLike) -> FloatArray:
        """Return ``[[1 - p, p], ...]`` like ``CatBoostClassifier.predict_proba``."""
        positive = 1.0 / (1.0 + np.exp(-self.raw_scores(rows)))
        return np.column_stack((1.0 - positive, positive))


def compact_from_catboost_json(
    payload: Mapping[str, Any],
    *,
    feature_columns: Sequence[str],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Shrink CatBoost's JSON export to the fields an evaluator needs."""
    ensemble = ObliviousEnsemble.from_catboost_json(payload)
    if ensemble.n_features != len(feature_columns):
        raise ValueError("feature_columns must match the model's float features")
    return {
        "format": COMPACT_FORMAT,
        "feature_columns": list(feature_columns),
        "scale": ensemble.scale,
        "bias": ensemble.bias,
        "trees": [
            {"f": list(tree.features), "b": list(tree.borders), "v": list(tree.leaves)}
            for tree in ensemble.trees
        ],
        **dict(metadata or {}),
    }


def load_compact(path: Path) -> ObliviousEnsemble:
    with path.open("r", encoding="utf-8") as handle:
        return ObliviousEnsemble.from_compact(json.load(handle))


def _scale_and_bias(value: Any) -> tuple[float, float]:
    if value is None:
        return 1.0, 0.0
    scale, bias = value
    bias_value = bias[0] if isinstance(bias, list) else bias
    scale_value, bias_float = float(scale), float(bias_value)
    if not (math.isfinite(scale_value) and math.isfinite(bias_float)):
        raise ValueError("scale_and_bias must be finite")
    return scale_value, bias_float
