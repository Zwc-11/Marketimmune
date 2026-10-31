"""Tests for the Model Confidence Set."""

from __future__ import annotations

import numpy as np
import pytest

from marketimmune.models.mcs import model_confidence_set, stationary_bootstrap_indices


def test_bootstrap_indices_shape_and_validation() -> None:
    idx = stationary_bootstrap_indices(10, 50, 3.0, np.random.default_rng(0))
    assert idx.shape == (50, 10) and idx.min() >= 0 and idx.max() < 10
    with pytest.raises(ValueError, match="one observation"):
        stationary_bootstrap_indices(0, 5, 3.0, np.random.default_rng(0))
    with pytest.raises(ValueError, match="mean_block"):
        stationary_bootstrap_indices(5, 5, 0.5, np.random.default_rng(0))


def test_mcs_drops_the_clearly_worse_model_and_keeps_ties() -> None:
    rng = np.random.default_rng(0)
    days = 30
    base = rng.normal(0.20, 0.02, days)  # shared day effect, as in real daily losses
    losses = np.column_stack([
        base + rng.normal(0, 0.002, days),          # best
        base + 0.0005 + rng.normal(0, 0.002, days),  # indistinguishable from best
        base + 0.02 + rng.normal(0, 0.002, days),    # clearly worse
    ])
    res = model_confidence_set(losses, ["l2", "l3a", "l0"], alpha=0.10, n_boot=2000)
    assert res.elimination_order[0] == "l0"
    assert res.p_values[2] < 0.01
    assert set(res.included) == {"l2", "l3a"}
    payload = res.to_dict()
    assert [m["name"] for m in payload["models"]][-1] == "l0"
    assert max(res.p_values) == 1.0


def test_mcs_identical_models_and_validation() -> None:
    same = np.tile(np.linspace(0.1, 0.2, 5)[:, None], (1, 3))
    res = model_confidence_set(same, ["a", "b", "c"], n_boot=200)
    assert res.included == ("a", "b", "c") and res.elimination_order == ()
    with pytest.raises(ValueError, match="one name per column"):
        model_confidence_set(same, ["a", "b"])
    with pytest.raises(ValueError, match="two models"):
        model_confidence_set(same[:, :1], ["a"])
    with pytest.raises(ValueError, match="NaN"):
        model_confidence_set(np.where(same > 0.15, np.nan, same), ["a", "b", "c"])
    with pytest.raises(ValueError, match="alpha"):
        model_confidence_set(same, ["a", "b", "c"], alpha=1.5)
    with pytest.raises(ValueError, match="3 days"):
        model_confidence_set(same[:2], ["a", "b", "c"])
