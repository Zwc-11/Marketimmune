"""Gold-label assembly for Hyperliquid markout datasets.

This module does not fetch data. It combines already parsed fills and L2-book snapshots
into label rows that can later be joined to point-in-time features. Keeping this pure
lets the requester-pays backfill remain an I/O adapter while the label logic stays easy
to test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from marketimmune.ingest.hyperliquid_archive import BookSnapshot
from marketimmune.ingest.hyperliquid_fills import NodeFill
from marketimmune.labels.markout import BPS, MarkoutConfig

DEFAULT_MARKOUT_CONFIG = MarkoutConfig()


def horizon_key(seconds: float) -> str:
    """Stable dict key for a horizon in seconds."""
    return f"{int(seconds)}s" if float(seconds).is_integer() else f"{seconds:g}s"


def book_mid_series(snapshots: Sequence[BookSnapshot]) -> tuple[tuple[float, float], ...]:
    """Return ``(ts_s, mid)`` pairs sorted by timestamp."""
    return tuple(
        sorted((snapshot.ts_ms / 1000.0, snapshot.features()["mid"]) for snapshot in snapshots)
    )


@dataclass(frozen=True, slots=True)
class MarkoutGoldRow:
    """One fill with forward markout labels for available horizons."""

    coin: str
    ts_ms: int
    px: float
    sz: float
    side: str
    crossed: bool | None
    maker_side: int
    markout_bps: Mapping[str, float]
    toxic: Mapping[str, bool]
    oid: int | None = None
    tid: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation for reports or parquet writers."""
        return {
            "coin": self.coin,
            "ts_ms": self.ts_ms,
            "px": self.px,
            "sz": self.sz,
            "side": self.side,
            "crossed": self.crossed,
            "maker_side": self.maker_side,
            "markout_bps": dict(self.markout_bps),
            "toxic": dict(self.toxic),
            "oid": self.oid,
            "tid": self.tid,
        }


def build_markout_gold_rows(
    fills: Sequence[NodeFill],
    book_snapshots: Sequence[BookSnapshot],
    config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
    *,
    coin: str | None = None,
) -> list[MarkoutGoldRow]:
    """Attach forward markout labels to fills using the book mid series.

    Rows with no available future mid for any requested horizon are skipped rather
    than backfilled, so the label set never fabricates look-ahead values. The
    forward as-of join is one ``searchsorted`` per horizon over all fills.
    """
    mids = book_mid_series(book_snapshots)
    if not mids:
        return []
    selected = [fill for fill in fills if coin is None or fill.coin == coin]
    if not selected:
        return []
    mid_ts_s = np.fromiter((ts for ts, _mid in mids), dtype=np.float64, count=len(mids))
    mid_px = np.fromiter((mid for _ts, mid in mids), dtype=np.float64, count=len(mids))
    # One pass over the fills; maker_side is a computed property, so read it once.
    maker_sides = [fill.maker_side for fill in selected]
    count = len(selected)
    fill_ts_s = np.fromiter((fill.ts_ms for fill in selected), dtype=np.float64, count=count)
    fill_ts_s /= 1000.0
    price = np.fromiter((fill.px for fill in selected), dtype=np.float64, count=count)
    side = np.asarray(maker_sides, dtype=np.float64)
    if np.any(price <= 0.0):
        raise ValueError("fill_price must be positive")
    if np.any((side != 1.0) & (side != -1.0)):
        raise ValueError("side must be +1 (maker buy) or -1 (maker sell)")

    per_horizon: list[tuple[str, list[float], list[bool], list[bool]]] = []
    for horizon_s in config.horizons_s:
        idx = np.searchsorted(mid_ts_s, fill_ts_s + horizon_s, side="left")
        future_mid = mid_px[np.minimum(idx, mid_ts_s.size - 1)]
        markout = side * (future_mid - price) / price * BPS
        per_horizon.append((
            horizon_key(horizon_s),
            markout.tolist(),
            (markout < -config.fee_bps).tolist(),
            (idx < mid_ts_s.size).tolist(),
        ))

    rows: list[MarkoutGoldRow] = []
    for i, fill in enumerate(selected):
        markouts: dict[str, float] = {}
        toxic_flags: dict[str, bool] = {}
        for key, values, toxic, available in per_horizon:
            if available[i]:
                markouts[key] = values[i]
                toxic_flags[key] = toxic[i]
        if not markouts:
            continue
        rows.append(MarkoutGoldRow(
            coin=fill.coin,
            ts_ms=fill.ts_ms,
            px=fill.px,
            sz=fill.sz,
            side=fill.side,
            crossed=fill.crossed,
            maker_side=maker_sides[i],
            markout_bps=markouts,
            toxic=toxic_flags,
            oid=fill.oid,
            tid=fill.tid,
        ))
    return rows
