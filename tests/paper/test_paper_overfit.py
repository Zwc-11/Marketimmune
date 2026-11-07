from __future__ import annotations

import numpy as np

from marketimmune.paper.overfit import deflated_sharpe, pbo_cscv


def test_pbo_is_high_for_noise_and_low_for_a_real_edge() -> None:
    pbos = [pbo_cscv(np.random.default_rng(seed).normal(0, 1, (64, 30)))["pbo"] for seed in range(20)]
    assert 0.4 < float(np.mean(pbos)) < 0.6  # no skill: the in-sample best is a coin flip out of sample
    noise = np.random.default_rng(0).normal(0, 1, (64, 30))
    edge = noise.copy()
    edge[:, 7] += 1.0  # one config really is better
    r = pbo_cscv(edge)
    assert r["pbo"] < 0.05 and r["best_in_sample_mean_oos"] > r["all_configs_mean_oos"]


def test_deflated_sharpe_falls_with_the_number_of_trials() -> None:
    rng = np.random.default_rng(1)
    r = rng.normal(0.3, 1, 100)
    few = deflated_sharpe(r, rng.normal(0, 0.1, 2))
    many = deflated_sharpe(r, rng.normal(0, 0.1, 200))
    assert few["deflated_sharpe"] > many["deflated_sharpe"]
    assert few["probabilistic_sharpe"] > 0.9
    assert many["expected_max_sharpe_of_trials"] > few["expected_max_sharpe_of_trials"]
