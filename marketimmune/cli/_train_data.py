"""Gold training partitions for the markout trainers: discovery, leakage gate and loading."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.features.training_rows import FEATURE_SETS, HYPERLIQUID_OFI_COLUMNS
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.utils import parse_date_spec as parse_date_spec
from marketimmune.utils import parse_symbol_spec as parse_symbol_spec

DEFAULT_FEATURE_SET = "l0"
# One shared list object: the trainers import it and ``use_feature_set`` swaps its
# contents in place, so every module sees the same columns.
FEATURE_COLUMNS = list(FEATURE_SETS[DEFAULT_FEATURE_SET])
# Not features: the out-of-fold export uses them to align rows across rungs and to
# split results by regime (a Binance move, a forced liquidation).
OOF_EXTRA_COLUMNS = ("oid", "tid", "liquidation", "cex_ret_1000ms_bps", "forced_same_notional_60000ms", "forced_opp_notional_60000ms")
# A missing or null fee / OFI feature counts as 0 (v2 Gold partitions may lack fees).
ZERO_FILL_COLUMNS = ("fee_bps", "maker_fee_bps", *HYPERLIQUID_OFI_COLUMNS)
_BASE_COLUMNS = ("ts_ms", "px", "sz", "maker_side", "l2_mid", "l2_microprice")


@dataclass(frozen=True, slots=True)
class TrainingPartition:
    """One local Gold training parquet."""

    coin: str
    date: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.coin}:{self.date}"


def use_feature_set(name: str) -> list[str]:
    """Select a ladder rung's columns (see ``FEATURE_SETS``)."""
    if name not in FEATURE_SETS:
        raise ValueError(f"unknown feature set {name!r}; choose from {sorted(FEATURE_SETS)}")
    FEATURE_COLUMNS[:] = FEATURE_SETS[name]
    return FEATURE_COLUMNS


def resolve_training_partitions(
    lake_root: Path,
    *,
    coins: tuple[str, ...],
    dates: tuple[str, ...],
) -> tuple[TrainingPartition, ...]:
    """Every requested (coin, date) partition; a missing one is an error."""
    layout = HyperliquidLakeLayout(lake_root)
    requested = [TrainingPartition(coin, date, layout.gold_training_path(coin, date)) for coin in coins for date in dates]
    missing = [partition.label for partition in requested if not partition.path.exists()]
    if missing:
        raise FileNotFoundError(f"missing {len(missing)} Gold training partition(s): {', '.join(missing[:8])}; build them first")
    return tuple(requested)


def partition_leakage_status(partitions: tuple[TrainingPartition, ...]) -> tuple[bool, list[dict[str, Any]]]:
    """True only when every partition has a passing no-look-ahead sidecar (fix B3) and keeps
    each row's ``feature_ts_ms``, which loading checks row by row (``check_feature_times``)."""
    details: list[dict[str, Any]] = []
    for partition in partitions:
        sidecar = partition.path.with_suffix(".leakage.json")
        entry: dict[str, Any] = {"coin": partition.coin, "date": partition.date}
        if "feature_ts_ms" not in pq.read_schema(partition.path).names:
            entry.update(passed=False, reason="no feature_ts_ms column: feature times cannot be checked")
        elif sidecar.exists():
            report = json.loads(sidecar.read_text(encoding="utf-8"))
            entry.update(
                passed=bool(report.get("passed")),
                n_checked=report.get("n_checked"),
                n_mismatched=report.get("n_mismatched"),
                n_dropped=report.get("n_dropped"),
            )
        else:
            entry.update(passed=False, reason="no leakage report")
        details.append(entry)
    return bool(details) and all(d["passed"] for d in details), details


def dataset_label(partitions: tuple[TrainingPartition, ...]) -> str:
    coins = "-".join(dict.fromkeys(partition.coin for partition in partitions))
    dates = "-".join(dict.fromkeys(partition.date for partition in partitions))
    return f"{coins}_{dates}"


