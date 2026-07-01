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
from collections.abc import Callable, Iterator, Mapping
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
    )


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
