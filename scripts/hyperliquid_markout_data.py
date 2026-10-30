"""Gold training-partition discovery and loading for the markout trainer."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.features.hyperliquid_features import (
    HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    HYPERLIQUID_OFI_COLUMNS,
)

FEATURE_COLUMNS = list(HYPERLIQUID_MARKOUT_FEATURE_COLUMNS)
OFI_COLUMNS = HYPERLIQUID_OFI_COLUMNS


@dataclass(frozen=True, slots=True)
class TrainingPartition:
    """One local Gold training parquet partition."""

    coin: str
    date: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.coin}:{self.date}"


def training_path(lake_root: Path, coin: str, date: str) -> Path:
    symbol = coin.strip().upper().replace("/", "-")
    return (
        lake_root
        / "gold"
        / "hyperliquid"
        / "training"
        / symbol
        / f"{symbol}-training-{date}.parquet"
    )


def parse_symbol_spec(value: str) -> tuple[str, ...]:
    symbols = tuple(_normalize_symbol(item) for item in _split_csv(value))
    if not symbols:
        raise ValueError("at least one coin is required")
    return tuple(dict.fromkeys(symbols))


def parse_date_spec(value: str) -> tuple[str, ...]:
    dates: list[str] = []
    for token in _split_csv(value):
        if ".." in token:
            dates.extend(_expand_date_range(token))
        else:
            dates.append(_validate_date(token))
    if not dates:
        raise ValueError("at least one date is required")
    return tuple(dict.fromkeys(dates))


def parse_threshold_grid(value: str) -> tuple[float, ...]:
    """Parse a comma list or inclusive start:end:step threshold range."""
    token = value.strip()
    if not token:
        raise ValueError("threshold grid cannot be empty")
    if ":" in token and "," not in token:
        parts = token.split(":")
        if len(parts) != 3:
            raise ValueError("threshold range must use start:end:step")
        start, end, step = (float(part) for part in parts)
        if step <= 0.0:
            raise ValueError("threshold step must be positive")
        values: list[float] = []
        current = start
        while current <= end + (step / 2.0):
            values.append(round(current, 10))
            current += step
    else:
        values = [float(item) for item in _split_csv(token)]
    if not values:
        raise ValueError("threshold grid cannot be empty")
    if any(value < 0.0 or value > 1.0 for value in values):
        raise ValueError("threshold grid values must be in [0, 1]")
    return tuple(dict.fromkeys(values))


def resolve_training_partitions(
    lake_root: Path,
    *,
    coins: tuple[str, ...],
    dates: tuple[str, ...],
    allow_missing: bool = False,
) -> tuple[TrainingPartition, ...]:
    partitions = requested_training_partitions(lake_root, coins=coins, dates=dates)
    existing, missing = split_existing_missing_partitions(partitions)
    if missing and not allow_missing:
        available = ", ".join(partition.label for partition in existing) or "(none)"
        missing_labels = ", ".join(partition.label for partition in missing[:8])
        if len(missing) > 8:
            missing_labels += f", ... (+{len(missing) - 8} more)"
        message = (
            f"missing {len(missing)} local Hyperliquid training partition(s): "
            f"{missing_labels}. Available requested partitions: {available}. "
            "Backfill the missing dates first, or pass --allow-missing-partitions "
            "to train only on files already present."
        )
        raise FileNotFoundError(message)
    if not existing:
        raise FileNotFoundError("no requested Hyperliquid training partitions exist locally")
    return existing


def requested_training_partitions(
    lake_root: Path,
    *,
    coins: tuple[str, ...],
    dates: tuple[str, ...],
) -> tuple[TrainingPartition, ...]:
    return tuple(
        TrainingPartition(
            coin=coin,
            date=date,
            path=training_path(lake_root, coin, date),
        )
        for coin in coins
        for date in dates
    )


def split_existing_missing_partitions(
    partitions: tuple[TrainingPartition, ...],
) -> tuple[tuple[TrainingPartition, ...], tuple[TrainingPartition, ...]]:
    existing = tuple(partition for partition in partitions if partition.path.exists())
    missing = tuple(partition for partition in partitions if not partition.path.exists())
    return existing, missing


def dataset_label(partitions: tuple[TrainingPartition, ...]) -> str:
    coins = "-".join(dict.fromkeys(partition.coin for partition in partitions))
    dates = "-".join(dict.fromkeys(partition.date for partition in partitions))
    return f"{coins}_{dates}"


def load_training_frame(path: Path, *, horizon: str, max_rows: int = 0) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    label_col = f"toxic_{horizon}"
    markout_col = f"markout_bps_{horizon}"
    requested_columns = [
        "ts_ms",
        "px",
        "sz",
        "maker_side",
        "fee_bps",
        label_col,
        markout_col,
        "l2_mid",
        "l2_spread_bps",
        "l2_microprice",
        "l2_top_imbalance",
        *OFI_COLUMNS,
        "asset_basis_bps",
        "asset_funding",
        "asset_open_interest",
        "asset_premium",
    ]
    available_columns = set(pq.read_schema(path).names)
    columns = [column for column in requested_columns if column in available_columns]
    frame = pq.read_table(path, columns=columns).to_pandas()
    if max_rows > 0 and len(frame) > max_rows:
        frame = frame.sort_values("ts_ms").iloc[:max_rows].copy()
    return prepare_training_frame(frame, horizon=horizon)


def load_training_panel(
    partitions: tuple[TrainingPartition, ...],
    *,
    horizon: str,
    max_rows: int = 0,
    workers: int = 4,
) -> pd.DataFrame:
    """Load partitions concurrently; parquet decode releases the GIL."""
    if not partitions:
        raise ValueError("no training partitions were provided")

    def load(partition: TrainingPartition) -> pd.DataFrame:
        frame = load_training_frame(partition.path, horizon=horizon, max_rows=0)
        frame["partition_coin"] = partition.coin
        frame["partition_date"] = partition.date
        frame["partition_path"] = str(partition.path)
        return frame

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(partitions)))) as pool:
        frames = list(pool.map(load, partitions))
    panel = pd.concat(frames, ignore_index=True).sort_values("ts_ms").reset_index(drop=True)
    if max_rows > 0 and len(panel) > max_rows:
        panel = panel.iloc[:max_rows].copy()
    return panel


def partition_row_counts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if "partition_coin" not in frame.columns or "partition_date" not in frame.columns:
        return []
    counts = (
        frame.groupby(["partition_coin", "partition_date"], sort=True)
        .size()
        .reset_index(name="rows")
    )
    return [
        {
            "coin": str(row.partition_coin),
            "date": str(row.partition_date),
            "rows": int(row.rows),
        }
        for row in counts.itertuples(index=False)
    ]


def prepare_training_frame(frame: pd.DataFrame, *, horizon: str) -> pd.DataFrame:
    label_col = f"toxic_{horizon}"
    markout_col = f"markout_bps_{horizon}"
    frame = frame.copy()
    if "fee_bps" not in frame.columns:
        frame["fee_bps"] = 0.0
    else:
        frame["fee_bps"] = frame["fee_bps"].fillna(0.0)
    for column in OFI_COLUMNS:
        if column not in frame.columns:
            frame[column] = 0.0
        else:
            frame[column] = frame[column].fillna(0.0)
    frame["l2_microprice_offset_bps"] = (
        (frame["l2_microprice"] - frame["l2_mid"]) / frame["l2_mid"] * 10_000.0
    )
    frame["fill_vs_mid_bps"] = (
        (frame["px"] - frame["l2_mid"]) / frame["l2_mid"] * 10_000.0 * frame["maker_side"]
    )
    needed = ["ts_ms", label_col, markout_col, *FEATURE_COLUMNS]
    numeric_needed = ["ts_ms", markout_col, *FEATURE_COLUMNS]
    frame[numeric_needed] = frame[numeric_needed].apply(pd.to_numeric, errors="coerce")
    frame[numeric_needed] = frame[numeric_needed].where(
        np.isfinite(frame[numeric_needed]),
        np.nan,
    )
    frame = frame.dropna(subset=needed)
    frame[label_col] = frame[label_col].astype(bool)
    return frame.sort_values("ts_ms").reset_index(drop=True)


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _normalize_symbol(value: str) -> str:
    return value.strip().upper().replace("/", "-")


def _validate_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid YYYYMMDD date: {value}") from exc
    return value


def _expand_date_range(value: str) -> list[str]:
    start_text, end_text = value.split("..", 1)
    start = datetime.strptime(_validate_date(start_text), "%Y%m%d").date()
    end = datetime.strptime(_validate_date(end_text), "%Y%m%d").date()
    if end < start:
        raise ValueError("date range end must be >= start")
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates
