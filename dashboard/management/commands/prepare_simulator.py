"""Pre-warm a replay session before the dev server starts.

Idempotent: does nothing when a session already exists. Designed to be
called from `setup_dashboard.bat` / `setup_dashboard.sh` so the very
first /simulator/ page load is instant rather than blocking for 30+
seconds while parquet files are decoded.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from dashboard.models import ReplaySession
from dashboard.services import SimulatorService


class Command(BaseCommand):
    help = "Ensure at least one replay session exists; build a default if not."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild the session even if one already exists.",
        )

    def handle(self, *args, **options):
        service = SimulatorService()
        existing = ReplaySession.objects.count()
        if existing and not options["force"]:
            self.stdout.write(self.style.SUCCESS(
                f"Found {existing} existing replay session(s); skipping warm-up."
            ))
            return
        self.stdout.write(self.style.WARNING(
            "Building default replay session "
            f"({service.DEFAULT_CONFIG.scenario_name}, limit="
            f"{service.DEFAULT_CONFIG.limit})..."
        ))
        service.start(service.DEFAULT_CONFIG)
        self.stdout.write(self.style.SUCCESS("Simulator is ready."))
