"""Gold-label assembly for Hyperliquid markout datasets.

This module does not fetch data. It combines already parsed fills and L2-book snapshots
into label rows that can later be joined to point-in-time features. Keeping this pure
lets the requester-pays backfill remain an I/O adapter while the label logic stays easy
to test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from marketimmune.ingest.hyperliquid_archive import BookSnapshot
from marketimmune.labels.markout import BPS, MarkoutConfig


class LabelledFill(Protocol):
    """What Gold reads from a fill: ``NodeFill`` (one leg) or ``MatchFill`` (deduped)."""

    @property
    def coin(self) -> str: ...
    @property
    def ts_ms(self) -> int: ...
    @property
    def px(self) -> float: ...
    @property
    def sz(self) -> float: ...
    @property
    def side(self) -> str: ...
    @property
    def crossed(self) -> bool | None: ...
    @property
    def maker_side(self) -> int: ...
    @property
    def oid(self) -> int | None: ...
    @property
    def tid(self) -> int | None: ...

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
    mid_before: float | None = None
    markout_px_bps: Mapping[str, float] = field(default_factory=dict)
    maker_user: str | None = None
    taker_user: str | None = None
    maker_fee_bps: float | None = None
    taker_fee_bps: float | None = None
    priority_gas: float | None = None
    liquidation: bool | None = None

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
            "mid_before": self.mid_before,
            "markout_px_bps": dict(self.markout_px_bps),
            "maker_user": self.maker_user,
            "taker_user": self.taker_user,
            "maker_fee_bps": self.maker_fee_bps,
            "taker_fee_bps": self.taker_fee_bps,
            "priority_gas": self.priority_gas,
            "liquidation": self.liquidation,
        }


def build_markout_gold_rows(
    fills: Sequence[LabelledFill],
    book_snapshots: Sequence[BookSnapshot],
    config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
    *,
    coin: str | None = None,
) -> list[MarkoutGoldRow]:
    """Attach forward markout labels to fills using the book mid series.

    Rows with no available future mid for any requested horizon are skipped rather
    than backfilled, so the label set never fabricates look-ahead values. With
    ``config.reference == "pre_fill_mid"`` a fill also needs a mid strictly before
    it (a snapshot in the fill's own millisecond may already show the fill), and is
    skipped without one. The forward as-of join is one ``searchsorted`` per horizon.

    Pass deduped ``MatchFill`` rows (``pair_fill_legs``); raw ``NodeFill`` legs label
    each match twice. Maker/taker users, fees in bps, priority gas and the
    liquidation flag are copied when the fill type carries them.
    """
    mids = book_mid_series(book_snapshots)
    if not mids:
        return []
    mid_ts_s = np.fromiter((ts for ts, _mid in mids), dtype=np.float64, count=len(mids))
    mid_px = np.fromiter((mid for _ts, mid in mids), dtype=np.float64, count=len(mids))
    return build_markout_gold_rows_from_mids(fills, mid_ts_s, mid_px, config, coin=coin)


def build_markout_gold_rows_from_mids(
    fills: Sequence[LabelledFill],
    mid_ts_s: npt.ArrayLike,
    mid_px: npt.ArrayLike,
    config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
    *,
    coin: str | None = None,
) -> list[MarkoutGoldRow]:
    """:func:`build_markout_gold_rows` on a mid series given as arrays (seconds, price).

    For sources that already hold mids by block (the Albers rebuild) and would
    otherwise build a ``BookSnapshot`` per block only to read its mid back.
    ``mid_ts_s`` must be sorted ascending.
    """
    mid_ts_s = np.asarray(mid_ts_s, dtype=np.float64)
    mid_px = np.asarray(mid_px, dtype=np.float64)
    if mid_ts_s.shape != mid_px.shape:
        raise ValueError("mid_ts_s and mid_px must have the same length")
    if mid_ts_s.size == 0:
        return []
    if np.any(np.diff(mid_ts_s) < 0.0):
        raise ValueError("mid_ts_s must be sorted ascending")
    selected = [fill for fill in fills if coin is None or fill.coin == coin]
    if not selected:
        return []
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

    # Last mid strictly before each fill (fix L2): the label's anchor.
    pre_idx = np.searchsorted(mid_ts_s, fill_ts_s, side="left") - 1
    has_pre = pre_idx >= 0
    mid_before = mid_px[np.maximum(pre_idx, 0)]
    if config.reference == "pre_fill_mid":
        anchor, anchor_ok = mid_before, has_pre
    elif config.reference == "fill_px":
        anchor, anchor_ok = price, np.ones(count, dtype=bool)
    else:
        raise ValueError(f"unknown markout reference {config.reference!r}")

    per_horizon: list[tuple[str, list[float], list[float], list[bool], list[bool]]] = []
    for horizon_s in config.horizons_s:
        idx = np.searchsorted(mid_ts_s, fill_ts_s + horizon_s, side="left")
        future_mid = mid_px[np.minimum(idx, mid_ts_s.size - 1)]
        markout = side * (future_mid - anchor) / anchor * BPS
        markout_px = side * (future_mid - price) / price * BPS
        per_horizon.append((
            horizon_key(horizon_s),
            markout.tolist(),
            markout_px.tolist(),
            (markout < -config.fee_bps).tolist(),
            ((idx < mid_ts_s.size) & anchor_ok).tolist(),
        ))

    rows: list[MarkoutGoldRow] = []
    for i, fill in enumerate(selected):
        markouts: dict[str, float] = {}
        markouts_px: dict[str, float] = {}
        toxic_flags: dict[str, bool] = {}
        for key, values, values_px, toxic, available in per_horizon:
            if available[i]:
                markouts[key] = values[i]
                markouts_px[key] = values_px[i]
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
            mid_before=float(mid_before[i]) if has_pre[i] else None,
            markout_px_bps=markouts_px,
            maker_user=getattr(fill, "maker_user", None),
            taker_user=getattr(fill, "taker_user", None),
            maker_fee_bps=getattr(fill, "maker_fee_bps", None),
            taker_fee_bps=getattr(fill, "taker_fee_bps", None),
            priority_gas=getattr(fill, "priority_gas", None),
            liquidation=getattr(fill, "liquidation", None),
        ))
    return rows
