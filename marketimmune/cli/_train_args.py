"""Command line of ``marketimmune.cli.train``."""

from __future__ import annotations

import argparse
from pathlib import Path

from marketimmune.features.training_rows import FEATURE_SETS
from marketimmune.models.cross_validation import CV_SCHEMES


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the CatBoost toxicity classifier on Gold training rows.")
    parser.add_argument("--coins", "--coin", dest="coins", default="SOL", help="comma-separated coins")
    parser.add_argument(
        "--dates", "--date", dest="dates", default="20260601", help="YYYYMMDD dates or inclusive a..b ranges, comma-separated"
    )
    parser.add_argument(
        "--holdout-dates", "--holdout-date", dest="holdout_dates", default="", help="later dates to score the final model on"
    )
    parser.add_argument("--horizon", default="10s", choices=["1s", "10s", "60s"])
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--feature-set", choices=sorted(FEATURE_SETS), default="l0", help="ladder rung (see FEATURE_SETS)")
    parser.add_argument("--cv-scheme", choices=CV_SCHEMES, default="rolling_daily")
    parser.add_argument("--train-days", type=int, default=7, help="training window before each tested day")
    parser.add_argument("--test-dates", default=None, help="test only these dates; the rest of --dates still trains")
    parser.add_argument("--purge-ms", type=float, default=60_000.0)
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--calibration-fraction", type=float, default=0.2, help="latest share of each training window kept for isotonic calibration"
    )
    parser.add_argument("--report", type=Path, default=Path("eval/hyperliquid_markout_SOL_20260601.json"))
    parser.add_argument("--model-out", type=Path, default=Path("data/models/hyperliquid_catboost_SOL_10s.cbm"))
    parser.add_argument("--calibrator-out", type=Path, default=None, help="isotonic JSON; defaults to <model-out>.isotonic.json")
    return parser.parse_args(argv)
