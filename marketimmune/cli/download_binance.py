"""Download Binance USD-M aggTrades days into data/bronze/binance (sha256-verified).

    python -m marketimmune.cli.download_binance aggtrades SOLUSDT 2025-12-01 2025-12-31"""

from marketimmune.sources.binance_aggtrades import main

if __name__ == "__main__":
    raise SystemExit(main())
