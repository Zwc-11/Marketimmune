"""L2 book snapshots from the requester-pays ``hyperliquid-archive`` bucket.

``market_data/<YYYYMMDD>/<hour>/l2Book/<COIN>.lz4`` is LZ4-framed NDJSON, one snapshot per
line, wrapped as ``{"time", "ver_num", "raw": {"channel": "l2Book", "data": {"coin", "time",
"levels": [bids, asks]}}}``. Each level is ``{"px": str, "sz": str, "n": int}``, best first.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NamedTuple

BPS = 10_000.0


def l2_book_key(coin: str, date: str, hour: int) -> str:
    return f"market_data/{date}/{hour}/l2Book/{coin}.lz4"


class L2Level(NamedTuple):
    """One aggregated price level: price, total size, number of resting orders."""

    # NOTE: a NamedTuple, not a dataclass: a day holds millions of levels and tuple
    # construction is twice as fast.
    px: float
    sz: float
    n: int


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """An L2 snapshot. ``bids`` are best-first (descending), ``asks`` best-first (ascending)."""

    ts_ms: int
    coin: str
    bids: tuple[L2Level, ...]
    asks: tuple[L2Level, ...]

    def features(self) -> dict[str, float]:
        """Top-of-book mid, spread (bps), microprice and size imbalance."""
        assert self.bids and self.asks, f"snapshot has an empty side: {self.coin=} {self.ts_ms=}"
        bid, ask = self.bids[0], self.asks[0]
        mid = (bid.px + ask.px) / 2.0
        total_sz = bid.sz + ask.sz
        assert total_sz > 0.0, f"top-of-book size is zero: {self.coin=} {self.ts_ms=}"
        return {
            "mid": mid,
            "spread_bps": (ask.px - bid.px) / mid * BPS,
            "microprice": (bid.px * ask.sz + ask.px * bid.sz) / total_sz,
            "top_imbalance": (bid.sz - ask.sz) / total_sz,
        }


def parse_l2_book_ndjson(text: str) -> list[BookSnapshot]:
    snapshots = []
    for line in text.splitlines():
        data = json.loads(line)["raw"]["data"]
        bids, asks = data["levels"]
        snapshots.append(
            BookSnapshot(
                ts_ms=data["time"],
                coin=data["coin"],
                bids=tuple([L2Level(float(x["px"]), float(x["sz"]), x["n"]) for x in bids]),
                asks=tuple([L2Level(float(x["px"]), float(x["sz"]), x["n"]) for x in asks]),
            )
        )
    return snapshots
