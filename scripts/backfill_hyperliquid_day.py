from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from marketimmune.ingest.hyperliquid_archive import (
    HyperliquidArchive,
    boto3_requester_pays_fetcher,
    lz4_decompress,
)
from marketimmune.ingest.hyperliquid_backfill import HyperliquidDailyBackfill
from marketimmune.ingest.hyperliquid_fills import NODE_DATA_BUCKET, HyperliquidNodeFills
from marketimmune.ingest.hyperliquid_lake import HyperliquidLakeLayout
from marketimmune.resilience import CircuitBreaker, with_retry


def parse_hours(values: Sequence[str]) -> list[int]:
    """Parse repeated comma/range hour arguments, e.g. ``0,1,2`` or ``0-23``."""
    hours: list[int] = []
    for value in values:
        for part in value.split(","):
            text = part.strip()
            if not text:
                continue
            if "-" in text:
                start_text, end_text = text.split("-", 1)
                start, end = int(start_text), int(end_text)
                hours.extend(range(start, end + 1))
            else:
                hours.append(int(text))
    unique_hours = sorted(set(hours))
    if not unique_hours:
        raise argparse.ArgumentTypeError("at least one hour is required")
    bad = [hour for hour in unique_hours if hour < 0 or hour > 23]
    if bad:
        raise argparse.ArgumentTypeError(f"hours must be in [0, 23], got {bad}")
    return unique_hours


def resilient_fetch(fetch: Callable[[str], bytes]) -> Callable[[str], bytes]:
    """Wrap one requester-pays fetch callable with retry and circuit breaking."""
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_s=30.0)
    retrying = with_retry(fetch, attempts=3, base_delay_s=0.25, max_delay_s=5.0)

    def wrapped(key: str) -> bytes:
        return breaker.call(retrying, key)

    return wrapped


def progress_fetch(
    fetch: Callable[[str], bytes],
    *,
    label: str,
    enabled: bool = True,
) -> Callable[[str], bytes]:
    """Print one line before/after each S3 object fetch."""

    def wrapped(key: str) -> bytes:
        if enabled:
            print(f"[fetch] {label}: {key}", file=sys.stderr, flush=True)
        raw = fetch(key)
        if enabled:
            print(
                f"[done]  {label}: {key} ({len(raw):,} bytes)",
                file=sys.stderr,
                flush=True,
            )
        return raw

    return wrapped


def progress_stage(message: str, *, enabled: bool = True) -> None:
    """Print a backfill processing stage line."""
    if enabled:
        print(f"[stage] {message}", file=sys.stderr, flush=True)


def fill_suffixes_for_hours(date: str, values: Sequence[str]) -> list[str]:
    """Build real hourly node-fill suffixes for ``node_fills_by_block``."""
    if not values:
        return []
    return [f"hourly/{date}/{hour}.lz4" for hour in parse_hours(values)]


def combine_fill_suffixes(
    *,
    date: str,
    explicit_suffixes: Sequence[str],
    fill_hour_values: Sequence[str],
) -> list[str]:
    """Merge explicit suffixes with generated hourly suffixes, preserving order."""
    combined = list(explicit_suffixes) + fill_suffixes_for_hours(date, fill_hour_values)
    out: list[str] = []
    seen: set[str] = set()
    for suffix in combined:
        if suffix not in seen:
            out.append(suffix)
            seen.add(suffix)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill one Hyperliquid coin/day into the local parquet lake. "
            "Requires pip install -e \".[hyperliquid]\" and requester-pays S3 access."
        )
    )
    parser.add_argument("--coin", required=True, help="Hyperliquid coin, e.g. BTC")
    parser.add_argument("--date", required=True, help="Archive date as YYYYMMDD")
    parser.add_argument(
        "--hour",
        action="append",
        required=True,
        help="Hour, comma list, or range. Repeatable. Example: --hour 0-23",
    )
    parser.add_argument(
        "--fill-suffix",
        action="append",
        default=[],
        help=(
            "Suffix under node_fills_by_block. Repeatable. "
            "Example: --fill-suffix hourly/20250727/8.lz4"
        ),
    )
    parser.add_argument(
        "--fill-hour",
        action="append",
        default=[],
        help=(
            "Hour, comma list, or range used to generate real fill suffixes "
            "hourly/<date>/<hour>.lz4. Example: --fill-hour 8-23"
        ),
    )
    parser.add_argument(
        "--lake-root",
        default="data/hyperliquid",
        help="Output lake root. Default: data/hyperliquid",
    )
    parser.add_argument(
        "--skip-asset-ctxs",
        action="store_true",
        help="Skip asset_ctxs/<YYYYMMDD>.csv.lz4.",
    )
    parser.add_argument(
        "--no-resilience",
        action="store_true",
        help="Do not wrap S3 fetches in retry/circuit breaker.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-object progress lines on stderr.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    hours = parse_hours(args.hour)
    fill_suffixes = combine_fill_suffixes(
        date=args.date,
        explicit_suffixes=args.fill_suffix,
        fill_hour_values=args.fill_hour,
    )
    archive_fetch = boto3_requester_pays_fetcher()
    node_fetch = boto3_requester_pays_fetcher(NODE_DATA_BUCKET)
    archive_fetch = progress_fetch(archive_fetch, label="archive", enabled=not args.quiet)
    node_fetch = progress_fetch(node_fetch, label="node-data", enabled=not args.quiet)
    if not args.no_resilience:
        archive_fetch = resilient_fetch(archive_fetch)
        node_fetch = resilient_fetch(node_fetch)
    backfill = HyperliquidDailyBackfill(
        layout=HyperliquidLakeLayout(Path(args.lake_root)),
        archive=HyperliquidArchive(fetch=archive_fetch, decompress=lz4_decompress),
        node_fills=HyperliquidNodeFills(fetch=node_fetch, decompress=lz4_decompress),
    )
    result = backfill.run(
        coin=args.coin,
        date=args.date,
        hours=hours,
        fill_suffixes=fill_suffixes,
        include_asset_ctxs=not args.skip_asset_ctxs,
        progress=lambda message: progress_stage(message, enabled=not args.quiet),
    )
    print(json.dumps({
        "coin": result.coin,
        "date": result.date,
        "book_snapshots": result.book_snapshots,
        "asset_contexts": result.asset_contexts,
        "fills": result.fills,
        "gold_rows": result.gold_rows,
        "training_rows": result.training_rows,
        "writes": [str(write.path) for write in result.writes],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
