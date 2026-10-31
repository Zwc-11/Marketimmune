"""Realized markout: the adverse-selection (toxicity) label.

For a maker fill at time ``t``, price ``p`` and side ``s`` (``+1``: a resting bid was
filled, the maker bought; ``-1``: a resting ask was filled, the maker sold) the markout
over horizon ``h`` is ``s * (mid_{t+h} - p) / p * 10_000`` bps. Negative means the mid
moved against the maker (picked off); a fill is toxic when its markout is below
``-fee_bps``. The label reads ``mid_{t+h}``, so training on it needs purged and embargoed
walk-forward CV, never random splits. :mod:`marketimmune.lake.gold` builds the labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BPS = 10_000.0


@dataclass(frozen=True, slots=True)
class MarkoutConfig:
    """Forward horizons (seconds), the toxicity threshold (bps), and the label anchor.

    ``reference = "pre_fill_mid"`` (fix L2, the default) measures the move from the
    last mid strictly before the fill, so the label is the adverse move alone and a
    feature that knows the fill price cannot recover the half-spread part of it.
    ``"fill_px"`` reproduces the v2 label, which Gold still stores alongside as
    ``markout_px_bps_*`` for PnL accounting.

    With ``max_mid_lag_s`` set, a label needs the anchor mid no older than that before
    the fill and the future mid no later than that after ``t + h``; otherwise it would
    span a gap in the data (Albers misses 2025-12-12 17:40 to 18:16 UTC).
    """

    horizons_s: tuple[float, ...] = (1.0, 10.0, 60.0)
    fee_bps: float = 1.0
    reference: Literal["pre_fill_mid", "fill_px"] = "pre_fill_mid"
    max_mid_lag_s: float | None = None
