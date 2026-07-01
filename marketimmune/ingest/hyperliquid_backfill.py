"""Hyperliquid daily backfill orchestration.

This module glues together the pure parser/label/writer pieces without owning
network access. A real requester-pays runner can provide S3 fetch callables and
object listings; tests can provide local bytes. The coordinator only decides the
order of operations:

1. Load L2 book snapshots for explicit hourly archive keys.
2. Load the daily asset-context CSV.
3. Load explicit node-fill objects.
4. Persist Silver book/context rows, Bronze/Silver fills, and Gold markout rows.

It intentionally does not infer the ``node_fills_by_block`` partition scheme. That
still needs confirmation against a real requester-pays listing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from marketimmune.features.hyperliquid_features import build_hyperliquid_training_rows
from marketimmune.ingest.hyperliquid_archive import BookSnapshot, HyperliquidArchive
from marketimmune.ingest.hyperliquid_asset_ctxs import AssetCtx, load_asset_ctxs
from marketimmune.ingest.hyperliquid_fills import HyperliquidNodeFills, NodeFill
from marketimmune.ingest.hyperliquid_gold import (
    DEFAULT_MARKOUT_CONFIG,
    MarkoutGoldRow,
    build_markout_gold_rows,
)
from marketimmune.ingest.hyperliquid_lake import (
    HyperliquidLakeLayout,
    LakeWrite,
    gold_markout_record,
    silver_asset_ctx_record,
    silver_l2_book_record,
    write_bronze_fills,
    write_gold_markout,
    write_gold_training_rows,
    write_silver_asset_ctxs,
    write_silver_fills,
    write_silver_l2_book,
)
from marketimmune.labels.markout import MarkoutConfig


@dataclass(frozen=True, slots=True)
class HyperliquidBackfillResult:
    """Counts and write locations from one daily Hyperliquid backfill."""

    coin: str
    date: str
    book_snapshots: int
    asset_contexts: int
    fills: int
    gold_rows: int
    training_rows: int
    writes: tuple[LakeWrite, ...]


@dataclass(frozen=True, slots=True)
class HyperliquidDailyBackfill:
    """Coordinates one coin/day backfill using injected I/O adapters."""

    layout: HyperliquidLakeLayout
    archive: HyperliquidArchive
    node_fills: HyperliquidNodeFills
    markout_config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG

    def run(
        self,
        *,
        coin: str,
        date: str,
        hours: Sequence[int],
        fill_suffixes: Sequence[str],
        include_asset_ctxs: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> HyperliquidBackfillResult:
        """Load explicit archive objects and write non-empty lake artifacts."""
        emit = progress or _no_progress
        snapshots = self._load_book_snapshots(coin=coin, date=date, hours=hours)
        emit(f"loaded {len(snapshots):,} L2 snapshots")
        contexts = self._load_asset_ctxs(date) if include_asset_ctxs else []
        emit(f"loaded {len(contexts):,} asset-context rows")
        fills = self._load_fills(fill_suffixes)
        emit(f"loaded {len(fills):,} raw fills")
        coin_fills = [fill for fill in fills if fill.coin == coin]
        emit(f"filtered {len(coin_fills):,} {coin} fills")
        gold_rows = build_markout_gold_rows(
            coin_fills,
            snapshots,
            self.markout_config,
            coin=coin,
        )
        emit(f"built {len(gold_rows):,} Gold markout rows")
        training_rows = build_hyperliquid_training_rows(
            [gold_markout_record(row) for row in gold_rows],
            [silver_l2_book_record(snapshot) for snapshot in snapshots],
            [silver_asset_ctx_record(ctx) for ctx in contexts],
        )
        emit(f"built {len(training_rows):,} Gold training rows")
        writes = self._write_outputs(
            coin=coin,
            date=date,
            snapshots=snapshots,
            contexts=contexts,
            fills=coin_fills,
            gold_rows=gold_rows,
            training_rows=training_rows,
        )
        emit(f"wrote {len(writes):,} parquet artifacts")
        return HyperliquidBackfillResult(
            coin=coin,
            date=date,
            book_snapshots=len(snapshots),
            asset_contexts=len(contexts),
            fills=len(coin_fills),
            gold_rows=len(gold_rows),
            training_rows=len(training_rows),
            writes=writes,
        )

    def _load_book_snapshots(
        self,
        *,
        coin: str,
        date: str,
        hours: Sequence[int],
    ) -> list[BookSnapshot]:
        snapshots: list[BookSnapshot] = []
        for hour in hours:
            snapshots.extend(self.archive.load_l2_book(coin, date, hour))
        return snapshots

    def _load_asset_ctxs(self, date: str) -> list[AssetCtx]:
        return load_asset_ctxs(self.archive.fetch, self.archive.decompress, date)

    def _load_fills(self, suffixes: Sequence[str]) -> list[NodeFill]:
        fills: list[NodeFill] = []
        for suffix in suffixes:
            fills.extend(self.node_fills.load_by_block_suffix(suffix))
        return fills

    def _write_outputs(
        self,
        *,
        coin: str,
        date: str,
        snapshots: Sequence[BookSnapshot],
        contexts: Sequence[AssetCtx],
        fills: Sequence[NodeFill],
        gold_rows: Sequence[MarkoutGoldRow],
        training_rows: Sequence[dict[str, object]],
    ) -> tuple[LakeWrite, ...]:
        writes: list[LakeWrite] = []
        if snapshots:
            writes.append(
                write_silver_l2_book(
                    self.layout,
                    coin=coin,
                    date=date,
                    snapshots=snapshots,
                )
            )
        if contexts:
            writes.append(write_silver_asset_ctxs(self.layout, date=date, contexts=contexts))
        if fills:
            writes.append(write_bronze_fills(self.layout, coin=coin, date=date, fills=fills))
            writes.append(write_silver_fills(self.layout, coin=coin, date=date, fills=fills))
        if gold_rows:
            writes.append(write_gold_markout(self.layout, coin=coin, date=date, rows=gold_rows))
        if training_rows:
            writes.append(
                write_gold_training_rows(
                    self.layout,
                    coin=coin,
                    date=date,
                    rows=training_rows,
                )
            )
        return tuple(writes)


def _no_progress(_message: str) -> None:
    return None
