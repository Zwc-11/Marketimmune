"""Run or plan one persisted Hyperliquid requester-pays backfill job."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from dashboard.services.hyperliquid_backfill_service import (
    BackfillRequest,
    combine_fill_suffixes,
    parse_hours,
    run_hyperliquid_backfill_job,
)


class Command(BaseCommand):
    help = "Run a persisted Hyperliquid requester-pays backfill job."

    def add_arguments(self, parser):
        parser.add_argument("--coin", required=True, help="Hyperliquid coin, e.g. SOL")
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
            help="Suffix under node_fills_by_block. Repeatable.",
        )
        parser.add_argument(
            "--fill-hour",
            action="append",
            default=[],
            help="Generate hourly/<date>/<hour>.lz4 fill suffixes.",
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
            "--no-refresh-decisions",
            action="store_true",
            help="Do not refresh promoted fill decisions after a successful backfill.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Persist a planned job without fetching requester-pays S3 objects.",
        )
        parser.add_argument(
            "--trigger",
            default="manual",
            choices=["manual", "scheduled", "api"],
            help="Operator trigger label recorded on the job.",
        )

    def handle(self, *args, **options):
        try:
            fill_suffixes = combine_fill_suffixes(
                date=options["date"],
                explicit_suffixes=options["fill_suffix"],
                fill_hour_values=options["fill_hour"],
            )
            request = BackfillRequest(
                coin=options["coin"].upper(),
                date=options["date"],
                hours=parse_hours(options["hour"]),
                fill_suffixes=fill_suffixes,
                lake_root=Path(options["lake_root"]),
                include_asset_ctxs=not options["skip_asset_ctxs"],
                refresh_decisions=not options["no_refresh_decisions"],
                dry_run=options["dry_run"],
                trigger=options["trigger"],
            )
            job = run_hyperliquid_backfill_job(request)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        style = self.style.SUCCESS if job.status in {"succeeded", "planned"} else self.style.ERROR
        self.stdout.write(
            style(
                f"{job.job_id}: status={job.status} coin={job.coin} date={job.date} "
                f"fills={job.fills} training_rows={job.training_rows} "
                f"refresh_run_id={job.refresh_run_id or '-'} "
                f"duration={job.duration_ms:.1f}ms"
            )
        )
        if job.message:
            self.stdout.write(job.message)
