"""Parquet lake writers for Hyperliquid Bronze/Silver/Gold artifacts.

The parser modules stay pure and schema-focused. This module owns only filesystem
layout and Parquet serialization for Hyperliquid-derived records:

* Bronze fills: parsed records plus raw JSON payload for audit/debug, one row per leg.
* Silver fills: one row per match (both legs merged, fix B2) with maker and taker
  wallets, fees and start positions promoted out of raw JSON (fix L3).
* Silver L2: the top ``L2_DEPTH`` levels per side (fix L4), not only the touch.
* Gold markout: flattened horizon label columns ready for model training.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.lake.gold import MarkoutGoldRow
from marketimmune.sources.hyperliquid_asset_ctxs import AssetCtx
from marketimmune.sources.hyperliquid_info_api import Candle
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot
from marketimmune.sources.hyperliquid_node_fills import MatchFill, NodeFill, pair_fill_legs

L2_DEPTH = 5

# pyarrow ships stubs in some releases and not others; route calls through Any so
# strict mypy is stable across versions without version-specific ignores.
_parquet: Any = pq


def _coin_dir(coin: str) -> str:
    return coin.strip().upper().replace("/", "-")


@dataclass(frozen=True, slots=True)
class LakeWrite:
    """Result of one parquet write."""

    path: Path
    rows: int


@dataclass(frozen=True, slots=True)
class HyperliquidLakeLayout:
    """File layout for Hyperliquid parquet artifacts."""

    root: Path

    def bronze_fills_path(self, coin: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return self.root / "bronze" / "hyperliquid" / "fills" / symbol / f"{symbol}-{date}.parquet"

    def silver_fills_path(self, coin: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return self.root / "silver" / "hyperliquid" / "fills" / symbol / f"{symbol}-{date}.parquet"

    def silver_order_events_path(self, coin: str, date: str) -> Path:
        """Forced-liquidation fills and unfilled IOCs (Albers order statuses)."""
        symbol = _coin_dir(coin)
        return (
            self.root / "silver" / "hyperliquid" / "order_events" / symbol
            / f"{symbol}-{date}.parquet"
        )

    def silver_l2_book_path(self, coin: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return (
            self.root
            / "silver"
            / "hyperliquid"
            / "l2_book"
            / symbol
            / f"{symbol}-{date}.parquet"
        )

    def silver_asset_ctxs_path(self, date: str) -> Path:
        return self.root / "silver" / "hyperliquid" / "asset_ctxs" / f"asset-ctxs-{date}.parquet"

    def silver_candles_path(self, coin: str, interval: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return (
            self.root
            / "silver"
            / "hyperliquid"
            / "candles"
            / interval
            / symbol
            / f"{symbol}-{interval}-{date}.parquet"
        )

    def gold_markout_path(self, coin: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return (
            self.root
            / "gold"
            / "hyperliquid"
            / "markout"
            / symbol
            / f"{symbol}-markout-{date}.parquet"
        )

    def gold_training_path(self, coin: str, date: str) -> Path:
        symbol = _coin_dir(coin)
        return (
            self.root
            / "gold"
            / "hyperliquid"
            / "training"
            / symbol
            / f"{symbol}-training-{date}.parquet"
        )


def write_parquet_records(path: Path, records: Sequence[Mapping[str, Any]]) -> LakeWrite:
    """Write non-empty records to a zstd-compressed parquet file."""
    if not records:
        raise ValueError("cannot write an empty Hyperliquid parquet artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([dict(record) for record in records])
    _write_table(path, table)
    return LakeWrite(path=path, rows=len(records))


def read_parquet_records(
    path: Path,
    columns: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Read a parquet artifact back into dictionaries.

    ``columns`` reads only those that exist in the file (the rest are skipped), so
    a wide Silver L2 day can be joined without building a 70-key dict per row.
    """
    if columns is None:
        table = _read_table(path)
    else:
        names = set(_parquet.read_schema(path).names)
        table = _parquet.read_table(path, columns=[c for c in columns if c in names])
    return [dict(record) for record in table.to_pylist()]


