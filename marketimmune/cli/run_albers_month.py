"""Run the Albers December 2025 pipeline for one coin: Silver L2 + order events, Silver
fills, positions, the forced-flow forecast, Gold labels and training rows (with the L1
CEX gap), then the L2/L3 columns (taker-wallet scores, lost races, realised and forecast
forced flow).

    python -m marketimmune.cli.run_albers_month --coin SOL --dates 20251201..20251231

Stages can run alone (``--stages gold``); each reads the previous one's output from the
lake. The L2 stage is the slow one because order statuses are a sequential ``.tar.xz``.
Train and compare rungs afterwards with ``marketimmune.cli.train``.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from marketimmune.cli import build_albers_fills, build_albers_gold, build_albers_silver, build_positions, enrich_albers, forced_forecast
from marketimmune.logger import init_logger
from marketimmune.utils import split_csv

logger = init_logger(__name__)

STAGES = ("l2", "fills", "positions", "forecast", "gold", "enrich")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--stages", default=",".join(STAGES))
    parser.add_argument("--albers-dir", type=Path, default=Path("data/bronze/albers"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stages = split_csv(args.stages)
    unknown = sorted(set(stages) - set(STAGES))
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    common = ["--coin", args.coin, "--dates", args.dates, "--lake-root", str(args.lake_root)]
    albers = ["--albers-dir", str(args.albers_dir)]
    binance = ["--binance-dir", str(args.binance_dir)]
    t0 = time.perf_counter()
    if "l2" in stages:
        build_albers_silver.build(build_albers_silver.parse_args([*common, *albers]))
    if "fills" in stages:
        build_albers_fills.build(build_albers_fills.parse_args([*common, *albers]))
    if "positions" in stages:
        build_positions.build(build_positions.parse_args(common))
    if "forecast" in stages:  # sequential over dates: state and priors carry forward
        forced_forecast.build(forced_forecast.parse_args([*common, *binance]))
    if "gold" in stages:
        build_albers_gold.build(build_albers_gold.parse_args([*common, *binance]))
    if "enrich" in stages:
        enrich_albers.build(enrich_albers.parse_args(common))
    logger.info(f"done: {', '.join(stages)} in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
