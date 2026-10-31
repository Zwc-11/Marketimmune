from __future__ import annotations

import json
from pathlib import Path

from marketimmune.sources.hyperliquid_meta import assets_by_name, save_snapshot

META = {
    "universe": [
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
        {"name": "OLD", "szDecimals": 0, "maxLeverage": 3, "isDelisted": True},
        {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
    ]
}


def test_assets_by_name_keeps_universe_indices() -> None:
    assets = assets_by_name(META)
    assert (assets["SOL"].index, assets["SOL"].sz_decimals, assets["SOL"].px_decimals) == (2, 2, 4)
    assert assets["OLD"].delisted and not assets["BTC"].delisted and assets["BTC"].px_decimals == 1


def test_save_snapshot(tmp_path: Path) -> None:
    path = save_snapshot(tmp_path / "meta", META)
    assert path.name.startswith("meta_") and json.loads(path.read_text())["meta"] == META
