"""Tests for persisted promoted-model fill decisions."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from server.api.services import markout_decisions as service


def test_latest_gold_partition_uses_partition_date(tmp_path: Path) -> None:
    older = tmp_path / "SOL-training-20260531.parquet"
    newer = tmp_path / "SOL-training-20260601.parquet"
    nested = tmp_path / "archive" / "SOL-training-20260530.parquet"
    nested.parent.mkdir()
    for path in (older, newer, nested):
        path.write_bytes(b"")

    assert service._latest_gold_partition(tmp_path) == newer


def test_should_refresh_when_resolved_gold_source_changes(monkeypatch: Any) -> None:
    class FakeLatest:
        source_path = "data/old.parquet"
        scored_at = service._now() - timedelta(milliseconds=1)

    class FakeDecisionManager:
        def order_by(self, *_fields: str) -> FakeDecisionManager:
            return self

        def first(self) -> FakeLatest:
            return FakeLatest()

    class FakeDecisionModel:
        objects = FakeDecisionManager()

    monkeypatch.setattr(service, "ScoredFillDecision", FakeDecisionModel)
    monkeypatch.setattr(service, "_display_path", lambda _path: "data/new.parquet")

    assert service._should_refresh(None, gold_path=Path("new.parquet")) is True
