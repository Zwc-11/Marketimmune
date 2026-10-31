"""Parquet layout and row shapes of the Hyperliquid lake (Bronze, Silver, Gold).

* Bronze fills: one row per leg, parsed fields plus the raw JSON for audit.
* Silver fills: one row per match, both legs merged, maker and taker wallets, fees and
  start positions promoted out of the raw JSON.
* Silver L2: top of book plus the top ``L2_DEPTH`` levels per side.
* Gold markout: horizon labels flattened into model-ready columns.
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
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot
from marketimmune.sources.hyperliquid_node_fills import MatchFill, NodeFill

L2_DEPTH = 5


def _coin_dir(coin: str) -> str:
    return coin.strip().upper().replace("/", "-")


@dataclass(frozen=True, slots=True)
class LakeWrite:
    path: Path
    rows: int


@dataclass(frozen=True, slots=True)
class HyperliquidLakeLayout:
    """Where each Hyperliquid artifact lives under the lake root."""

    root: Path

    def bronze_fills_path(self, coin: str, date: str) -> Path:
        return self._partition("bronze", "fills", coin, date)

    def silver_fills_path(self, coin: str, date: str) -> Path:
        return self._partition("silver", "fills", coin, date)

    def silver_order_events_path(self, coin: str, date: str) -> Path:
        """Forced-liquidation fills and unfilled IOCs (Albers order statuses)."""
        return self._partition("silver", "order_events", coin, date)

    def silver_l2_book_path(self, coin: str, date: str) -> Path:
        return self._partition("silver", "l2_book", coin, date)

    def silver_asset_ctxs_path(self, date: str) -> Path:
        return self.root / "silver" / "hyperliquid" / "asset_ctxs" / f"asset-ctxs-{date}.parquet"

    def gold_markout_path(self, coin: str, date: str) -> Path:
        return self._partition("gold", "markout", coin, date, "markout-")

    def gold_training_path(self, coin: str, date: str) -> Path:
        return self._partition("gold", "training", coin, date, "training-")

    def _partition(self, layer: str, table: str, coin: str, date: str, tag: str = "") -> Path:
        symbol = _coin_dir(coin)
        return self.root / layer / "hyperliquid" / table / symbol / f"{symbol}-{tag}{date}.parquet"


def write_parquet_records(path: Path, records: Sequence[Mapping[str, Any]]) -> LakeWrite:
    """Write non-empty records to a zstd parquet file; the first record's keys name the columns."""
    assert records, f"refusing to write an empty parquet artifact: {path}"
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path, compression="zstd")
    return LakeWrite(path=path, rows=len(records))


