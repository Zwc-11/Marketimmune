"""Hyperliquid fills ingestion.

The public API fill shape documents the stable fields we need for labels:
``coin``, ``px``, ``sz``, ``side`` (``B`` buy / ``A`` ask-sell), ``time`` in
milliseconds, ``crossed`` (taker flag), ``fee``, ``oid``, and ``tid``.

The bulk ``hl-mainnet-node-data/node_fills_by_block`` archive may wrap those fills
inside block-level envelopes, so this module is deliberately tolerant of nested
``{"fill": ...}``, ``{"fills": [...]}``, and raw fill records. Network and codec
work stay behind injected callables; parsing is pure.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from marketimmune.labels.markout import BPS, MakerFill

NODE_DATA_BUCKET = "hl-mainnet-node-data"
NODE_FILLS_BY_BLOCK_PREFIX = "node_fills_by_block"


def node_fills_by_block_key(suffix: str = "") -> str:
    """Build an object key under ``node_fills_by_block``.

    ``suffix`` is intentionally free-form because the public docs identify the prefix
    but not a stable date/block partition contract. Confirm the exact suffix against a
    real requester-pays listing before automating a backfill.
    """
    cleaned = suffix.strip("/")
    if not cleaned:
        return NODE_FILLS_BY_BLOCK_PREFIX
    return f"{NODE_FILLS_BY_BLOCK_PREFIX}/{cleaned}"


def normalize_side(value: object) -> str:
    """Normalize a Hyperliquid side value to ``B`` or ``A``."""
    text = str(value).strip().upper()
    if text in {"B", "BUY", "BID", "LONG"}:
        return "B"
    if text in {"A", "ASK", "SELL", "SHORT"}:
        return "A"
    raise ValueError(f"unknown Hyperliquid fill side: {value!r}")


def side_sign(side: str) -> int:
    """User-direction sign: ``B`` = +1, ``A`` = -1."""
    normalized = normalize_side(side)
    return 1 if normalized == "B" else -1


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(str(value))


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"unknown boolean value: {value!r}")


@dataclass(frozen=True, slots=True)
class NodeFill:
    """One parsed fill from a Hyperliquid API/archive row."""

    coin: str
    ts_ms: int
    px: float
    sz: float
    side: str
    crossed: bool | None
    oid: int | None = None
    tid: int | None = None
    trade_hash: str | None = None
    fee: float | None = None
    fee_token: str | None = None
    builder_fee: float | None = None
    direction: str | None = None
    raw: Mapping[str, Any] | None = None
    # Promoted from the raw row (fix L3) so Silver never has to re-parse raw_json.
    user: str | None = None
    start_position: float | None = None
    priority_gas: float | None = None
    liquidation: bool = False

    @property
    def user_side_sign(self) -> int:
        """Direction of the reported user fill: buy = +1, sell = -1."""
        return side_sign(self.side)

    @property
    def maker_side(self) -> int:
        """Maker-side sign for markout labels.

        If ``crossed`` is true, the reported user crossed the spread and the maker is
        on the opposite side. If ``crossed`` is false, the reported user was resting.
        If the archive omits ``crossed``, keep the reported side and treat it as
        already maker-oriented until a real file proves otherwise.
        """
        if self.crossed is None:
            return self.user_side_sign
        return -self.user_side_sign if self.crossed else self.user_side_sign

    @property
    def notional(self) -> float:
        """Fill notional in quote currency."""
        return self.px * self.sz

    @property
    def fee_bps(self) -> float | None:
        """Fee paid as bps of notional, when fee is present."""
        if self.fee is None or self.notional <= 0.0:
            return None
        return self.fee / self.notional * BPS

    def to_maker_fill(self) -> MakerFill:
        """Convert to the markout label module's maker-fill value object."""
        return MakerFill(ts_s=self.ts_ms / 1000.0, price=self.px, side=self.maker_side)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation for Bronze/Silver artifacts."""
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
    """Parse one documented Hyperliquid fill mapping."""
    data: Mapping[str, Any] = row["fill"] if isinstance(row.get("fill"), Mapping) else row
    return NodeFill(
        coin=str(data["coin"]),
        ts_ms=int(data["time"]),
        px=float(data["px"]),
        sz=float(data["sz"]),
        side=normalize_side(data["side"]),
        crossed=_optional_bool(data.get("crossed")),
        oid=_optional_int(data.get("oid")),
        tid=_optional_int(data.get("tid")),
        trade_hash=_optional_str(data.get("hash")),
        fee=_optional_float(data.get("fee")),
        fee_token=_optional_str(data.get("feeToken")),
        builder_fee=_optional_float(data.get("builderFee")),
        direction=_optional_str(data.get("dir")),
        raw=dict(data),
        user=_optional_str(data.get("user")),
        start_position=_optional_float(data.get("startPosition")),
        priority_gas=_optional_float(data.get("priorityGas")),
        liquidation=_is_liquidation(data.get("liquidation")),
    )


def _is_liquidation(value: object) -> bool:
    """Node fills carry ``liquidation: {liquidatedUser, markPx, method}`` or null."""
    if value is None or value is False or value == "":
        return False
    if isinstance(value, Mapping):
        return bool(value)
    return _optional_bool(value) is True


def iter_fill_mappings(obj: Any) -> Iterator[Mapping[str, Any]]:
    """Yield raw fill mappings from raw, nested, or block-level JSON objects."""
    if isinstance(obj, list):
        if len(obj) == 2 and isinstance(obj[1], Mapping) and _looks_like_fill(obj[1]):
            fill = dict(obj[1])
            fill.setdefault("user", obj[0])
            yield fill
            return
        for item in obj:
            yield from iter_fill_mappings(item)
        return
    if not isinstance(obj, Mapping):
        return
    if isinstance(obj.get("fill"), Mapping):
        yield obj["fill"]
        return
    for key in ("events", "fills", "userFills", "node_fills", "nodeFills"):
        nested = obj.get(key)
        if isinstance(nested, list):
            for item in nested:
                yield from iter_fill_mappings(item)
            return
    if _looks_like_fill(obj):
        yield obj


def _looks_like_fill(obj: Mapping[str, Any]) -> bool:
    return {"coin", "px", "sz", "side", "time"}.issubset(obj.keys())


def parse_node_fills_json(text: str) -> list[NodeFill]:
    """Parse a JSON or NDJSON payload into fills."""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        fills: list[NodeFill] = []
        for line in text.splitlines():
            line_text = line.strip()
            if not line_text:
                continue
            fills.extend(parse_fill_row(row) for row in iter_fill_mappings(json.loads(line_text)))
        return fills
    return [parse_fill_row(row) for row in iter_fill_mappings(obj)]


@dataclass(frozen=True, slots=True)
class HyperliquidNodeFills:
    """Reads node-fill payloads via injected ``fetch`` and ``decompress`` callables."""

    fetch: Callable[[str], bytes]
    decompress: Callable[[bytes], bytes]

    def load_key(self, key: str) -> list[NodeFill]:
        """Fetch + decompress + parse a node-fills object key."""
        raw = self.fetch(key)
        return parse_node_fills_json(self.decompress(raw).decode("utf-8"))

    def load_by_block_suffix(self, suffix: str = "") -> list[NodeFill]:
        """Load a key under the ``node_fills_by_block`` prefix."""
        return self.load_key(node_fills_by_block_key(suffix))


@dataclass(frozen=True, slots=True)
class MatchFill:
    """One match with both legs merged (fix B2).

    ``node_fills_by_block`` reports every match twice, once per wallet, and only the
    taker's leg has ``crossed = true``. Labelling legs separately counts each match
    twice and lets the copies land in different folds. A ``MatchFill`` is the single
    row a markout label belongs to. Field names that Gold reads (``side``,
    ``crossed``, ``oid``, ``maker_side``) are reported from the taker's view, so a
    ``MatchFill`` can stand wherever a ``NodeFill`` was labelled.
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
        """Side of the reported leg, which is the taker's."""
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
        return -side_sign(self.taker_side)

    @property
    def notional(self) -> float:
        return self.px * self.sz

    @property
    def maker_fee_bps(self) -> float | None:
        return _fee_bps(self.maker_fee, self.notional)

    @property
    def taker_fee_bps(self) -> float | None:
        return _fee_bps(self.taker_fee, self.notional)

    def to_maker_fill(self) -> MakerFill:
        return MakerFill(ts_s=self.ts_ms / 1000.0, price=self.px, side=self.maker_side)

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> MatchFill:
        """Rebuild from a Silver fills row (:meth:`to_dict`; derived columns ignored)."""
        return cls(
            coin=str(row["coin"]),
            ts_ms=int(row["ts_ms"]),
            px=float(row["px"]),
            sz=float(row["sz"]),
            taker_side=str(row["taker_side"]),
            tid=_optional_int(row.get("tid")),
            trade_hash=_optional_str(row.get("hash")),
            maker_user=_optional_str(row.get("maker_user")),
            taker_user=_optional_str(row.get("taker_user")),
            maker_oid=_optional_int(row.get("maker_oid")),
            taker_oid=_optional_int(row.get("taker_oid")),
            maker_fee=_optional_float(row.get("maker_fee")),
            taker_fee=_optional_float(row.get("taker_fee")),
            maker_start_position=_optional_float(row.get("maker_start_position")),
            taker_start_position=_optional_float(row.get("taker_start_position")),
            priority_gas=_optional_float(row.get("priority_gas")),
            liquidation=bool(row.get("liquidation") or False),
            n_legs=int(row.get("n_legs") or 2),
        )

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


def _fee_bps(fee: float | None, notional: float) -> float | None:
    if fee is None or notional <= 0.0:
        return None
    return fee / notional * BPS


def pair_fill_legs(fills: Sequence[NodeFill]) -> list[MatchFill]:
    """Merge the two legs of each match into one :class:`MatchFill`.

    Legs are keyed on ``(coin, ts_ms, tid)``; legs without a ``tid`` fall back to
    ``(coin, ts_ms, hash, px, sz)``. A lone leg (an API user-fills download holds
    only one wallet's side) still yields a row, with the other side's fields left
    ``None`` and ``n_legs = 1``. Output follows the first appearance of each match.

    Raises ``ValueError`` when two legs under one key disagree on price or size, or
    when a key has more than one taker or maker leg: either means the key is not
    unique and the dedupe would silently merge different trades.
    """
    groups: dict[tuple[object, ...], list[NodeFill]] = {}
    for fill in fills:
        key: tuple[object, ...] = (
            (fill.coin, fill.ts_ms, fill.tid)
            if fill.tid is not None
            else (fill.coin, fill.ts_ms, fill.trade_hash, fill.px, fill.sz)
        )
        groups.setdefault(key, []).append(fill)
    return [_merge_legs(key, legs) for key, legs in groups.items()]


def _merge_legs(key: tuple[object, ...], legs: list[NodeFill]) -> MatchFill:
    if len(legs) > 2:
        raise ValueError(f"{len(legs)} fill legs share key {key!r}")
    first = legs[0]
    if any(leg.px != first.px or leg.sz != first.sz for leg in legs[1:]):
        raise ValueError(f"fill legs under {key!r} disagree on px/sz")
    takers = [leg for leg in legs if leg.crossed is True]
    makers = [leg for leg in legs if leg.crossed is False]
    if len(takers) > 1 or len(makers) > 1:
        raise ValueError(f"fill legs under {key!r} have {len(takers)} takers, {len(makers)} makers")
    taker = takers[0] if takers else None
    maker = makers[0] if makers else None
    if taker is not None:
        taker_side = taker.side
    elif maker is not None:
        taker_side = "A" if maker.side == "B" else "B"
    else:
        # ``crossed`` missing: keep NodeFill.maker_side's convention (reported side
        # is the maker's), so the label orientation does not change.
        taker_side = "A" if first.side == "B" else "B"
        maker = first if len(legs) == 1 else None
    return MatchFill(
        coin=first.coin,
        ts_ms=first.ts_ms,
        px=first.px,
        sz=first.sz,
        taker_side=taker_side,
        tid=first.tid,
        trade_hash=(taker or maker or first).trade_hash,
        maker_user=maker.user if maker else None,
        taker_user=taker.user if taker else None,
        maker_oid=maker.oid if maker else None,
        taker_oid=taker.oid if taker else None,
        maker_fee=maker.fee if maker else None,
        taker_fee=taker.fee if taker else None,
        maker_start_position=maker.start_position if maker else None,
        taker_start_position=taker.start_position if taker else None,
        priority_gas=taker.priority_gas if taker else None,
        liquidation=any(leg.liquidation for leg in legs),
        n_legs=len(legs),
    )
