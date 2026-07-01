"""Argument parser for the Hyperliquid markout training script."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train a CatBoost toxicity model on Hyperliquid Gold training rows."
    )
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--date", default="20260601")
    parser.add_argument(
        "--coins",
        default="",
        help="Comma-separated coins. Defaults to --coin.",
    )
    parser.add_argument(
        "--dates",
        default="",
        help=(
            "Comma-separated dates or inclusive YYYYMMDD..YYYYMMDD ranges. "
            "Defaults to --date."
        ),
    )
    parser.add_argument(
        "--holdout-date",
        default="",
        help="Optional single YYYYMMDD holdout date for final unseen evaluation.",
    )
    parser.add_argument(
        "--holdout-dates",
        default="",
        help="Optional comma-separated dates/ranges for final unseen evaluation.",
    )
    parser.add_argument(
        "--holdout-coins",
        default="",
        help="Optional comma-separated holdout coins. Defaults to training coins.",
    )
    parser.add_argument("--horizon", default="10s", choices=["1s", "10s", "60s"])
    parser.add_argument(
        "--lake-root",
        type=Path,
        default=Path("data/hyperliquid"),
        help="Hyperliquid lake root.",
    )
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--purge-ms", type=float, default=60_000.0)
    parser.add_argument("--embargo-ms", type=float, default=60_000.0)
    parser.add_argument("--iterations", type=int, default=150)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--calibration-fraction",
        type=float,
        default=0.2,
        help="Tail fraction of each fold's train rows reserved for isotonic calibration.",
    )
    parser.add_argument(
        "--disable-calibration",
        action="store_true",
        help="Use raw CatBoost probabilities instead of isotonic-calibrated probabilities.",
    )
    parser.add_argument(
        "--decision-threshold",
        type=float,
        default=None,
        help=(
            "Fixed skip threshold. Omit to tune fold-local thresholds from "
            "the requested threshold grid."
        ),
    )
    parser.add_argument(
        "--threshold-grid",
        default="0.05:0.95:0.01",
        help=(
            "Threshold candidates for auto policy tuning. Use start:end:step "
            "or a comma-separated list."
        ),
    )
    parser.add_argument(
        "--min-quote-rate",
        type=float,
        default=0.2,
        help="Minimum quote rate accepted during auto threshold selection.",
    )
    parser.add_argument(
        "--max-quote-rate",
        type=float,
        default=0.95,
        help="Maximum quote rate accepted during auto threshold selection.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap for fast smoke runs. 0 means all rows.",
    )
    parser.add_argument(
        "--allow-missing-partitions",
        action="store_true",
        help="Train on available local partitions and record skipped partitions.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/hyperliquid_markout_SOL_20260601.json"),
    )
    parser.add_argument(
        "--model-out",
        type=Path,
        default=Path("data/models/hyperliquid_catboost_SOL_10s.cbm"),
    )
    parser.add_argument(
        "--calibrator-out",
        type=Path,
        default=None,
        help="Optional JSON isotonic calibrator path. Defaults next to --model-out.",
    )
    return parser.parse_args()
