"""Adverse-selection labels.

The toxicity target is realized markout — see :mod:`marketimmune.labels.markout`.
"""

from marketimmune.labels.markout import (
    BPS,
    MakerFill,
    MarkoutConfig,
    future_mid_at,
    is_toxic,
    markout_bps,
    realized_markout_bps,
)

__all__ = [
    "BPS",
    "MakerFill",
    "MarkoutConfig",
    "future_mid_at",
    "is_toxic",
    "markout_bps",
    "realized_markout_bps",
]
