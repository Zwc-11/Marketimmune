"""Synthesise a labelled feature dataset from the scenario registry.

Each registered `AgentScenario` produces a deterministic per-tick feature
vector. We perturb those vectors with low-amplitude Gaussian noise and
emit `(X, y)` with `y=1` for hostile scenarios and `y=0` for benign
ones. That gives us a clean, reproducible binary classification task to
train and evaluate the `RiskScorer` against — and it stays consistent
with what the simulator actually emits at inference time.

A real production system would substitute event-stream-derived features
here; the contract (numpy arrays in `FEATURE_ORDER`) is the same.
"""

from __future__ import annotations

import numpy as np

from marketimmune.models.risk_head import FEATURE_ORDER
from marketimmune.simulator.scenarios import ScenarioRegistry


def build_dataset(
    n_per_scenario: int = 800,
    noise_std: float = 0.55,
    contamination: float = 0.18,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build a realistic labelled dataset from the scenario registry.

    The naive approach — emit each scenario's template features with
    small Gaussian noise — produces a perfectly separable dataset and
    therefore a useless PR-AUC. We make the benchmark honest by:

    1. Adding *large* multiplicative noise so feature distributions
       overlap across families. Hostile flow with a quiet minute and
       benign flow during a price spike are both realistic.
    2. *Contamination*: on a fixed fraction of rows we randomly pick a
       feature from the opposite family's template instead of the
       row's own scenario. This injects ambiguous samples and forces
       the classifier to learn multi-feature interactions, not lookup.

    The result is a non-trivial benchmark (PR-AUC well under 1.0) that
    is still reproducible from `seed`.
    """
    rng = np.random.default_rng(seed)
    catalog = ScenarioRegistry.catalog()
    # Pre-compute the template features for every scenario so we can
    # sample from "the other family" during contamination.
    templates: dict[str, dict[str, float]] = {}
    families: dict[str, str] = {}
    for meta in catalog:
        scenario = ScenarioRegistry.create(meta["name"])
        templates[meta["name"]] = dict(scenario.step(0, 100.0).features)
        families[meta["name"]] = meta["family"]

    hostile_names = [n for n, f in families.items() if f == "hostile"]
    benign_names = [n for n, f in families.items() if f == "benign"]

    rows: list[list[float]] = []
    labels: list[int] = []
    names: list[str] = []
    for meta in catalog:
        own_template = templates[meta["name"]]
        hostile = meta["family"] == "hostile"
        opposite_pool = benign_names if hostile else hostile_names
        for idx in range(n_per_scenario):
            row = []
            opposite_template = templates[opposite_pool[idx % len(opposite_pool)]]
            for key in FEATURE_ORDER:
                # With probability `contamination` we sample this feature
                # from the opposite-family template; otherwise from our
                # own. Then multiply by lognormal noise.
                src = opposite_template if rng.random() < contamination else own_template
                base = float(src.get(key, 0.0))
                jitter = float(rng.lognormal(mean=0.0, sigma=noise_std))
                row.append(max(0.0, base * jitter))
            rows.append(row)
            labels.append(1 if hostile else 0)
            names.append(meta["name"])
    X = np.asarray(rows, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    return X, y, names
