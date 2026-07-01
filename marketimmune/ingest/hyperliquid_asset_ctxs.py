"""Hyperliquid asset-contexts ingestion — funding / open-interest / basis signals.

The archive stores per-asset contexts at ``s3://hyperliquid-archive/asset_ctxs/<date>.csv.lz4``.
The fields mirror the API ``metaAndAssetCtxs`` asset contexts: ``funding``,
``openInterest``, ``oraclePx``, ``markPx``, ``midPx``, ``premium`` (plus ``prevDayPx`` /
``dayNtlVlm`` we don't need here).

**Honest note on schema:** Hyperliquid does not publish the exact *CSV header* of the
archive files, so the column names are configurable (:class:`AssetCtxColumns`, defaulting
to the documented API camelCase). Confirm them against a real file and override if needed.
The derived derivatives-state signals — perp-oracle basis, funding rate-of-change, OI
delta — are pure and schema-independent. Network (boto3) + codec (lz4) stay injected, as
in :mod:`marketimmune.ingest.hyperliquid_archive`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from marketimmune.ingest.hyperliquid_archive import BPS, asset_ctxs_key


@dataclass(frozen=True, slots=True)
class AssetCtx:
    """One asset's context row (a single coin at one archive timestamp)."""

    coin: str
    funding: float
    open_interest: float
    oracle_px: float
    mark_px: float
    mid_px: float
    premium: float
    ts_ms: int | None = None

    @property
    def basis_bps(self) -> float:
        """Perp-oracle basis in bps: ``(mark - oracle) / oracle * 1e4``."""
        if self.oracle_px <= 0.0:
            raise ValueError("oracle_px must be positive")
        return (self.mark_px - self.oracle_px) / self.oracle_px * BPS


@dataclass(frozen=True, slots=True)
class AssetCtxColumns:
    """CSV header names mapped to :class:`AssetCtx` fields (defaults = API camelCase)."""

    coin: str = "coin"
    funding: str = "funding"
    open_interest: str = "openInterest"
    oracle_px: str = "oraclePx"
    mark_px: str = "markPx"
    mid_px: str = "midPx"
    premium: str = "premium"
    time: str = "time"


_DEFAULT_COLUMNS = AssetCtxColumns()
_ARCHIVE_COLUMNS = AssetCtxColumns(
    open_interest="open_interest",
    oracle_px="oracle_px",
    mark_px="mark_px",
    mid_px="mid_px",
)


def parse_asset_ctx_row(
    row: Mapping[str, Any], columns: AssetCtxColumns = _DEFAULT_COLUMNS
) -> AssetCtx:
    """Parse one CSV row (string values) into an :class:`AssetCtx`."""
    mark_px = _required_float(row, columns.mark_px)
    return AssetCtx(
        coin=str(row[columns.coin]),
        funding=_required_float(row, columns.funding),
        open_interest=_required_float(row, columns.open_interest),
        oracle_px=_required_float(row, columns.oracle_px),
        mark_px=mark_px,
        mid_px=_optional_float(row, columns.mid_px, mark_px),
        premium=_optional_float(row, columns.premium, 0.0),
        ts_ms=_optional_ts_ms(row.get(columns.time)),
    )


def parse_asset_ctxs_csv(
    text: str, columns: AssetCtxColumns = _DEFAULT_COLUMNS
) -> list[AssetCtx]:
    """Parse a full ``asset_ctxs`` CSV (header + rows) into asset contexts."""
    reader = csv.DictReader(io.StringIO(text))
    resolved_columns = _resolve_columns(reader.fieldnames or [], columns)
    return [parse_asset_ctx_row(row, resolved_columns) for row in reader]


def _resolve_columns(fieldnames: Sequence[str], columns: AssetCtxColumns) -> AssetCtxColumns:
    """Use archive snake_case columns when the caller did not override names."""
    if columns != _DEFAULT_COLUMNS:
        return columns
    fields = set(fieldnames)
    if {"open_interest", "oracle_px", "mark_px"}.issubset(fields):
        return _ARCHIVE_COLUMNS
    return columns


def _required_float(row: Mapping[str, Any], column: str) -> float:
    value = row[column]
    if value is None or value == "":
        raise ValueError(f"{column} is required")
    return float(value)


def _optional_float(row: Mapping[str, Any], column: str, fallback: float) -> float:
    value = row.get(column)
    if value is None or value == "":
        return fallback
    return float(value)


def _optional_ts_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    text = str(value)
    if text.isdigit():
        return int(text)
    normalized = text.replace("Z", "+00:00")
    if "." in normalized:
        prefix, suffix = normalized.split(".", 1)
        fraction, _, zone = suffix.partition("+")
        normalized = f"{prefix}.{fraction[:6]}+{zone}" if zone else f"{prefix}.{fraction[:6]}"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def funding_rate_of_change(funding: Sequence[float]) -> list[float]:
    """First difference of an ordered funding series (0.0 for the first point)."""
    out = [0.0]
    for i in range(1, len(funding)):
        out.append(funding[i] - funding[i - 1])
    return out


def open_interest_delta(open_interest: Sequence[float]) -> list[float]:
    """First difference of an ordered open-interest series (0.0 for the first point)."""
    out = [0.0]
    for i in range(1, len(open_interest)):
        out.append(open_interest[i] - open_interest[i - 1])
    return out


def load_asset_ctxs(
    fetch: Callable[[str], bytes],
    decompress: Callable[[bytes], bytes],
    date: str,
    columns: AssetCtxColumns = _DEFAULT_COLUMNS,
) -> list[AssetCtx]:
    """Fetch + decompress + parse one ``asset_ctxs`` file (injected I/O)."""
    raw = fetch(asset_ctxs_key(date))
    return parse_asset_ctxs_csv(decompress(raw).decode("utf-8"), columns)
