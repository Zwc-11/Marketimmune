"""Market events for the paper trader, parsed from Hyperliquid and Coinbase WebSocket messages.

Hyperliquid (``wss://api.hyperliquid.xyz/ws``):

- ``bbo``: the best bid and ask, sent when either changes (about once a block) -> ``Top``.
- ``l2Book``: 20 levels a side, sent every few seconds -> ``Depth``.
- ``trades``: one row per match; ``side`` is the taker's (``B`` buys from the asks), ``users`` is
  ``[buyer, seller]`` -> ``Trade``. The first message after subscribing replays recent trades;
  ``parse_hl`` drops trades more than ``STALE_TRADE_MS`` older than their receive time.
- ``activeAssetCtx``: the perp's oracle, mark and funding. For builder-deployed (HIP-3) markets such
  as ``xyz:XYZ100``, which have no Coinbase product, the oracle is the price reference: a
  ``RefTop`` at the oracle price (bid = ask), timed at receipt, whenever it changes.

Coinbase (``wss://advanced-trade-ws.coinbase.com``, ``level2``): a snapshot, then level updates per
product. ``CoinbaseBooks`` keeps the books and emits a ``RefTop`` whenever a product's best bid or
ask changes. Coinbase is the price reference because it is licensed in Ontario; Binance's terms
there are an open question (``docs/research/jurisdiction.md``).

Every time is in milliseconds. Hyperliquid's are block times; ``RefTop.t_ms`` is the receive time.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

STALE_TRADE_MS = 5_000


@dataclass(frozen=True, slots=True)
class Top:
    coin: str
    t_ms: int
    bid: float
    bid_sz: float
    ask: float
    ask_sz: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


@dataclass(frozen=True, slots=True)
class Depth:
    coin: str
    t_ms: int
    bids: dict[float, float]
    asks: dict[float, float]


@dataclass(frozen=True, slots=True)
class Trade:
    coin: str
    t_ms: int
    px: float
    sz: float
    taker_buy: bool
    taker: str


@dataclass(frozen=True, slots=True)
class RefTop:
    coin: str
    t_ms: int
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid + self.ask)


Event = Top | Depth | Trade | RefTop


def parse_hl(msg: dict[str, Any], local_ms: int) -> list[Event]:
    """Events in one Hyperliquid message; subscription acks, pongs and one-sided books give none."""
    channel = msg.get("channel")
    data: Any = msg.get("data")
    if channel == "bbo":
        bid, ask = data["bbo"]
        if not bid or not ask:
            return []
        return [Top(data["coin"], int(data["time"]), float(bid["px"]), float(bid["sz"]), float(ask["px"]), float(ask["sz"]))]
    if channel == "l2Book":
        bids, asks = data["levels"]
        return [
            Depth(
                data["coin"],
                int(data["time"]),
                {float(x["px"]): float(x["sz"]) for x in bids},
                {float(x["px"]): float(x["sz"]) for x in asks},
            )
        ]
    if channel == "trades":
        out: list[Event] = []
        for x in data:
            t = int(x["time"])
            if local_ms - t > STALE_TRADE_MS:
                continue
            buy = x["side"] == "B"
            out.append(Trade(x["coin"], t, float(x["px"]), float(x["sz"]), buy, x["users"][0 if buy else 1]))
        return out
    if channel == "activeAssetCtx" and ":" in str(data.get("coin", "")):
        oracle = data["ctx"].get("oraclePx")
        if not oracle:
            return []
        px = float(oracle)
        return [RefTop(data["coin"], local_ms, px, px)]
    return []


class _Side:
    """One side of a Coinbase book: sizes by price, and a heap of prices with lazy deletion so the
    best price costs O(log n) per update. ``sign`` is -1 for bids (max-heap) and +1 for asks."""

    def __init__(self, sign: int) -> None:
        self.sign = sign
        self.size: dict[float, float] = {}
        self.heap: list[float] = []

    def clear(self) -> None:
        self.size.clear()
        self.heap.clear()

    def set(self, px: float, qty: float) -> None:
        if qty > 0:
            if px not in self.size:
                heapq.heappush(self.heap, self.sign * px)
            self.size[px] = qty
        else:
            self.size.pop(px, None)
        if len(self.heap) > 4 * len(self.size) + 64:
            self.heap = [self.sign * x for x in self.size]
            heapq.heapify(self.heap)

    def best(self) -> float | None:
        while self.heap and self.sign * self.heap[0] not in self.size:
            heapq.heappop(self.heap)
        return self.sign * self.heap[0] if self.heap else None


class CoinbaseBooks:
    """Coinbase ``level2`` books per product (``SOL-USD`` -> coin ``SOL``). ``apply`` returns a
    ``RefTop`` for each product whose top changed. A gap in ``sequence_num`` raises, so the caller
    reconnects and starts from a fresh snapshot."""

    def __init__(self) -> None:
        self.books: dict[str, tuple[_Side, _Side]] = {}
        self.best: dict[str, tuple[float, float]] = {}
        self.seq: int | None = None

    def apply(self, msg: dict[str, Any], local_ms: int) -> list[RefTop]:
        seq = msg.get("sequence_num")
        if seq is not None:
            assert self.seq is None or seq == self.seq + 1, f"coinbase sequence gap: {self.seq=} {seq=}"
            self.seq = seq
        if msg.get("channel") != "l2_data":
            return []
        out: list[RefTop] = []
        for event in msg["events"]:
            product = event["product_id"]
            bids, asks = self.books.setdefault(product, (_Side(-1), _Side(1)))
            if event["type"] == "snapshot":
                bids.clear()
                asks.clear()
            for u in event["updates"]:
                (bids if u["side"] == "bid" else asks).set(float(u["price_level"]), float(u["new_quantity"]))
            bid, ask = bids.best(), asks.best()
            if bid is None or ask is None:
                continue
            if (bid, ask) != self.best.get(product):
                self.best[product] = (bid, ask)
                out.append(RefTop(product.split("-")[0], local_ms, bid, ask))
        return out
