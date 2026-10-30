"""Save today's Hyperliquid asset metadata (tick and lot decimals) to data/bronze/meta.

    python -m marketimmune.cli.snapshot_asset_meta [dest_dir]"""

from marketimmune.sources.hyperliquid_meta import main

if __name__ == "__main__":
    raise SystemExit(main())