def read_parquet_window(
    path: Path,
    *,
    limit: int,
    latest: bool = True,
    order_by: str = "ts_ms",
) -> list[dict[str, Any]]:
    """Read only the newest (or oldest) ``limit`` rows as dictionaries.

    Sorting and slicing happen on the Arrow table, so a 200K-row day costs one
    columnar sort instead of 200K Python dicts. ``limit <= 0`` reads everything,
    sorted by ``order_by``.
    """
    table = _read_table(path)
    if table.num_rows == 0:
        return []
    table = table.sort_by(order_by)
    if 0 < limit < table.num_rows:
        offset = table.num_rows - limit if latest else 0
        table = table.slice(offset, limit)
    return [dict(record) for record in table.to_pylist()]


def _write_table(path: Path, table: pa.Table) -> None:
    _parquet.write_table(table, path, compression="zstd")


def _read_table(path: Path) -> pa.Table:
    table: pa.Table = _parquet.read_table(path)
    return table


def bronze_fill_record(fill: NodeFill) -> dict[str, Any]:
    """Bronze row: parsed fields plus raw JSON for auditability."""
    record = fill.to_dict()
    record["raw_json"] = json.dumps(dict(fill.raw or {}), sort_keys=True)
    return record


def silver_fill_record(fill: NodeFill) -> dict[str, Any]:
    """Silver row: conformed typed fields for joins and labels."""
    return {
        "coin": fill.coin,
        "ts_ms": fill.ts_ms,
        "px": fill.px,
        "sz": fill.sz,
        "notional": fill.notional,
        "side": fill.side,
        "crossed": fill.crossed,
        "maker_side": fill.maker_side,
        "fee": fill.fee,
        "fee_bps": fill.fee_bps,
        "fee_token": fill.fee_token,
        "oid": fill.oid,
        "tid": fill.tid,
        "hash": fill.trade_hash,
        "direction": fill.direction,
        "user": fill.user,
        "start_position": fill.start_position,
        "priority_gas": fill.priority_gas,
        "liquidation": fill.liquidation,
    }


def silver_match_record(match: MatchFill) -> dict[str, Any]:
    """Silver row: one match, maker and taker sides merged."""
    return match.to_dict()


def silver_l2_book_record(snapshot: BookSnapshot) -> dict[str, Any]:
    """Silver row: top-of-book microstructure features from one L2 snapshot."""
    features = snapshot.features()
    return {
        "coin": snapshot.coin,
        "ts_ms": snapshot.ts_ms,
        "bid_px": snapshot.bids[0].px,
        "bid_sz": snapshot.bids[0].sz,
        "bid_n": snapshot.bids[0].n,
        "ask_px": snapshot.asks[0].px,
        "ask_sz": snapshot.asks[0].sz,
        "ask_n": snapshot.asks[0].n,
        "mid": features["mid"],
        "spread_bps": features["spread_bps"],
        "microprice": features["microprice"],
        "top_imbalance": features["top_imbalance"],
        **_depth_columns(snapshot),
    }


def _depth_columns(snapshot: BookSnapshot, depth: int = L2_DEPTH) -> dict[str, Any]:
    """``bid_px_1..depth`` etc.; levels the snapshot lacks are ``None``."""
    out: dict[str, Any] = {}
    for name, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
        for i in range(depth):
            level = levels[i] if i < len(levels) else None
            out[f"{name}_px_{i + 1}"] = level.px if level else None
            out[f"{name}_sz_{i + 1}"] = level.sz if level else None
            out[f"{name}_n_{i + 1}"] = level.n if level else None
    return out


def silver_asset_ctx_record(ctx: AssetCtx) -> dict[str, Any]:
    """Silver row: derivatives-state signals from one asset-context record."""
    record: dict[str, Any] = {
        "coin": ctx.coin,
        "funding": ctx.funding,
        "open_interest": ctx.open_interest,
        "oracle_px": ctx.oracle_px,
        "mark_px": ctx.mark_px,
        "mid_px": ctx.mid_px,
        "premium": ctx.premium,
        "basis_bps": ctx.basis_bps,
    }
    if ctx.ts_ms is not None:
        record["ts_ms"] = ctx.ts_ms
    return record


