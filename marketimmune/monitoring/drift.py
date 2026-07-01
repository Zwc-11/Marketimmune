"""Distribution-drift monitors (v2 plan §6.5): PSI and the two-sample KS statistic.

Pure, dependency-free statistics for detecting feature/score drift between a *reference*
window (e.g. the training distribution) and a *current* window (recent live scores). The
*Remember* step uses these to decide when a retrain is warranted.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence

# PSI rule-of-thumb thresholds (industry standard).
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already-sorted sequence (``q`` in [0, 1])."""
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _bin_edges(reference: Sequence[float], bins: int) -> list[float]:
    """Interior quantile edges (``bins`` - 1 of them) from the reference sample."""
    ordered = sorted(reference)
    return [_quantile(ordered, i / bins) for i in range(1, bins)]


def _bin_fractions(values: Sequence[float], edges: Sequence[float], floor: float) -> list[float]:
    """Fraction of ``values`` in each of the ``len(edges) + 1`` bins, floored at ``floor``."""
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    total = len(values)
    return [max(count / total, floor) for count in counts]


def psi(
    reference: Sequence[float],
    current: Sequence[float],
    *,
    bins: int = 10,
    floor: float = 1e-6,
) -> float:
    """Population Stability Index between a reference and a current sample.

    Higher = more drift. Rule of thumb: < 0.1 stable, 0.1–0.25 moderate, > 0.25 significant.
    """
    if bins < 1:
        raise ValueError("bins must be >= 1")
    if not reference or not current:
        raise ValueError("reference and current must be non-empty")
    edges = _bin_edges(reference, bins)
    ref_frac = _bin_fractions(reference, edges, floor)
    cur_frac = _bin_fractions(current, edges, floor)
    return sum((c - r) * math.log(c / r) for r, c in zip(ref_frac, cur_frac, strict=True))


def ks_statistic(reference: Sequence[float], current: Sequence[float]) -> float:
    """Two-sample Kolmogorov–Smirnov statistic: max |CDF_ref - CDF_cur|, in [0, 1]."""
    if not reference or not current:
        raise ValueError("reference and current must be non-empty")
    ref_sorted = sorted(reference)
    cur_sorted = sorted(current)
    n_ref, n_cur = len(ref_sorted), len(cur_sorted)
    i = j = 0
    cdf_ref = cdf_cur = 0.0
    distance = 0.0
    while i < n_ref and j < n_cur:
        value_ref, value_cur = ref_sorted[i], cur_sorted[j]
        if value_ref <= value_cur:
            i += 1
            cdf_ref = i / n_ref
        if value_cur <= value_ref:
            j += 1
            cdf_cur = j / n_cur
        distance = max(distance, abs(cdf_ref - cdf_cur))
    return distance


def drift_severity(psi_value: float) -> str:
    """Map a PSI value to ``"none"`` / ``"moderate"`` / ``"significant"``."""
    if psi_value >= PSI_SIGNIFICANT:
        return "significant"
    if psi_value >= PSI_MODERATE:
        return "moderate"
    return "none"