def read_parquet_records(path: Path, columns: Sequence[str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = pq.read_table(path, columns=None if columns is None else list(columns)).to_pylist()
    return rows


def read_parquet_window(path: Path, *, limit: int, latest: bool = True, order_by: str = "ts_ms") -> list[dict[str, Any]]:
    """The newest (or oldest) ``limit`` rows by ``order_by``; ``limit <= 0`` reads all, sorted.

    Sorts and slices the Arrow table, so a 200K-row day costs one columnar sort, not 200K dicts.
    """
    table = pq.read_table(path).sort_by(order_by)
    if 0 < limit < table.num_rows:
        table = table.slice(table.num_rows - limit if latest else 0, limit)
    rows: list[dict[str, Any]] = table.to_pylist()
    return rows


def bronze_fill_record(fill: NodeFill) -> dict[str, Any]:
    return fill.to_dict() | {"raw_json": json.dumps(fill.raw, sort_keys=True)}


def silver_l2_book_record(snapshot: BookSnapshot) -> dict[str, Any]:
    """Top of book, its microstructure features and ``bid/ask_{px,sz,n}_1..L2_DEPTH`` (``None`` past the book's depth)."""
    features = snapshot.features()
    bid, ask = snapshot.bids[0], snapshot.asks[0]
    record: dict[str, Any] = {
        "coin": snapshot.coin,
        "ts_ms": snapshot.ts_ms,
        "bid_px": bid.px,
        "bid_sz": bid.sz,
        "bid_n": bid.n,
        "ask_px": ask.px,
        "ask_sz": ask.sz,
        "ask_n": ask.n,
        **features,
    }
    for name, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
        for i in range(L2_DEPTH):
            px, sz, n = levels[i] if i < len(levels) else (None, None, None)
            record[f"{name}_px_{i + 1}"] = px
            record[f"{name}_sz_{i + 1}"] = sz
            record[f"{name}_n_{i + 1}"] = n
    return record


def silver_asset_ctx_record(ctx: AssetCtx) -> dict[str, Any]:
    return {
        "coin": ctx.coin,
        "funding": ctx.funding,
        "open_interest": ctx.open_interest,
        "oracle_px": ctx.oracle_px,
        "mark_px": ctx.mark_px,
        "mid_px": ctx.mid_px,
        "premium": ctx.premium,
        "basis_bps": ctx.basis_bps,
        "ts_ms": ctx.ts_ms,
    }


def gold_markout_record(row: MarkoutGoldRow) -> dict[str, Any]:
    """Flatten the per-horizon dicts into ``markout_bps_<h>``, ``toxic_<h>`` and ``markout_px_bps_<h>`` columns."""
    return {
        "coin": row.coin,
        "ts_ms": row.ts_ms,
        "px": row.px,
        "sz": row.sz,
        "side": row.side,
        "crossed": row.crossed,
        "maker_side": row.maker_side,
        "oid": row.oid,
        "tid": row.tid,
        **{f"markout_bps_{h}": value for h, value in row.markout_bps.items()},
        **{f"toxic_{h}": value for h, value in row.toxic.items()},
        "mid_before": row.mid_before,
        **{f"markout_px_bps_{h}": value for h, value in row.markout_px_bps.items()},
        "maker_user": row.maker_user,
        "taker_user": row.taker_user,
        "maker_fee_bps": row.maker_fee_bps,
        "taker_fee_bps": row.taker_fee_bps,
        "priority_gas": row.priority_gas,
        "liquidation": row.liquidation,
    }


def write_bronze_fills(layout: HyperliquidLakeLayout, *, coin: str, date: str, fills: Sequence[NodeFill]) -> LakeWrite:
    return write_parquet_records(layout.bronze_fills_path(coin, date), [bronze_fill_record(fill) for fill in fills])


def write_silver_fills(layout: HyperliquidLakeLayout, *, coin: str, date: str, fills: Sequence[MatchFill]) -> LakeWrite:
    return write_parquet_records(layout.silver_fills_path(coin, date), [match.to_dict() for match in fills])


def write_silver_l2_book(layout: HyperliquidLakeLayout, *, coin: str, date: str, snapshots: Sequence[BookSnapshot]) -> LakeWrite:
    return write_parquet_records(layout.silver_l2_book_path(coin, date), [silver_l2_book_record(s) for s in snapshots])


def write_silver_asset_ctxs(layout: HyperliquidLakeLayout, *, date: str, contexts: Sequence[AssetCtx]) -> LakeWrite:
    return write_parquet_records(layout.silver_asset_ctxs_path(date), [silver_asset_ctx_record(ctx) for ctx in contexts])


def write_gold_markout(layout: HyperliquidLakeLayout, *, coin: str, date: str, rows: Sequence[MarkoutGoldRow]) -> LakeWrite:
    return write_parquet_records(layout.gold_markout_path(coin, date), [gold_markout_record(row) for row in rows])


def leakage_report_path(layout: HyperliquidLakeLayout, coin: str, date: str) -> Path:
    """``<training partition>.leakage.json``: the no-look-ahead check for that partition."""
    return layout.gold_training_path(coin, date).with_suffix(".leakage.json")


def write_leakage_report(layout: HyperliquidLakeLayout, *, coin: str, date: str, report: Mapping[str, Any]) -> Path:
    path = leakage_report_path(layout, coin, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(report), indent=2, default=str) + "\n", encoding="utf-8")
    return path


def write_gold_training_rows(layout: HyperliquidLakeLayout, *, coin: str, date: str, rows: Sequence[Mapping[str, Any]]) -> LakeWrite:
    return write_parquet_records(layout.gold_training_path(coin, date), rows)
