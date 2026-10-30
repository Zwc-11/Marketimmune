import numpy as np
import polars as pl
import pytest

from marketimmune.lake import checks
from marketimmune.priority import nonces


def synthetic(n: int = 2_000, seed: int = 1) -> pl.LazyFrame:
    rng = np.random.default_rng(seed)
    t_block = 1_765_800_000_000 + np.sort(rng.integers(0, 3_600_000, n))
    rows = []
    # A clock signer: latency 40 ms + offset, jitter up to 70 ms (block wait).
    rows += [("clock", int(t), int(t - 40 - rng.integers(0, 70))) for t in t_block]
    # A counter signer: nonces are small integers, delays are enormous.
    rows += [("counter", int(t), i) for i, t in enumerate(t_block)]
    # A sloppy clock: 30% of delays far outside [0, 1000] ms.
    rows += [("sloppy", int(t), int(t - (50 if rng.random() > 0.3 else 5_000))) for t in t_block]
    # Too few actions to judge.
    rows += [("rare", int(t), int(t - 50)) for t in t_block[:10]]
    return pl.DataFrame(rows, schema=["signer", "t_block_ms", "nonce"], orient="row").lazy()


def test_clock_filter_keeps_only_clock_signers() -> None:
    stats = nonces.signer_latency(synthetic()).collect().sort("signer")
    verdict = dict(zip(stats["signer"], stats["is_clock"], strict=True))
    assert verdict == {"clock": True, "counter": False, "rare": False, "sloppy": False}
    lat = stats.filter(pl.col("signer") == "clock")["lat_ms"][0]
    assert 40 <= lat <= 45  # the 5% lower envelope sits just above the true 40 ms


def test_arrivals_and_summary() -> None:
    acts = synthetic()
    arr = nonces.attach_arrivals(acts).collect()
    assert set(arr["signer"]) == {"clock"}
    assert (arr["arrive_ms"] - arr["nonce"] == arr["lat_ms"]).all()
    s = nonces.delay_summary(acts)
    assert s["n"] == 6_010
    assert 0.5 < s["share_0_1000"] < 0.6
    assert s["q0.5"] > 0


def test_nonce_check_reports_share() -> None:
    stats = nonces.signer_latency(synthetic()).collect()
    c = checks.nonce_delays(stats, min_clock_share=0.2)
    assert c.ok and c.detail["clock_signers"] == 1
    assert c.detail["clock_action_share"] == pytest.approx(2000 / 6010, abs=1e-3)