def load_training_panel(
    partitions: tuple[TrainingPartition, ...],
    *,
    horizon: str,
    workers: int = 4,
) -> pd.DataFrame:
    """Prepared rows of every partition, sorted by time.

    Partitions load concurrently: parquet decoding releases the GIL.
    """
    assert partitions, "no training partitions were provided"

    def load(partition: TrainingPartition) -> pd.DataFrame:
        frame = _read_partition(partition.path, horizon=horizon)
        frame["partition_coin"] = partition.coin
        frame["partition_date"] = partition.date
        return frame

    with ThreadPoolExecutor(max_workers=min(workers, len(partitions))) as pool:
        frames = list(pool.map(load, partitions))
    # NOTE: the second sort must stay a plain (unstable) sort_values after the per-partition
    # one: row order within a millisecond feeds CatBoost, so it is part of the result.
    return pd.concat(frames, ignore_index=True).sort_values("ts_ms").reset_index(drop=True)


def partition_row_counts(frame: pd.DataFrame) -> list[dict[str, Any]]:
    counts = frame.groupby(["partition_coin", "partition_date"], sort=True).size()
    return [{"coin": str(coin), "date": str(date), "rows": int(rows)} for (coin, date), rows in counts.items()]


def prepare_training_frame(frame: pd.DataFrame, *, horizon: str) -> pd.DataFrame:
    """Zero-fill fees/OFI, derive the bps features, drop rows with a missing or non-finite
    feature, label or markout, and sort by time. Mutates and returns ``frame``'s rows."""
    label_col, markout_col = f"toxic_{horizon}", f"markout_bps_{horizon}"
    for column in (c for c in ZERO_FILL_COLUMNS if c in FEATURE_COLUMNS):
        frame[column] = frame[column].fillna(0.0) if column in frame.columns else 0.0
    mid = frame["l2_mid"]
    frame["l2_microprice_offset_bps"] = (frame["l2_microprice"] - mid) / mid * 10_000.0
    frame["fill_vs_mid_bps"] = (frame["px"] - mid) / mid * 10_000.0 * frame["maker_side"]
    keep = frame[label_col].notna().to_numpy()
    for column in dict.fromkeys(("ts_ms", markout_col, *FEATURE_COLUMNS)):
        if frame[column].dtype == object:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        keep = keep & np.isfinite(frame[column].to_numpy(dtype=np.float64, na_value=np.nan))
    frame = frame.loc[keep].copy()
    frame[label_col] = frame[label_col].astype(bool)
    return frame.sort_values("ts_ms").reset_index(drop=True)


def check_feature_times(frame: pd.DataFrame, path: Path) -> None:
    """Every row's features were known strictly before its fill (``feature_ts_ms < ts_ms``).

    The row builder checks this when it writes Gold; checking again here stops a stale,
    rebuilt or external Gold file from training a model that then reports itself safe.
    """
    if "feature_ts_ms" not in frame.columns:
        return
    feature_ts = frame["feature_ts_ms"].to_numpy(dtype=np.float64, na_value=np.nan)
    bad = ~(feature_ts < frame["ts_ms"].to_numpy(dtype=np.float64))
    if bad.any():
        raise ValueError(f"{path}: {int(bad.sum())} row(s) have features stamped at or after their fill (or no feature time)")


def _read_partition(path: Path, *, horizon: str) -> pd.DataFrame:
    """Only the columns the trainers use: features, label, markout, baseline, OOF keys and the
    feature time, which is checked against the fill time."""
    wanted = (*_BASE_COLUMNS, "feature_ts_ms", f"toxic_{horizon}", f"markout_bps_{horizon}", *FEATURE_COLUMNS, *OOF_EXTRA_COLUMNS)
    available = set(pq.read_schema(path).names)
    columns = [column for column in dict.fromkeys(wanted) if column in available]
    frame = pq.read_table(path, columns=columns).to_pandas()
    check_feature_times(frame, path)
    return prepare_training_frame(frame, horizon=horizon)
