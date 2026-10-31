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


def fetch_meta(url: str = INFO_URL, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps({"type": "meta"}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        meta: dict[str, Any] = json.load(r)
    return meta


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
