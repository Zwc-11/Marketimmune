"""Run one full agentic immune-loop iteration and persist every artifact."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from dashboard.services import AgenticService


class Command(BaseCommand):
    help = "Run RedTeam -> Simulator -> Sentinel -> Investigator -> Policy -> Memory once."

    def add_arguments(self, parser):
        parser.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
        parser.add_argument("--limit", type=int, default=60, help="Kline ticks to simulate.")
        parser.add_argument(
            "--repeat", type=int, default=1, help="How many loops to run back-to-back."
        )

    def handle(self, *args, **options):
        for i in range(options["repeat"]):
            loop = AgenticService.run_once(
                difficulty=options["difficulty"],
                tick_limit=options["limit"],
            )
            self.stdout.write(self.style.SUCCESS(
                f"[{i+1}/{options['repeat']}] loop {loop.loop_id}: "
                f"posture={loop.aggregate_posture} "
                f"alerts={loop.alert_count} cases={loop.case_count} "
                f"new_memories={loop.new_memory_count} "
                f"duration={loop.duration_ms:.1f}ms"
            ))
