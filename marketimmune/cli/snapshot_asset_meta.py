"""Save today's Hyperliquid asset metadata (tick and lot decimals) to data/bronze/meta.

python -m marketimmune.cli.snapshot_asset_meta [dest_dir]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from marketimmune.sources.hyperliquid_meta import assets_by_name, fetch_meta, save_snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest", type=Path, nargs="?", default=Path("data/bronze/meta"))
    args = ap.parse_args(argv)
    meta = fetch_meta()
    path = save_snapshot(args.dest, meta)
    assets = assets_by_name(meta)
    for coin in ("BTC", "ETH", "SOL"):
        a = assets[coin]
        print(f"{coin}: index={a.index} szDecimals={a.sz_decimals} pxDecimals={a.px_decimals}")
    print(f"saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
