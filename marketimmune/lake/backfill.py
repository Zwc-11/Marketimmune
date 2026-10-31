"""One coin-day from the requester-pays Hyperliquid buckets to Silver and Gold.

L2 snapshots for the given hours, the day's asset contexts and the coin's node fills land in
Silver; the paired matches get markout labels (Gold) and model features (Gold training) with
a no-look-ahead sidecar. Network access is the two injected ``key -> bytes`` fetchers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import lz4.frame

from marketimmune.features.training_rows import build_hyperliquid_training_rows, verify_training_rows_no_lookahead
from marketimmune.labels.markout import MarkoutConfig
from marketimmune.lake.gold import DEFAULT_MARKOUT_CONFIG, build_markout_gold_rows
from marketimmune.lake.tables import (
    HyperliquidLakeLayout,
    LakeWrite,
    gold_markout_record,
    silver_asset_ctx_record,
    silver_l2_book_record,
    write_bronze_fills,
    write_gold_training_rows,
    write_leakage_report,
    write_parquet_records,
    write_silver_fills,
)
from marketimmune.logger import init_logger
from marketimmune.sources.hyperliquid_asset_ctxs import asset_ctxs_key, parse_asset_ctxs_csv
from marketimmune.sources.hyperliquid_l2_archive import l2_book_key, parse_l2_book_ndjson
from marketimmune.sources.hyperliquid_node_fills import node_fills_key, pair_fill_legs, parse_node_fills

logger = init_logger(__name__)

Fetch = Callable[[str], bytes]


@dataclass(frozen=True, slots=True)
class HyperliquidBackfillResult:
    coin: str
    date: str
    book_snapshots: int
    asset_contexts: int
    fills: int
    gold_rows: int
    training_rows: int
    writes: tuple[LakeWrite, ...]


def parse_hours(values: Sequence[str]) -> tuple[int, ...]:
    """``["0-2", "2,5"]`` -> ``(0, 1, 2, 5)``: hours in [0, 23], sorted, without repeats."""
    hours: set[int] = set()
    for token in (t.strip() for value in values for t in value.split(",")):
        if token:
            start, _, end = token.partition("-")
            hours.update(range(int(start), int(end or start) + 1))
    assert hours and all(0 <= h <= 23 for h in hours), f"{values=}: need hours in [0, 23]"
    return tuple(sorted(hours))


def run_backfill(
    layout: HyperliquidLakeLayout,
    *,
    archive: Fetch,
    node: Fetch,
    coin: str,
    date: str,
    hours: Sequence[int],
    fill_hours: Sequence[int],
    include_asset_ctxs: bool = True,
    markout_config: MarkoutConfig = DEFAULT_MARKOUT_CONFIG,
) -> HyperliquidBackfillResult:
    """Fetch, parse and write one coin-day; empty artifacts are skipped, not written."""

    def read(fetch: Fetch, key: str) -> str:
        logger.info("fetch %s", key)
        text: str = lz4.frame.decompress(fetch(key)).decode()
        return text

    snapshots = [s for hour in hours for s in parse_l2_book_ndjson(read(archive, l2_book_key(coin, date, hour)))]
    contexts = parse_asset_ctxs_csv(read(archive, asset_ctxs_key(date))) if include_asset_ctxs else []
    legs = [leg for hour in fill_hours for leg in parse_node_fills(read(node, node_fills_key(date, hour)), coin)]
    matches = pair_fill_legs(legs)
    gold_rows = build_markout_gold_rows(matches, snapshots, markout_config, coin=coin)
    logger.info(
        "%s %s: %d L2 snapshots, %d asset contexts, %d legs -> %d matches -> %d Gold rows",
        coin,
        date,
        len(snapshots),
        len(contexts),
        len(legs),
        len(matches),
        len(gold_rows),
    )
    label_records = [gold_markout_record(row) for row in gold_rows]
    l2_records = [silver_l2_book_record(snapshot) for snapshot in snapshots]
    asset_records = [silver_asset_ctx_record(ctx) for ctx in contexts]
    writes: list[LakeWrite] = []
    if l2_records:
        writes.append(write_parquet_records(layout.silver_l2_book_path(coin, date), l2_records))
    if asset_records:
        writes.append(write_parquet_records(layout.silver_asset_ctxs_path(date), asset_records))
    if legs:
        writes.append(write_bronze_fills(layout, coin=coin, date=date, fills=legs))
        writes.append(write_silver_fills(layout, coin=coin, date=date, fills=matches))
    if label_records:
        writes.append(write_parquet_records(layout.gold_markout_path(coin, date), label_records))
    training_rows = build_hyperliquid_training_rows(label_records, l2_records, asset_records)
    if training_rows:
        writes.append(write_gold_training_rows(layout, coin=coin, date=date, rows=training_rows))
        leakage = verify_training_rows_no_lookahead(label_records, l2_records, asset_records)
        write_leakage_report(layout, coin=coin, date=date, report=leakage.to_dict())
        logger.info("%d training rows; no-look-ahead check passed=%s (%d checked)", len(training_rows), leakage.passed, leakage.n_checked)
    return HyperliquidBackfillResult(
        coin=coin,
        date=date,
        book_snapshots=len(snapshots),
        asset_contexts=len(contexts),
        fills=len(legs),
        gold_rows=len(gold_rows),
        training_rows=len(training_rows),
        writes=tuple(writes),
    )
