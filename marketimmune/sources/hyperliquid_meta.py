"""Asset index -> symbol and size decimals, from the ``info`` endpoint's ``meta``.

Actions name perps by index into ``meta.universe``; delisted assets keep their
slot and HIP-3 assets use a separate scheme. There is no historical ``meta``
endpoint, so each index used is checked two ways and the check is recorded:

1. against a saved snapshot (:func:`save_snapshot`, run daily on the recorder
   host once docs/jurisdiction.md clears API use), and
2. from the data itself: order ids placed by ``order`` actions on asset ``a``
   (via ``resps``) appear in ``node_fills_by_block`` with a coin name, which
   pins ``a`` -> coin for that date without calling the API.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

INFO_URL = "https://api.hyperliquid.xyz/info"


@dataclass(frozen=True)
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
    req = urllib.request.Request(
        url, data=json.dumps({"type": "meta"}).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out: dict[str, Any] = json.load(r)
    return out


def parse(meta: dict[str, Any]) -> dict[int, Asset]:
    return {
        i: Asset(
            index=i,
            name=u["name"],
            sz_decimals=int(u["szDecimals"]),
            max_leverage=u.get("maxLeverage"),
            delisted=bool(u.get("isDelisted", False)),
        )
        for i, u in enumerate(meta["universe"])
    }


def by_name(meta: dict[str, Any]) -> dict[str, Asset]:
    return {a.name: a for a in parse(meta).values()}


def save_snapshot(dest_dir: Path, meta: dict[str, Any] | None = None) -> Path:
    meta = meta if meta is not None else fetch_meta()
    stamp = datetime.now(UTC)
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"meta_{stamp:%Y%m%d}.json"
    path.write_text(json.dumps({"fetched_at": stamp.isoformat(), "meta": meta}, indent=1))
    return path


def load_snapshot(dest_dir: Path, on: date) -> tuple[date, dict[str, Any]]:
    """Latest snapshot taken on or before ``on``; else the oldest one available."""
    snaps = sorted(dest_dir.glob("meta_*.json"))
    if not snaps:
        raise FileNotFoundError(f"no meta snapshots in {dest_dir}; run save_snapshot first")

    def day(p: Path) -> date:
        return datetime.strptime(p.stem.removeprefix("meta_"), "%Y%m%d").date()

    before = [p for p in snaps if day(p) <= on]
    chosen = before[-1] if before else snaps[0]
    return day(chosen), json.loads(chosen.read_text())["meta"]


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/bronze/meta")
    p = save_snapshot(dest)
    assets = by_name(json.loads(p.read_text())["meta"])
    for c in ("BTC", "ETH", "SOL"):
        a = assets[c]
        print(f"{c}: index={a.index} szDecimals={a.sz_decimals} pxDecimals={a.px_decimals}")
    print(f"saved {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
