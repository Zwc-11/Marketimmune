"""Data checks for the priority study. Each returns a :class:`Check` and never raises on
bad data, so a run can report every failure at once: every match has one taker and one
maker leg, block heights are contiguous, block times never decrease, and how many actions
come from clock-nonce signers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import polars as pl


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{'PASS' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


def fill_legs(fills: pl.DataFrame) -> Check:
    """Each (coin, tid) has exactly two legs, exactly one with ``crossed = true``."""
    g = fills.group_by("coin", "tid").agg(n=pl.len(), n_taker=pl.col("crossed").sum())
    bad = g.filter((pl.col("n") != 2) | (pl.col("n_taker") != 1))
    return Check(
        "fill_legs",
        bad.height == 0,
        {"matches": g.height, "bad_matches": bad.height, "examples": bad.head(5).to_dicts()},
    )


def heights_contiguous(heights: pl.Series) -> Check:
    """Block heights, sorted, increase by exactly one."""
    h = heights.sort()
    diffs = h.diff().drop_nulls()
    gaps = h.filter(pl.concat([pl.Series([1], dtype=diffs.dtype), diffs]) != 1)
    dupes = int((diffs == 0).sum())
    return Check(
        "heights_contiguous",
        gaps.len() == 0,
        {
            "first": h.min(),
            "last": h.max(),
            "n": h.len(),
            "breaks": gaps.len(),
            "duplicates": dupes,
            "first_breaks": gaps.head(5).to_list(),
        },
    )


def block_times_increasing(blocks: pl.DataFrame, height: str = "height", time: str = "t_block_ms") -> Check:
    """Block time never decreases with height."""
    s = blocks.sort(height)
    back = s.filter(pl.col(time).diff() < 0)
    return Check("block_times_increasing", back.height == 0, {"n": s.height, "decreases": back.height})


def nonce_delays(signer_stats: pl.DataFrame, min_clock_share: float = 0.0) -> Check:
    """Summarise the clock-signer filter from :func:`marketimmune.priority.nonces.signer_latency`.

    Passes when at least ``min_clock_share`` of actions come from clock signers.
    """
    total = int(signer_stats["n"].sum())
    clock = int(signer_stats.filter(pl.col("is_clock"))["n"].sum())
    share = clock / total if total else 0.0
    return Check(
        "nonce_delays",
        share >= min_clock_share,
        {
            "signers": signer_stats.height,
            "clock_signers": int(signer_stats["is_clock"].sum()),
            "actions": total,
            "clock_action_share": round(share, 4),
        },
    )