def silver_candle_record(candle: Candle) -> dict[str, Any]:
    """Silver row: one recent public-API candle."""
    return candle.to_dict()


def gold_markout_record(row: MarkoutGoldRow) -> dict[str, Any]:
    """Gold row: flatten horizon dictionaries into model-friendly columns."""
    record = {
        "coin": row.coin,
        "ts_ms": row.ts_ms,
        "px": row.px,
        "sz": row.sz,
        "side": row.side,
        "crossed": row.crossed,
        "maker_side": row.maker_side,
        "oid": row.oid,
        "tid": row.tid,
    }
    for horizon, value in row.markout_bps.items():
        record[f"markout_bps_{horizon}"] = value
    for horizon, value in row.toxic.items():
        record[f"toxic_{horizon}"] = value
    record["mid_before"] = row.mid_before
    for horizon, value in row.markout_px_bps.items():
        record[f"markout_px_bps_{horizon}"] = value
    record["maker_user"] = row.maker_user
    record["taker_user"] = row.taker_user
    record["maker_fee_bps"] = row.maker_fee_bps
    record["taker_fee_bps"] = row.taker_fee_bps
    record["priority_gas"] = row.priority_gas
    record["liquidation"] = row.liquidation
    return record


def write_bronze_fills(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    fills: Sequence[NodeFill],
) -> LakeWrite:
    """Write parsed Bronze fill rows."""
    return write_parquet_records(
        layout.bronze_fills_path(coin, date),
        [bronze_fill_record(fill) for fill in fills],
    )


def write_silver_fills(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    fills: Sequence[NodeFill] | Sequence[MatchFill],
) -> LakeWrite:
    """Write Silver fill rows, one per match. ``NodeFill`` legs are paired first."""
    matches = [f for f in fills if isinstance(f, MatchFill)]
    legs = [f for f in fills if isinstance(f, NodeFill)]
    matches.extend(pair_fill_legs(legs))
    return write_parquet_records(
        layout.silver_fills_path(coin, date),
        [silver_match_record(match) for match in matches],
    )


def write_silver_l2_book(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    snapshots: Sequence[BookSnapshot],
) -> LakeWrite:
    """Write Silver top-of-book rows."""
    return write_parquet_records(
        layout.silver_l2_book_path(coin, date),
        [silver_l2_book_record(snapshot) for snapshot in snapshots],
    )


def write_silver_asset_ctxs(
    layout: HyperliquidLakeLayout,
    *,
    date: str,
    contexts: Sequence[AssetCtx],
) -> LakeWrite:
    """Write Silver asset-context rows."""
    return write_parquet_records(
        layout.silver_asset_ctxs_path(date),
        [silver_asset_ctx_record(ctx) for ctx in contexts],
    )


def write_silver_candles(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    interval: str,
    date: str,
    candles: Sequence[Candle],
) -> LakeWrite:
    """Write Silver candle rows from the public Info API."""
    return write_parquet_records(
        layout.silver_candles_path(coin, interval, date),
        [silver_candle_record(candle) for candle in candles],
    )


def write_gold_markout(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    rows: Sequence[MarkoutGoldRow],
) -> LakeWrite:
    """Write flattened Gold markout rows."""
    return write_parquet_records(
        layout.gold_markout_path(coin, date),
        [gold_markout_record(row) for row in rows],
    )


def leakage_report_path(layout: HyperliquidLakeLayout, coin: str, date: str) -> Path:
    """``<training partition>.leakage.json``: the no-look-ahead check for that partition."""
    return layout.gold_training_path(coin, date).with_suffix(".leakage.json")


def write_leakage_report(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    report: Mapping[str, Any],
) -> Path:
    path = leakage_report_path(layout, coin, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_gold_training_rows(
    layout: HyperliquidLakeLayout,
    *,
    coin: str,
    date: str,
    rows: Sequence[Mapping[str, Any]],
) -> LakeWrite:
    """Write model-ready Gold feature/label rows."""
    return write_parquet_records(layout.gold_training_path(coin, date), rows)
