"""Asset index -> name and size decimals, from the ``info`` endpoint's ``meta``.

Actions name perps by their index in ``meta.universe``; delisted assets keep their slot.
There is no historical ``meta`` endpoint, so a snapshot is saved daily (on the recorder host,
once docs/jurisdiction.md clears API use) and each index used is also checked against the
data itself: order ids placed by ``order`` actions on asset ``a`` (via ``resps``) appear in
``node_fills_by_block`` with a coin name.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True, slots=True)
class Asset:
    index: int
    name: str
    sz_decimals: int
    max_leverage: int | None
    delisted: bool

    @property
    def px_decimals(self) -> int:
        """Maximum price decimals for a perp: 6 - szDecimals."""
        return max(0, 6 - self.sz_decimals)


def info(payload: dict[str, Any], url: str = INFO_URL, timeout: float = 20.0) -> Any:
    """One POST to the ``info`` endpoint."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def fetch_meta(url: str = INFO_URL, timeout: float = 20.0) -> dict[str, Any]:
    meta: dict[str, Any] = info({"type": "meta"}, url, timeout)
    return meta


INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
MAX_CANDLES = 5_000  # per candleSnapshot response


def fetch_candles(coin: str, interval: str, start_ms: int, end_ms: int, url: str = INFO_URL) -> list[dict[str, Any]]:
    """Perp candles ``[start_ms, end_ms)`` (``t`` open time, ``o``/``h``/``l``/``c`` strings), in pages
    of ``MAX_CANDLES``. The endpoint serves only the most recent 5,000 candles of an interval."""
    step = INTERVAL_MS[interval] * MAX_CANDLES
    out: dict[int, dict[str, Any]] = {}
    for lo in range(start_ms, end_ms, step):
        hi = min(lo + step, end_ms) - 1
        for c in info({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": lo, "endTime": hi}}, url):
            if start_ms <= c["t"] < end_ms:
                out[c["t"]] = c
    return [out[t] for t in sorted(out)]


def assets_by_name(meta: dict[str, Any]) -> dict[str, Asset]:
    return {
        u["name"]: Asset(
            index=i, name=u["name"], sz_decimals=u["szDecimals"], max_leverage=u.get("maxLeverage"), delisted=u.get("isDelisted", False)
        )
        for i, u in enumerate(meta["universe"])
    }


def save_snapshot(dest_dir: Path, meta: dict[str, Any]) -> Path:
    """``<dest_dir>/meta_<YYYYMMDD>.json`` holding ``{"fetched_at", "meta"}``."""
    stamp = datetime.now(UTC)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"meta_{stamp:%Y%m%d}.json"
    path.write_text(json.dumps({"fetched_at": stamp.isoformat(), "meta": meta}, indent=1))
    return path
