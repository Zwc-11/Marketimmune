"""Run (or plan) one persisted Hyperliquid requester-pays backfill job.

python server/manage.py run_hyperliquid_backfill --coin SOL --date 20250727 --hour 0-23 --fill-hour 0-23
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from marketimmune.lake.backfill import parse_hours
from server.api.services.hyperliquid_backfill import BackfillRequest, run_hyperliquid_backfill_job


class Command(BaseCommand):
    help = __doc__.splitlines()[0]

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--coin", required=True)
        parser.add_argument("--date", required=True, help="YYYYMMDD")
        parser.add_argument("--hour", action="append", required=True, help="L2 book hours, e.g. 0-23 or 8,9 (repeatable)")
        parser.add_argument("--fill-hour", action="append", required=True, help="node_fills_by_block hours, same syntax")
        parser.add_argument("--lake-root", type=Path, default=Path("data"))
        parser.add_argument("--skip-asset-ctxs", action="store_true")
        parser.add_argument("--no-refresh-decisions", action="store_true", help="do not rescore promoted fill decisions afterwards")
        parser.add_argument("--dry-run", action="store_true", help="record a planned job without fetching from S3")
        parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled", "api"])

    def handle(self, *args: Any, **options: Any) -> None:
        request = BackfillRequest(
            coin=options["coin"].upper(),
            date=options["date"],
            hours=parse_hours(options["hour"]),
            fill_hours=parse_hours(options["fill_hour"]),
            lake_root=options["lake_root"],
            include_asset_ctxs=not options["skip_asset_ctxs"],
            refresh_decisions=not options["no_refresh_decisions"],
            dry_run=options["dry_run"],
            trigger=options["trigger"],
        )
        job = run_hyperliquid_backfill_job(request)
        style = self.style.SUCCESS if job.status in {"succeeded", "planned"} else self.style.ERROR
        self.stdout.write(
            style(
                f"{job.job_id}: status={job.status} coin={job.coin} date={job.date} fills={job.fills} "
                f"training_rows={job.training_rows} refresh_run_id={job.refresh_run_id or '-'} duration={job.duration_ms:.1f}ms"
            )
        )
        if job.message:
            self.stdout.write(job.message)
