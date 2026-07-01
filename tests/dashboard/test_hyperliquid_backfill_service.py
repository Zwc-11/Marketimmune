"""Tests for persisted Hyperliquid backfill orchestration."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard_project.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from dashboard.services import hyperliquid_backfill_service as service


class FakeJob:
    def __init__(self, **kwargs: Any) -> None:
        self.id = 123
        self.refresh_run_id = None
        self.book_snapshots = 0
        self.asset_contexts = 0
        self.fills = 0
        self.gold_rows = 0
        self.training_rows = 0
        self.writes: list[str] = []
        self.message = ""
        self.finished_at = None
        self.duration_ms = 0.0
        self.saved = False
        for key, value in kwargs.items():
            setattr(self, key, value)

    def save(self) -> None:
        self.saved = True


class FakeJobManager:
    def __init__(self) -> None:
        self.created: list[FakeJob] = []

    def create(self, **kwargs: Any) -> FakeJob:
        job = FakeJob(**kwargs)
        self.created.append(job)
        return job


class FakeJobModel:
    objects = FakeJobManager()


def test_combine_fill_suffixes_deduplicates_generated_hours() -> None:
    suffixes = service.combine_fill_suffixes(
        date="20260601",
        explicit_suffixes=["hourly/20260601/8.lz4"],
        fill_hour_values=["8-9"],
    )

    assert suffixes == ("hourly/20260601/8.lz4", "hourly/20260601/9.lz4")


def test_backfill_dry_run_persists_planned_job(monkeypatch: Any) -> None:
    monkeypatch.setattr(service, "HyperliquidBackfillJob", FakeJobModel)
    request = service.BackfillRequest(
        coin="SOL",
        date="20260601",
        hours=(0,),
        fill_suffixes=("hourly/20260601/0.lz4",),
        dry_run=True,
    )

    job = service.run_hyperliquid_backfill_job(
        request,
        runner=lambda _request: (_ for _ in ()).throw(AssertionError("no run")),
    )

    assert job.status == "planned"
    assert job.dry_run is True
    assert job.message == "Dry run; no S3 objects fetched."
    assert job.saved is True


def test_backfill_success_refreshes_promoted_decisions(monkeypatch: Any) -> None:
    monkeypatch.setattr(service, "HyperliquidBackfillJob", FakeJobModel)
    refreshed: list[str] = []

    def fake_refresh(*, trigger: str):
        refreshed.append(trigger)
        return SimpleNamespace(run_id=77)

    monkeypatch.setattr(service, "refresh_markout_fill_decisions", fake_refresh)

    result = SimpleNamespace(
        book_snapshots=10,
        asset_contexts=20,
        fills=30,
        gold_rows=29,
        training_rows=28,
        writes=[SimpleNamespace(path=Path("gold.parquet"))],
    )
    request = service.BackfillRequest(
        coin="SOL",
        date="20260601",
        hours=(0,),
        fill_suffixes=("hourly/20260601/0.lz4",),
    )

    job = service.run_hyperliquid_backfill_job(request, runner=lambda _request: result)

    assert job.status == "succeeded"
    assert job.training_rows == 28
    assert job.writes == ["gold.parquet"]
    assert job.refresh_run_id == 77
    assert refreshed == ["backfill_job"]
