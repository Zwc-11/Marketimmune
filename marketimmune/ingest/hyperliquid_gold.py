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

from marketimmune.ingest.hyperliquid_archive import BookSnapshot
from marketimmune.ingest.hyperliquid_fills import NodeFill
from marketimmune.labels.markout import MarkoutConfig, is_toxic, realized_markout_bps

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
    than backfilled, so the label set never fabricates look-ahead values.
    """
    mids = book_mid_series(book_snapshots)
    if not mids:
        return []
    mid_ts_s, mid_px = zip(*mids, strict=True)
    rows: list[MarkoutGoldRow] = []
    for fill in fills:
        if coin is not None and fill.coin != coin:
            continue
        maker_fill = fill.to_maker_fill()
        markouts: dict[str, float] = {}
        toxic_flags: dict[str, bool] = {}
        for horizon_s in config.horizons_s:
            markout = realized_markout_bps(maker_fill, mid_ts_s, mid_px, horizon_s)
            if markout is None:
                continue
            key = horizon_key(horizon_s)
            markouts[key] = markout
            toxic_flags[key] = is_toxic(markout, config.fee_bps)
        if not markouts:
            continue
        rows.append(MarkoutGoldRow(
            coin=fill.coin,
            ts_ms=fill.ts_ms,
            px=fill.px,
            sz=fill.sz,
            side=fill.side,
            crossed=fill.crossed,
            maker_side=fill.maker_side,
            markout_bps=markouts,
            toxic=toxic_flags,
            oid=fill.oid,
            tid=fill.tid,
        ))
    return rows
