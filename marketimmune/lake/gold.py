"""Gold markout labels: fills plus a mid series -> one labelled row per fill.

Pure (no I/O), so the backfill and the Albers builds stay thin adapters around it. A
label is never backfilled: a fill without a future mid for a horizon has no label at
that horizon, and a fill with none at all has no row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import numpy.typing as npt

from marketimmune.labels.markout import BPS, MarkoutConfig
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot


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
    """Stable column suffix for a horizon in seconds."""
    return f"{int(seconds)}s" if float(seconds).is_integer() else f"{seconds:g}s"


@dataclass(frozen=True, slots=True)
class MarkoutGoldRow:
    """One fill with forward markout labels for the horizons it has data for."""

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


def build_markout_gold_rows(
    fills: Sequence[LabelledFill],
    book_snapshots: Sequence[BookSnapshot],
    config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
    *,
    coin: str | None = None,
) -> list[MarkoutGoldRow]:
    """:func:`build_markout_gold_rows_from_mids` on the mids of ``book_snapshots`` (any order)."""
    mids = sorted((s.ts_ms / 1000.0, s.features()["mid"]) for s in book_snapshots)
    return build_markout_gold_rows_from_mids(fills, [t for t, _ in mids], [m for _, m in mids], config, coin=coin)


def build_markout_gold_rows_from_mids(
    fills: Sequence[LabelledFill],
    mid_ts_s: npt.ArrayLike,
    mid_px: npt.ArrayLike,
    config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
    *,
    coin: str | None = None,
) -> list[MarkoutGoldRow]:
    """Attach forward markout labels to the fills of ``coin`` (all fills when None).

    ``mid_ts_s`` (seconds, ascending) and ``mid_px`` are the mid series. The future
    mid of horizon ``h`` is the first at or after ``t + h`` (one ``searchsorted`` per
    horizon). With ``config.reference == "pre_fill_mid"`` a fill also needs a mid
    strictly before it (a snapshot in the fill's own millisecond may already show
    the fill), and has no labels without one.

    Pass deduped ``MatchFill`` rows (``pair_fill_legs``); raw ``NodeFill`` legs label
    each match twice. Maker/taker users and fees in bps are copied when the fill type
    carries them.
    """
    mid_ts_s = np.asarray(mid_ts_s, dtype=np.float64)
    mid_px = np.asarray(mid_px, dtype=np.float64)
    assert mid_ts_s.shape == mid_px.shape, f"{mid_ts_s.shape=} {mid_px.shape=}"
    assert np.all(mid_ts_s[1:] >= mid_ts_s[:-1]), "mid_ts_s must be sorted ascending"
    selected = [fill for fill in fills if coin is None or fill.coin == coin]
    if mid_ts_s.size == 0 or not selected:
        return []
    maker_sides = [fill.maker_side for fill in selected]  # a computed property: read it once
    fill_ts_s = np.array([fill.ts_ms for fill in selected], dtype=np.float64) / 1000.0
    price = np.array([fill.px for fill in selected], dtype=np.float64)
    side = np.array(maker_sides, dtype=np.float64)
    assert np.all(price > 0.0), "fill prices must be positive"
    assert np.all(np.abs(side) == 1.0), "maker side must be +1 (maker buy) or -1 (maker sell)"
    assert config.reference in ("pre_fill_mid", "fill_px"), f"{config.reference=}"

    last = mid_ts_s.size - 1
    lag = config.max_mid_lag_s
    # Last mid strictly before each fill (fix L2): the label's anchor.
    pre_idx = np.searchsorted(mid_ts_s, fill_ts_s, side="left") - 1
    has_pre = pre_idx >= 0
    if lag is not None:
        has_pre &= fill_ts_s - mid_ts_s[np.maximum(pre_idx, 0)] <= lag
    mid_before = mid_px[np.maximum(pre_idx, 0)]
    anchor, anchor_ok = (mid_before, has_pre) if config.reference == "pre_fill_mid" else (price, np.ones(price.size, dtype=bool))

    per_horizon: list[tuple[str, list[float], list[float], list[bool], list[bool]]] = []
    for horizon_s in config.horizons_s:
        target = fill_ts_s + horizon_s
        idx = np.searchsorted(mid_ts_s, target, side="left")
        future_mid = mid_px[np.minimum(idx, last)]
        available = (idx <= last) & anchor_ok
        if lag is not None:
            available &= mid_ts_s[np.minimum(idx, last)] - target <= lag
        markout = side * (future_mid - anchor) / anchor * BPS
        markout_px = side * (future_mid - price) / price * BPS
        per_horizon.append(
            (horizon_key(horizon_s), markout.tolist(), markout_px.tolist(), (markout < -config.fee_bps).tolist(), available.tolist())
        )

    mid_before_or_none = [m if ok else None for m, ok in zip(mid_before.tolist(), has_pre.tolist(), strict=True)]
    rows: list[MarkoutGoldRow] = []
    for i, fill in enumerate(selected):
        markouts: dict[str, float] = {}
        markouts_px: dict[str, float] = {}
        toxic_flags: dict[str, bool] = {}
        for key, values, values_px, toxic, available_h in per_horizon:
            if available_h[i]:
                markouts[key] = values[i]
                markouts_px[key] = values_px[i]
                toxic_flags[key] = toxic[i]
        if not markouts:
            continue
        rows.append(
            MarkoutGoldRow(
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
                mid_before=mid_before_or_none[i],
                markout_px_bps=markouts_px,
                # NOTE: NodeFill has no maker/taker split; MatchFill has no single-leg fee.
                maker_user=getattr(fill, "maker_user", None),
                taker_user=getattr(fill, "taker_user", None),
                maker_fee_bps=getattr(fill, "maker_fee_bps", None),
                taker_fee_bps=getattr(fill, "taker_fee_bps", None),
                priority_gas=getattr(fill, "priority_gas", None),
                liquidation=getattr(fill, "liquidation", None),
            )
        )
    return rows
