"""Download the Albers et al. Dec 2025 L4 dataset (Zenodo) into data/bronze/albers.

    python -m marketimmune.cli.download_albers --dest data/bronze/albers --set needed

The module also runs without the package installed (standard library only):
``python marketimmune/sources/albers_download.py --set needed``."""

from marketimmune.sources.albers_download import main

if __name__ == "__main__":
    raise SystemExit(main())
