"""Run the Albers December 2025 pipeline for one coin: Silver L2 + order events,
Silver fills, then Gold labels and training rows (with the L1 CEX gap).

    python -m marketimmune.cli.run_albers_month --coin SOL --dates 20251201..20251231

Stages can be run alone (``--stages gold``); each stage reads the previous one's
output from the lake. The L2 stage is the slow one (~15 s per hour on 2 cores)
because order statuses are a sequential ``.tar.xz``. Then train and compare rungs:

    python -m marketimmune.cli.train --coin SOL --dates 20251201..20251231 \\
        --feature-set l0_book --horizon 1s --report eval/sol_dec_l0.json \\
        --model-out data/models/sol_dec_l0.cbm
    (same with --feature-set l1_book)
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from marketimmune.cli import build_albers_fills, build_albers_gold, build_albers_silver

STAGES = ("l2", "fills", "gold")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--stages", default=",".join(STAGES))
    parser.add_argument(
        "--albers-dir", type=Path, default=Path("data/bronze/albers")
    )
    parser.add_argument(
        "--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades")
    )
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    unknown = sorted(set(stages) - set(STAGES))
    if unknown:
        raise SystemExit(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    common = ["--coin", args.coin, "--dates", args.dates, "--lake-root", str(args.lake_root)]
    albers = ["--albers-dir", str(args.albers_dir)]
    t0 = time.perf_counter()
    if "l2" in stages:
        build_albers_silver.build(build_albers_silver.parse_args([*common, *albers]))
    if "fills" in stages:
        build_albers_fills.build(build_albers_fills.parse_args([*common, *albers]))
    if "gold" in stages:
        build_albers_gold.build(
            build_albers_gold.parse_args([*common, "--binance-dir", str(args.binance_dir)])
        )
    print(f"done: {', '.join(stages)} in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
