"""Tests for the shrunk taker-wallet scores (L2)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from marketimmune.features.wallet_toxicity import (
    WALLET_FEATURE_COLUMNS,
    shrunk_wallet_scores,
    verify_wallet_scores_no_lookahead,
    wallet_toxicity_features,
)


def test_scores_use_only_labels_known_strictly_before() -> None:
    ts = [0.0, 500.0, 2000.0, 2000.0, 3000.0]
    wallet = ["a", "b", "a", None, "a"]
    y = [-10.0, 4.0, 2.0, 0.0, np.nan]
    score, seen = shrunk_wallet_scores(ts, wallet, y, 1000.0, prior_weight=2.0)
    # t=0 and t=500: nothing known yet -> prior 0, no history
    assert score[:2].tolist() == [0.0, 0.0] and seen[:2].tolist() == [0.0, 0.0]
    # t=2000: rows at 0 and 500 are known (1000 and 1500 < 2000); prior = -3
    assert score[2] == pytest.approx((-10.0 + 2.0 * -3.0) / (1 + 2.0))
    assert score[3] == pytest.approx(-3.0)  # no wallet -> prior
    # t=3000: rows at 2000 are known only at 3000, so not yet (strict)
    assert score[4] == pytest.approx(score[2]) and seen[4] == 1.0


def test_wallet_toxicity_features_and_validation() -> None:
    f = wallet_toxicity_features([0.0, 2000.0], ["a", "a"], {"1s": [1.0, 2.0], "10s": [1.0, 2.0]})
    assert set(f) == set(WALLET_FEATURE_COLUMNS)
    assert f["taker_log_n"].tolist() == [0.0, 0.0]  # the 10 s label is not known by 2 s
    assert f["taker_tox_1s"][1] == pytest.approx((1.0 + 20.0 * 1.0) / 21.0)
    with pytest.raises(ValueError, match="same length"):
        shrunk_wallet_scores([0.0], [], [1.0], 1.0)
    with pytest.raises(ValueError, match="prior_weight"):
        shrunk_wallet_scores([0.0], ["a"], [1.0], 1.0, prior_weight=0.0)
    with pytest.raises(ValueError, match="horizon"):
        wallet_toxicity_features([0.0], ["a"], {"10m": [1.0]})


def test_streaming_matches_brute_force() -> None:
    rng = np.random.default_rng(3)
    n = 400
    ts = np.sort(rng.uniform(0, 60_000, n)).round()
    wallet = [None if k % 17 == 0 else f"w{k % 9}" for k in rng.integers(0, 50, n)]
    y = rng.normal(size=n)
    y[::23] = np.nan
    report = verify_wallet_scores_no_lookahead(ts, wallet, y, 1000.0, sample=60)
    assert report["passed"] is True and report["n_checked"] == 60
    assert math.isclose(report["max_abs_diff"], 0.0, abs_tol=1e-9)
