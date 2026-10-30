"""Arrival times from nonces (Lesson 3.3).

For signer ``s`` and action ``i`` in a block with time ``T_i`` carrying nonce
``n_i`` (ms), the delay ``d_i = T_i - n_i`` is latency + clock offset + the wait
for the block cut. Its lower envelope estimates latency + offset:

    lat_s = Q_0.05({T_i - n_i}),   arrive_i = n_i + lat_s

Only "clock signers" are kept: wallets whose delays almost always fall in
[0, 1000] ms with a tight spread. Counter or random nonces fail the filter.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class ClockFilter:
    min_actions: int = 500
    delay_lo_ms: int = 0
    delay_hi_ms: int = 1_000
    min_share_in_range: float = 0.95
    max_iqr_ms: float = 100.0
    latency_quantile: float = 0.05

    @classmethod
    def from_config(cls) -> ClockFilter:
        from marketimmune.config import load

        return cls(**load("episodes")["clock_signer"])


def with_delay(acts: pl.LazyFrame) -> pl.LazyFrame:
    """Add ``d_ms = t_block_ms - nonce``. Needs ``t_block_ms`` and ``nonce`` (Int64)."""
    return acts.with_columns(d_ms=pl.col("t_block_ms") - pl.col("nonce"))


def signer_latency(acts: pl.LazyFrame, f: ClockFilter | None = None) -> pl.LazyFrame:
    """Per-signer delay statistics and the clock-signer verdict (all signers kept)."""
    f = f or ClockFilter()
    d = pl.col("d_ms")
    in_range = (d >= f.delay_lo_ms) & (d <= f.delay_hi_ms)
    return (
        with_delay(acts)
        .group_by("signer")
        .agg(
            n=pl.len(),
            lat_ms=d.quantile(f.latency_quantile, interpolation="lower"),
            median_ms=d.median(),
            iqr_ms=d.quantile(0.75, interpolation="linear") - d.quantile(0.25, interpolation="linear"),
            share_in_range=in_range.mean(),
        )
        .with_columns(
            is_clock=(pl.col("n") >= f.min_actions)
            & (pl.col("share_in_range") >= f.min_share_in_range)
            & (pl.col("iqr_ms") < f.max_iqr_ms)
        )
    )


def attach_arrivals(acts: pl.LazyFrame, f: ClockFilter | None = None) -> pl.LazyFrame:
    """Keep clock signers' actions and add ``arrive_ms = nonce + lat_ms``."""
    lat = signer_latency(acts, f).filter(pl.col("is_clock")).select("signer", "lat_ms")
    return acts.join(lat, on="signer", how="inner").with_columns(arrive_ms=pl.col("nonce") + pl.col("lat_ms"))


def delay_summary(acts: pl.LazyFrame) -> dict[str, float]:
    """Pooled delay distribution for the G0 note (all actions, all signers)."""
    d = pl.col("d_ms")
    qs = [0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]
    row = (
        with_delay(acts)
        .select(
            n=pl.len(),
            share_0_1000=((d >= 0) & (d <= 1_000)).mean(),
            share_negative=(d < 0).mean(),
            share_over_1day=(d > 86_400_000).mean(),
            **{f"q{q:g}": d.quantile(q, interpolation="linear") for q in qs},
        )
        .collect()
        .row(0, named=True)
    )
    return {k: float(v) for k, v in row.items()}
