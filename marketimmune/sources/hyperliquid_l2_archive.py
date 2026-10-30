"""Hyperliquid archive ingestion — read the public S3 archive into book snapshots.

Layout (Hyperliquid docs, "Historical data"; **requester-pays**):

* L2 book:    ``s3://hyperliquid-archive/market_data/<YYYYMMDD>/<hour>/l2Book/<COIN>.lz4``
* asset ctxs: ``s3://hyperliquid-archive/asset_ctxs/<YYYYMMDD>.csv.lz4``

Files are LZ4-frame compressed; l2Book files are newline-delimited JSON, one book
snapshot per line in Hyperliquid's WS shape ``{"coin", "time", "levels": [bids, asks]}``
(optionally wrapped in ``{"channel": "l2Book", "data": {...}}``), where each level is
``{"px", "sz", "n"}``. (SonarX's public mirror uses a different ``{market, block_time,
bids, asks}`` shape — a separate parser; not handled here.)

Design (Ports & Adapters): the network (boto3) and codec (lz4) live behind two injected
callables, so the parsing + microstructure derivation is **pure and fully testable**.
The boto3/lz4 wiring is the only untested boundary (``# pragma: no cover``) and needs the
optional extra: ``pip install -e ".[hyperliquid]"``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

BPS = 10_000.0
ARCHIVE_BUCKET = "hyperliquid-archive"


# ---- S3 key builders (pure) ------------------------------------------------


def l2_book_key(coin: str, date: str, hour: int) -> str:
    """Key for an L2-book file: ``market_data/<YYYYMMDD>/<hour>/l2Book/<COIN>.lz4``."""
    return f"market_data/{date}/{hour}/l2Book/{coin}.lz4"


def asset_ctxs_key(date: str) -> str:
    """Key for an asset-contexts file: ``asset_ctxs/<YYYYMMDD>.csv.lz4``."""
    return f"asset_ctxs/{date}.csv.lz4"


# ---- Book snapshot value objects (pure) ------------------------------------


@dataclass(frozen=True, slots=True)
class L2Level:
    """One aggregated price level: price, total size, number of resting orders."""

    px: float
    sz: float
    n: int


def parse_level(level: Mapping[str, Any]) -> L2Level:
    """Parse one ``{"px", "sz", "n"}`` level (px/sz are strings in the feed)."""
    return L2Level(px=float(level["px"]), sz=float(level["sz"]), n=int(level["n"]))


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """An L2 snapshot. ``bids`` are best-first (descending), ``asks`` best-first (ascending)."""

    ts_ms: int
    coin: str
    bids: tuple[L2Level, ...]
    asks: tuple[L2Level, ...]

    def features(self) -> dict[str, float]:
        """Top-of-book microstructure features (mid, spread bps, microprice, imbalance)."""
        if not self.bids or not self.asks:
            raise ValueError("snapshot has an empty side")
        best_bid, best_ask = self.bids[0], self.asks[0]
        mid = (best_bid.px + best_ask.px) / 2.0
        total_sz = best_bid.sz + best_ask.sz
        if total_sz <= 0.0:
            raise ValueError("top-of-book size is zero")
        return {
            "mid": mid,
            "spread_bps": (best_ask.px - best_bid.px) / mid * BPS,
            "microprice": (best_bid.px * best_ask.sz + best_ask.px * best_bid.sz) / total_sz,
            "top_imbalance": (best_bid.sz - best_ask.sz) / total_sz,
        }


def parse_book_snapshot(obj: Mapping[str, Any]) -> BookSnapshot:
    """Parse one l2Book record, tolerant of public archive envelopes."""
    record: Mapping[str, Any] = obj
    raw = obj.get("raw")
    if isinstance(raw, Mapping):
        record = raw
    data: Mapping[str, Any] = record.get("data", record)
    levels = data["levels"]
    bids = tuple(parse_level(x) for x in levels[0])
    asks = tuple(parse_level(x) for x in levels[1])
    return BookSnapshot(ts_ms=int(data["time"]), coin=str(data["coin"]), bids=bids, asks=asks)


def parse_l2_book_ndjson(text: str) -> list[BookSnapshot]:
    """Parse newline-delimited l2Book JSON (blank lines ignored)."""
    snapshots: list[BookSnapshot] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        snapshots.append(parse_book_snapshot(json.loads(stripped)))
    return snapshots


# ---- Archive client (pure orchestration over injected I/O) -----------------


@dataclass(frozen=True, slots=True)
class HyperliquidArchive:
    """Reads the archive via injected ``fetch`` (S3 get) and ``decompress`` (lz4)."""

    fetch: Callable[[str], bytes]
    decompress: Callable[[bytes], bytes]

    def load_l2_book(self, coin: str, date: str, hour: int) -> list[BookSnapshot]:
        """Fetch + decompress + parse one ``l2Book`` file into book snapshots."""
        raw = self.fetch(l2_book_key(coin, date, hour))
        return parse_l2_book_ndjson(self.decompress(raw).decode("utf-8"))


# ---- I/O wiring (the only untested boundary; optional extra) ----------------


def lz4_decompress(raw: bytes) -> bytes:  # pragma: no cover - thin codec boundary
    """LZ4-frame decompress. Requires the optional ``lz4`` package."""
    import lz4.frame

    return bytes(lz4.frame.decompress(raw))


def boto3_requester_pays_fetcher(
    bucket: str = ARCHIVE_BUCKET,
) -> Callable[[str], bytes]:  # pragma: no cover - network boundary
    """Build a requester-pays S3 fetch callable. Requires the optional ``boto3`` package."""
    import boto3

    client = boto3.client("s3")

    def _fetch(key: str) -> bytes:
        response = client.get_object(Bucket=bucket, Key=key, RequestPayer="requester")
        return bytes(response["Body"].read())

    return _fetch
