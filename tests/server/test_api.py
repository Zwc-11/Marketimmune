"""The three endpoints the terminal polls, through the views, services and a throwaway test database."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.settings")

import django
import pytest

django.setup()

from django.db import connection
from django.test import Client, override_settings

from server.api.models import HyperliquidBackfillJob, ScoredFillDecision, ScoredFillRefreshRun
from server.api.services import hyperliquid_backfill, markout_decisions


@pytest.fixture(scope="module", autouse=True)
def test_db() -> Iterator[None]:
    old_name = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    yield
    connection.creation.destroy_test_db(old_name, verbosity=0)


@pytest.fixture(autouse=True)
def empty_tables() -> None:
    for model in (HyperliquidBackfillJob, ScoredFillDecision, ScoredFillRefreshRun):
        model.objects.all().delete()


@dataclass
class FakeScore:
    ts_ms: float
    calibrated_score: float
    action: str
    coin: str = "SOL"
    px: float = 150.0
    sz: float = 2.0
    side: str = "B"
    maker_side: int = 1
    model_name: str = "catboost_markout_SOL_10s"
    raw_score: float = 0.5
    decision_threshold: float | None = 0.3
    markout_bps: float | None = -1.5
    toxic: bool | None = True
    tid: int | None = 7
    oid: int | None = None
    feature_values: dict[str, float] = field(default_factory=lambda: {"a": 0.1, "b": -2.0, "c": 0.5, "d": 0.0})

    @property
    def alert_id(self) -> str:
        return f"hl_{self.coin}_{int(self.ts_ms)}-{self.tid}"

    def top_features(self) -> tuple[str, ...]:
        return ("b", "c", "a")


def _request(**overrides: Any) -> hyperliquid_backfill.BackfillRequest:
    fields: dict[str, Any] = {"coin": "SOL", "date": "20260601", "hours": (0, 1), "fill_hours": (0,), "refresh_decisions": False}
    return hyperliquid_backfill.BackfillRequest(**(fields | overrides))


def test_head_is_a_cheap_405_and_bad_methods_are_refused() -> None:
    client = Client()
    assert client.head("/api/markout-model/health/").status_code == 405
    assert client.post("/api/hyperliquid/backfill-jobs/").status_code == 405


def test_terminal_serves_the_bundle_with_absolute_asset_urls() -> None:
    page = Client().get("/terminal/some/route")
    assert page.status_code == 200 and b'="/static/terminal/assets/' in page.content


def test_backfill_jobs_endpoint_lists_planned_succeeded_and_failed_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hyperliquid_backfill, "_run_requester_pays", lambda _r: pytest.fail("a dry run must not fetch"))
    planned = hyperliquid_backfill.run_hyperliquid_backfill_job(_request(dry_run=True))
    assert (planned.status, planned.message, planned.fill_suffixes) == (
        "planned",
        "Dry run; no S3 objects fetched.",
        ["hourly/20260601/0.lz4"],
    )
    result = SimpleNamespace(
        book_snapshots=10, asset_contexts=20, fills=30, gold_rows=29, training_rows=28, writes=[SimpleNamespace(path=Path("gold.parquet"))]
    )
    monkeypatch.setattr(hyperliquid_backfill, "_run_requester_pays", lambda _r: result)
    hyperliquid_backfill.run_hyperliquid_backfill_job(_request())

    def boom(_r: object) -> object:
        raise RuntimeError("S3 said no")

    monkeypatch.setattr(hyperliquid_backfill, "_run_requester_pays", boom)
    hyperliquid_backfill.run_hyperliquid_backfill_job(_request())
    payload = Client().get("/api/hyperliquid/backfill-jobs/?limit=2").json()
    assert payload["kind"] == "hyperliquid_backfill_jobs" and payload["configured_limit"] == 2
    failed, succeeded = payload["jobs"]
    assert (failed["status"], failed["message"]) == ("failed", "S3 said no")
    assert (succeeded["status"], succeeded["fills"], succeeded["training_rows"], succeeded["writes"]) == (
        "succeeded",
        30,
        28,
        ["gold.parquet"],
    )
    assert succeeded["duration_ms"] >= 0.0 and succeeded["hours"] == [0, 1] and succeeded["refresh_run_id"] is None
    frontend_fields = {"job_id", "status", "coin", "date", "book_snapshots", "fills", "training_rows", "message", "duration_ms"}
    assert frontend_fields <= succeeded.keys()


def test_backfill_job_refreshes_decisions_after_new_training_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hyperliquid_backfill, "refresh_markout_fill_decisions", lambda *, trigger: SimpleNamespace(run_id=77, trigger=trigger)
    )
    result = SimpleNamespace(book_snapshots=1, asset_contexts=0, fills=2, gold_rows=1, training_rows=1, writes=[])
    monkeypatch.setattr(hyperliquid_backfill, "_run_requester_pays", lambda _r: result)
    job = hyperliquid_backfill.run_hyperliquid_backfill_job(_request(refresh_decisions=True))
    assert (job.status, job.refresh_run_id) == ("succeeded", 77)


@pytest.fixture
def promoted(tmp_path: Path) -> Iterator[Path]:
    gold = tmp_path / "gold"
    (gold / "archive").mkdir(parents=True)
    for name in (
        "SOL-training-20260531.parquet",
        "SOL-training-20260601.parquet",
        "archive/SOL-training-20260530.parquet",
        "SOL-training-20260601.leakage.json",
    ):
        (gold / name).write_bytes(b"")
    for name in ("model.cbm", "model.isotonic.json", "report.json"):
        (tmp_path / name).write_text("{}")
    with override_settings(
        BASE_DIR=tmp_path,
        MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH="model.cbm",
        MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH="model.isotonic.json",
        MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH="report.json",
        MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT="gold",
    ):
        yield tmp_path


def test_latest_gold_partition_uses_partition_date(promoted: Path) -> None:
    assert markout_decisions.latest_gold_partition() == promoted / "gold" / "SOL-training-20260601.parquet"


def test_decisions_score_once_then_serve_until_stale(promoted: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, int]] = []

    def file_scorer(path: Path, scorer: object, limit: int) -> list[FakeScore]:
        calls.append((path, limit))
        return [
            FakeScore(ts_ms=1_000.0 * i, calibrated_score=s, action=a)
            for i, (s, a) in enumerate([(0.9, "withhold_quote"), (0.5, "withhold_quote"), (0.5, "quote"), (0.1, "quote")])
        ]

    monkeypatch.setattr(markout_decisions, "_score_gold_file", file_scorer)
    monkeypatch.setattr(
        markout_decisions.HyperliquidMarkoutScorer, "load", staticmethod(lambda *_paths: object())
    )  # the scorer is not used
    payload = Client().get("/api/markout-model/decisions/?limit=3").json()
    assert calls == [(promoted / "gold" / "SOL-training-20260601.parquet", 3)]
    assert (payload["available"], payload["refresh_attempted"], payload["refreshed_count"], payload["message"]) == (True, True, 3, "")
    assert payload["source_path"] == "gold/SOL-training-20260601.parquet" and payload["latest_refresh"]["status"] == "succeeded"
    assert [d["severity"] for d in payload["decisions"]] == ["low", "medium", "high"]
    decision = payload["decisions"][0]
    assert {
        "decision_id",
        "ts_ms",
        "px",
        "sz",
        "maker_side",
        "calibrated_score",
        "action",
        "markout_bps",
        "toxic",
        "top_features",
    } <= decision.keys()
    assert decision["top_features"] == ["b", "c", "a"]
    again = Client().get("/api/markout-model/decisions/").json()
    assert again["refresh_attempted"] is False and len(calls) == 1 and len(again["decisions"]) == 3
    forced = Client().get("/api/markout-model/decisions/?refresh=1").json()
    assert forced["refresh_attempted"] is True and len(calls) == 2
    with override_settings(MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS=0):
        assert Client().get("/api/markout-model/decisions/").json()["refresh_attempted"] is True


def test_decisions_report_a_failed_refresh(promoted: Path) -> None:
    (promoted / "model.cbm").unlink()
    payload = Client().get("/api/markout-model/decisions/").json()
    assert payload["available"] is False and payload["message"] == "Missing artifact: model.cbm"
    assert payload["latest_refresh"]["status"] == "failed" and payload["decisions"] == []


def test_health_endpoint_lists_missing_artifacts(tmp_path: Path) -> None:
    with override_settings(BASE_DIR=tmp_path):
        payload = Client().get("/api/markout-model/health/?samples=5000").json()
    assert payload["available"] is False and payload["message"] == "Promoted markout artifacts are not complete yet."
    assert [a["label"] for a in payload["missing_artifacts"]] == ["model", "calibrator", "report"]
