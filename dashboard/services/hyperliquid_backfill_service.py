"""Persisted orchestration for Hyperliquid requester-pays backfills."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.db import transaction

from dashboard.models import HyperliquidBackfillJob
from dashboard.services.markout_decision_service import refresh_markout_fill_decisions
from marketimmune.ingest.hyperliquid_archive import (
    HyperliquidArchive,
    boto3_requester_pays_fetcher,
    lz4_decompress,
)
from marketimmune.ingest.hyperliquid_backfill import (
    HyperliquidBackfillResult,
    HyperliquidDailyBackfill,
)
from marketimmune.ingest.hyperliquid_fills import NODE_DATA_BUCKET, HyperliquidNodeFills
from marketimmune.ingest.hyperliquid_lake import HyperliquidLakeLayout
from marketimmune.resilience import CircuitBreaker, with_retry

BackfillRunner = Callable[["BackfillRequest"], HyperliquidBackfillResult]


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    """Operator request for one coin/day backfill."""

    coin: str
    date: str
    hours: tuple[int, ...]
    fill_suffixes: tuple[str, ...]
    lake_root: Path = Path("data/hyperliquid")
    include_asset_ctxs: bool = True
    refresh_decisions: bool = True
    dry_run: bool = False
    trigger: str = "manual"


def run_hyperliquid_backfill_job(
    request: BackfillRequest,
    *,
    runner: BackfillRunner | None = None,
) -> HyperliquidBackfillJob:
    """Run or plan one requester-pays backfill and persist the job outcome."""
    _validate_request(request)
    job = HyperliquidBackfillJob.objects.create(
        job_id=f"hl_backfill_{uuid.uuid4().hex[:12]}",
        status="running",
        trigger=request.trigger,
        coin=request.coin,
        date=request.date,
        hours=list(request.hours),
        fill_suffixes=list(request.fill_suffixes),
        lake_root=str(request.lake_root),
        include_asset_ctxs=request.include_asset_ctxs,
        refresh_decisions=request.refresh_decisions,
        dry_run=request.dry_run,
        started_at=_now(),
    )
    if request.dry_run:
        return _finish_job(job, status="planned", message="Dry run; no S3 objects fetched.")

    try:
        result = (runner or _run_requester_pays_backfill)(request)
        refresh_run_id = _refresh_decisions_if_needed(request, result)
    except Exception as exc:
        return _finish_job(job, status="failed", message=str(exc))

    return _finish_job(
        job,
        status="succeeded",
        result=result,
        refresh_run_id=refresh_run_id,
    )


def recent_hyperliquid_backfill_jobs(*, limit: int = 10) -> dict[str, Any]:
    """Return recent persisted backfill jobs for operator status surfaces."""
    bounded = max(1, min(50, int(limit)))
    rows = HyperliquidBackfillJob.objects.order_by("-started_at")[:bounded]
    return {
        "kind": "hyperliquid_backfill_jobs",
        "configured_limit": bounded,
        "jobs": [_job_payload(row) for row in rows],
    }


def parse_hours(values: Sequence[str]) -> tuple[int, ...]:
    """Parse comma/range hour values, e.g. ``0,1`` or ``8-23``."""
    hours: list[int] = []
    for value in values:
        for part in value.split(","):
            text = part.strip()
            if not text:
                continue
            if "-" in text:
                start_text, end_text = text.split("-", 1)
                start = int(start_text)
                end = int(end_text)
                hours.extend(range(start, end + 1))
            else:
                hours.append(int(text))
    out = tuple(sorted(set(hours)))
    if not out:
        raise ValueError("at least one hour is required")
    bad = [hour for hour in out if hour < 0 or hour > 23]
    if bad:
        raise ValueError(f"hours must be in [0, 23], got {bad}")
    return out


def fill_suffixes_for_hours(date: str, values: Sequence[str]) -> tuple[str, ...]:
    """Build confirmed hourly node-fill suffixes for ``node_fills_by_block``."""
    if not values:
        return ()
    return tuple(f"hourly/{date}/{hour}.lz4" for hour in parse_hours(values))


def combine_fill_suffixes(
    *,
    date: str,
    explicit_suffixes: Sequence[str],
    fill_hour_values: Sequence[str],
) -> tuple[str, ...]:
    """Merge explicit and generated suffixes, preserving first occurrence."""
    combined = [*explicit_suffixes, *fill_suffixes_for_hours(date, fill_hour_values)]
    out: list[str] = []
    seen: set[str] = set()
    for suffix in combined:
        if suffix not in seen:
            out.append(suffix)
            seen.add(suffix)
    return tuple(out)


def _run_requester_pays_backfill(request: BackfillRequest) -> HyperliquidBackfillResult:
    archive_fetch = _resilient_fetch(boto3_requester_pays_fetcher())
    node_fetch = _resilient_fetch(boto3_requester_pays_fetcher(NODE_DATA_BUCKET))
    backfill = HyperliquidDailyBackfill(
        layout=HyperliquidLakeLayout(request.lake_root),
        archive=HyperliquidArchive(fetch=archive_fetch, decompress=lz4_decompress),
        node_fills=HyperliquidNodeFills(fetch=node_fetch, decompress=lz4_decompress),
    )
    return backfill.run(
        coin=request.coin,
        date=request.date,
        hours=request.hours,
        fill_suffixes=request.fill_suffixes,
        include_asset_ctxs=request.include_asset_ctxs,
    )


def _resilient_fetch(fetch: Callable[[str], bytes]) -> Callable[[str], bytes]:
    breaker = CircuitBreaker(failure_threshold=3, reset_timeout_s=30.0)
    retrying = with_retry(fetch, attempts=3, base_delay_s=0.25, max_delay_s=5.0)

    def wrapped(key: str) -> bytes:
        return breaker.call(retrying, key)

    return wrapped


def _refresh_decisions_if_needed(
    request: BackfillRequest,
    result: HyperliquidBackfillResult,
) -> int | None:
    if not request.refresh_decisions or result.training_rows <= 0:
        return None
    refresh = refresh_markout_fill_decisions(trigger="backfill_job")
    return refresh.run_id


@transaction.atomic
def _finish_job(
    job: HyperliquidBackfillJob,
    *,
    status: str,
    result: HyperliquidBackfillResult | None = None,
    refresh_run_id: int | None = None,
    message: str = "",
) -> HyperliquidBackfillJob:
    finished_at = _now()
    job.status = status
    job.finished_at = finished_at
    job.duration_ms = (finished_at - job.started_at.replace(tzinfo=None)).total_seconds() * 1000.0
    job.message = message
    job.refresh_run_id = refresh_run_id
    if result is not None:
        job.book_snapshots = result.book_snapshots
        job.asset_contexts = result.asset_contexts
        job.fills = result.fills
        job.gold_rows = result.gold_rows
        job.training_rows = result.training_rows
        job.writes = [str(write.path) for write in result.writes]
    job.save()
    return job


def _validate_request(request: BackfillRequest) -> None:
    if not request.coin.strip():
        raise ValueError("coin is required")
    if len(request.date) != 8 or not request.date.isdigit():
        raise ValueError("date must be YYYYMMDD")
    parse_hours([",".join(str(hour) for hour in request.hours)])
    if not request.fill_suffixes:
        raise ValueError("at least one fill suffix or fill hour is required")


def _job_payload(job: HyperliquidBackfillJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "trigger": job.trigger,
        "coin": job.coin,
        "date": job.date,
        "hours": list(job.hours or []),
        "fill_suffixes": list(job.fill_suffixes or []),
        "lake_root": job.lake_root,
        "include_asset_ctxs": job.include_asset_ctxs,
        "refresh_decisions": job.refresh_decisions,
        "dry_run": job.dry_run,
        "book_snapshots": job.book_snapshots,
        "asset_contexts": job.asset_contexts,
        "fills": job.fills,
        "gold_rows": job.gold_rows,
        "training_rows": job.training_rows,
        "writes": list(job.writes or []),
        "refresh_run_id": job.refresh_run_id,
        "message": job.message,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": job.duration_ms,
    }


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
