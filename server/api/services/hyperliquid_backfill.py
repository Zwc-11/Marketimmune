"""Run requester-pays Hyperliquid backfills as persisted jobs the terminal can list."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.utils import timezone

from marketimmune.lake.backfill import HyperliquidBackfillResult, run_backfill
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.sources import hyperliquid_s3 as s3
from server.api.models import HyperliquidBackfillJob
from server.api.services.markout_decisions import refresh_markout_fill_decisions


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    """One coin-day: L2 ``hours`` and ``node_fills_by_block`` ``fill_hours``."""

    coin: str
    date: str
    hours: tuple[int, ...]
    fill_hours: tuple[int, ...]
    lake_root: Path = Path("data")
    include_asset_ctxs: bool = True
    refresh_decisions: bool = True
    dry_run: bool = False
    trigger: str = "manual"


def run_hyperliquid_backfill_job(request: BackfillRequest) -> HyperliquidBackfillJob:
    """Run (or, with ``dry_run``, only record) one backfill; failures end the job as ``failed`` with the error."""
    assert len(request.date) == 8 and request.date.isdigit(), f"{request.date=}: want YYYYMMDD"
    assert request.fill_hours, "at least one fill hour is required"
    job = HyperliquidBackfillJob.objects.create(
        job_id=f"hl_backfill_{uuid.uuid4().hex[:12]}",
        status="running",
        trigger=request.trigger,
        coin=request.coin,
        date=request.date,
        hours=list(request.hours),
        fill_suffixes=[f"hourly/{request.date}/{hour}.lz4" for hour in request.fill_hours],
        lake_root=str(request.lake_root),
        include_asset_ctxs=request.include_asset_ctxs,
        refresh_decisions=request.refresh_decisions,
        dry_run=request.dry_run,
        started_at=timezone.now(),
    )
    if request.dry_run:
        return _finish(job, status="planned", message="Dry run; no S3 objects fetched.")
    try:
        result = _run_requester_pays(request)
        refresh_run_id = None
        if request.refresh_decisions and result.training_rows > 0:
            refresh_run_id = refresh_markout_fill_decisions(trigger="backfill_job").run_id
    except Exception as exc:  # recorded on the job, which the terminal shows
        return _finish(job, status="failed", message=str(exc))
    return _finish(job, status="succeeded", result=result, refresh_run_id=refresh_run_id)


def recent_hyperliquid_backfill_jobs(*, limit: int = 10) -> dict[str, Any]:
    limit = max(1, min(50, limit))
    return {
        "kind": "hyperliquid_backfill_jobs",
        "configured_limit": limit,
        "jobs": [_job_payload(job) for job in HyperliquidBackfillJob.objects.order_by("-started_at")[:limit]],
    }


def _run_requester_pays(request: BackfillRequest) -> HyperliquidBackfillResult:
    return run_backfill(
        HyperliquidLakeLayout(request.lake_root),
        archive=s3.fetcher(s3.ARCHIVE_BUCKET, s3.ARCHIVE_REGION),
        node=s3.fetcher(s3.NODE_BUCKET, s3.NODE_REGION),
        coin=request.coin,
        date=request.date,
        hours=request.hours,
        fill_hours=request.fill_hours,
        include_asset_ctxs=request.include_asset_ctxs,
    )


def _finish(
    job: HyperliquidBackfillJob,
    *,
    status: str,
    result: HyperliquidBackfillResult | None = None,
    refresh_run_id: int | None = None,
    message: str = "",
) -> HyperliquidBackfillJob:
    job.status = status
    job.finished_at = timezone.now()
    job.duration_ms = (job.finished_at - job.started_at).total_seconds() * 1000.0
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


def _job_payload(job: HyperliquidBackfillJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "trigger": job.trigger,
        "coin": job.coin,
        "date": job.date,
        "hours": job.hours,
        "fill_suffixes": job.fill_suffixes,
        "lake_root": job.lake_root,
        "include_asset_ctxs": job.include_asset_ctxs,
        "refresh_decisions": job.refresh_decisions,
        "dry_run": job.dry_run,
        "book_snapshots": job.book_snapshots,
        "asset_contexts": job.asset_contexts,
        "fills": job.fills,
        "gold_rows": job.gold_rows,
        "training_rows": job.training_rows,
        "writes": job.writes,
        "refresh_run_id": job.refresh_run_id,
        "message": job.message,
        "started_at": job.started_at.isoformat(),
        "finished_at": None if job.finished_at is None else job.finished_at.isoformat(),
        "duration_ms": job.duration_ms,
    }
