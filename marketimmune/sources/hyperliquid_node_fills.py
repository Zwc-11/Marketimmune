"""Fills from ``node_fills_by_block``, and the merge of each match's two legs into one row.

``node_fills_by_block/hourly/<YYYYMMDD>/<H>.lz4`` is LZ4-framed NDJSON, one block per line:
``{"local_time", "block_time", "block_number", "events": [[user, fill], ...]}``. A fill is
``{"coin", "px", "sz", "side": "B" | "A", "time" (ms), "crossed", "oid", "tid", "hash", "fee",
"feeToken", "startPosition", "dir", ...}``; ``priorityGas`` (from April 2026), ``builderFee``
and ``liquidation`` appear only when they apply. Every match is reported twice, once per
wallet, and only the taker's leg has ``crossed = true``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any

from marketimmune.sources.hyperliquid_l2_archive import BPS

SIDE_SIGN = {"B": 1, "A": -1}


def node_fills_key(date: str, hour: int) -> str:
    return f"node_fills_by_block/hourly/{date}/{hour}.lz4"


def _float(value: str | None) -> float | None:
    return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class NodeFill:
    """One leg of a match, as one wallet saw it."""

    coin: str
    ts_ms: int
    px: float
    sz: float
    side: str
    crossed: bool
    oid: int | None = None
    tid: int | None = None
    trade_hash: str | None = None
    fee: float | None = None
    fee_token: str | None = None
    builder_fee: float | None = None
    direction: str | None = None
    raw: Mapping[str, Any] | None = None
    user: str | None = None
    start_position: float | None = None
    priority_gas: float | None = None
    liquidation: bool = False

    @property
    def maker_side(self) -> int:
        """+1 when the maker bought: the opposite of a taker leg's side, a maker leg's own side."""
        sign = SIDE_SIGN[self.side]
        return -sign if self.crossed else sign

    def to_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "ts_ms": self.ts_ms,
            "px": self.px,
            "sz": self.sz,
            "side": self.side,
            "crossed": self.crossed,
            "maker_side": self.maker_side,
            "oid": self.oid,
            "tid": self.tid,
            "hash": self.trade_hash,
            "fee": self.fee,
            "fee_token": self.fee_token,
            "builder_fee": self.builder_fee,
            "direction": self.direction,
            "user": self.user,
            "start_position": self.start_position,
            "priority_gas": self.priority_gas,
            "liquidation": self.liquidation,
        }


def parse_fill_row(row: Mapping[str, Any]) -> NodeFill:
    """One fill mapping; ``user`` is the wallet its block event names."""
    assert row["side"] in SIDE_SIGN, f"{row['side']=}"
    return NodeFill(
        coin=row["coin"],
        ts_ms=row["time"],
        px=float(row["px"]),
        sz=float(row["sz"]),
        side=row["side"],
        crossed=row["crossed"],
        oid=row.get("oid"),
        tid=row.get("tid"),
        trade_hash=row.get("hash"),
        fee=_float(row.get("fee")),
        fee_token=row.get("feeToken"),
        builder_fee=_float(row.get("builderFee")),
        direction=row.get("dir"),
        raw=row,
        user=row.get("user"),
        start_position=_float(row.get("startPosition")),
        priority_gas=_float(row.get("priorityGas")),
        liquidation=row.get("liquidation") is not None,
    )


def parse_node_fills(text: str, coin: str) -> list[NodeFill]:
    """The legs of ``coin`` in one ``node_fills_by_block`` file."""
    quoted = f'"{coin}"'
    legs = []
    for line in text.splitlines():
        # Most blocks only trade other coins: skip them before paying for json.loads.
        if quoted not in line:
            continue
        for user, fill in json.loads(line)["events"]:
            if fill["coin"] == coin:
                fill["user"] = user
                legs.append(parse_fill_row(fill))
    return legs


@dataclass(frozen=True, slots=True)
class MatchFill:
    """One match with both legs merged: the row a markout label belongs to.

    Labelling the two legs separately counts each match twice and lets the copies land in
    different folds. ``side``, ``crossed``, ``oid`` and ``maker_side`` read as the taker's
    leg would, so a ``MatchFill`` stands wherever Gold reads a ``NodeFill``.
    """

    coin: str
    ts_ms: int
    px: float
    sz: float
    taker_side: str
    tid: int | None = None
    trade_hash: str | None = None
    maker_user: str | None = None
    taker_user: str | None = None
    maker_oid: int | None = None
    taker_oid: int | None = None
    maker_fee: float | None = None
    taker_fee: float | None = None
    maker_start_position: float | None = None
    taker_start_position: float | None = None
    priority_gas: float | None = None
    liquidation: bool = False
    n_legs: int = 2

    @property
    def side(self) -> str:
        return self.taker_side

    @property
    def crossed(self) -> bool:
        return True

    @property
    def oid(self) -> int | None:
        return self.taker_oid

    @property
    def maker_side(self) -> int:
        """+1 when the resting bid was hit (maker bought), -1 when the ask was lifted."""
        return -SIDE_SIGN[self.taker_side]

    @property
    def notional(self) -> float:
        return self.px * self.sz

    @property
    def maker_fee_bps(self) -> float | None:
        return None if self.maker_fee is None else self.maker_fee / self.notional * BPS

    @property
    def taker_fee_bps(self) -> float | None:
        return None if self.taker_fee is None else self.taker_fee / self.notional * BPS

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> MatchFill:
        """Rebuild from a Silver fills row (:meth:`to_dict`; derived columns are ignored)."""
        return cls(trade_hash=row["hash"], **{name: row[name] for name in _RECORD_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "ts_ms": self.ts_ms,
            "px": self.px,
            "sz": self.sz,
            "notional": self.notional,
            "taker_side": self.taker_side,
            "maker_side": self.maker_side,
            "tid": self.tid,
            "hash": self.trade_hash,
            "maker_user": self.maker_user,
            "taker_user": self.taker_user,
            "maker_oid": self.maker_oid,
            "taker_oid": self.taker_oid,
            "maker_fee": self.maker_fee,
            "taker_fee": self.taker_fee,
            "maker_fee_bps": self.maker_fee_bps,
            "taker_fee_bps": self.taker_fee_bps,
            "maker_start_position": self.maker_start_position,
            "taker_start_position": self.taker_start_position,
            "priority_gas": self.priority_gas,
            "liquidation": self.liquidation,
            "n_legs": self.n_legs,
        }


_RECORD_FIELDS = tuple(f.name for f in fields(MatchFill) if f.name != "trade_hash")


def leg_key(fill: NodeFill) -> tuple[str, int, int | None, str | None, int | None, str, bool]:
    """What makes a leg one leg: the match, the wallet, its order, side and role."""
    return (fill.coin, fill.ts_ms, fill.tid, fill.user, fill.oid, fill.side, fill.crossed)


def dedupe_fill_legs(fills: Sequence[NodeFill]) -> tuple[list[NodeFill], int]:
    """``fills`` with repeats of the same leg dropped (overlapping source objects deliver one
    leg twice), in first-seen order, and how many were dropped."""
    seen: set[tuple[str, int, int | None, str | None, int | None, str, bool]] = set()
    unique: list[NodeFill] = []
    for fill in fills:
        key = leg_key(fill)
        if key not in seen:
            seen.add(key)
            unique.append(fill)
    return unique, len(fills) - len(unique)


def pair_fill_legs(fills: Sequence[NodeFill]) -> list[MatchFill]:
    """One maker opportunity per match: the taker and maker legs of each ``(coin, ts_ms, tid)``
    merged, in first-seen order, after :func:`dedupe_fill_legs`. A match that does not have
    exactly one taker and one maker leg is an error, not a guess at which leg is which."""
    legs_by_match: dict[tuple[str, int, int | None], list[NodeFill]] = {}
    for fill in dedupe_fill_legs(fills)[0]:
        legs_by_match.setdefault((fill.coin, fill.ts_ms, fill.tid), []).append(fill)
    return [_merge_legs(legs) for legs in legs_by_match.values()]


def _merge_legs(legs: list[NodeFill]) -> MatchFill:
    assert len(legs) == 2, f"{len(legs)} legs share one match: {legs[0].coin=} {legs[0].ts_ms=} {legs[0].tid=}"
    taker, maker = legs if legs[0].crossed else legs[::-1]
    assert taker.tid is not None and taker.crossed and not maker.crossed, f"not one taker and one maker leg: {legs=}"
    assert taker.px == maker.px and taker.sz == maker.sz, f"legs disagree on px/sz: {legs=}"
    return MatchFill(
        coin=taker.coin,
        ts_ms=taker.ts_ms,
        px=taker.px,
        sz=taker.sz,
        taker_side=taker.side,
        tid=taker.tid,
        trade_hash=taker.trade_hash,
        maker_user=maker.user,
        taker_user=taker.user,
        maker_oid=maker.oid,
        taker_oid=taker.oid,
        maker_fee=maker.fee,
        taker_fee=taker.fee,
        maker_start_position=maker.start_position,
        taker_start_position=taker.start_position,
        priority_gas=taker.priority_gas,
        liquidation=taker.liquidation or maker.liquidation,
    )
