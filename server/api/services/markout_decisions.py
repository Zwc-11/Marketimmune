"""Score the newest Gold partition with the promoted model and serve the persisted decisions."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from marketimmune.serving.gold_scoring import GoldFillScore, score_gold_training_file
from marketimmune.serving.scorer import HyperliquidMarkoutScorer
from server.api.models import ScoredFillDecision, ScoredFillRefreshRun
from server.api.services.markout_model import configured_path, display_path, promoted_artifacts


@dataclass(frozen=True, slots=True)
class DecisionRefresh:
    """Outcome of one score-and-persist pass."""

    attempted: bool
    refreshed_count: int = 0
    message: str = ""
    source_path: str = ""
    status: str = "skipped"
    run_id: int | None = None


def latest_gold_partition() -> Path:
    """The ``*-training-<YYYYMMDD>.parquet`` with the latest date anywhere under the Gold root."""
    root = configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT")
    partitions = root.rglob("*-training-*.parquet")
    return max(partitions, key=lambda path: (path.name.rsplit("-", 1)[1], str(path)), default=root / "<no Gold training partition>")


def recent_markout_fill_decisions(*, limit: int | None = None, refresh: bool | None = None) -> dict[str, Any]:
    """The newest persisted decisions; ``refresh=None`` scores first only when the table is empty or stale."""
    limit = _limit(limit)
    gold_path = latest_gold_partition()
    outcome = DecisionRefresh(attempted=False)
    if refresh or (refresh is None and _stale(gold_path)):
        outcome = refresh_markout_fill_decisions(limit=limit, trigger="api")
    rows = ScoredFillDecision.objects.order_by("-scored_at", "-timestamp")[:limit]
    latest = ScoredFillRefreshRun.objects.order_by("-started_at").first()
    return {
        "available": bool(rows) and not outcome.message,
        "kind": "hyperliquid_markout_fill_decisions",
        "source_path": outcome.source_path or display_path(gold_path),
        "configured_limit": limit,
        "refresh_attempted": outcome.attempted,
        "refreshed_count": outcome.refreshed_count,
        "message": outcome.message,
        "latest_refresh": None if latest is None else _refresh_payload(latest),
        "decisions": [_decision_payload(row) for row in rows],
    }


def refresh_markout_fill_decisions(*, limit: int | None = None, trigger: str = "manual") -> DecisionRefresh:
    """Score the newest Gold rows and upsert them; the attempt is recorded as a :class:`ScoredFillRefreshRun`."""
    limit = _limit(limit)
    paths = promoted_artifacts()
    gold_path = latest_gold_partition()
    run = ScoredFillRefreshRun.objects.create(
        status="running",
        trigger=trigger,
        source_path=display_path(gold_path),
        requested_limit=limit,
        started_at=timezone.now(),
    )
    missing = [path for path in (*paths.values(), gold_path) if not path.exists()]
    if missing:
        return _finish(run, status="failed", message=f"Missing artifact: {display_path(missing[0])}")
    try:
        scorer = HyperliquidMarkoutScorer.load(paths["model"], paths["calibrator"], paths["report"])
        scores = _score_gold_file(gold_path, scorer, limit)
        count = _persist(scores[-limit:], source_path=run.source_path, model_key=model_digest(paths["model"]))
    except Exception as exc:  # recorded on the run, which the terminal shows
        return _finish(run, status="failed", message=str(exc))
    return _finish(run, status="succeeded", refreshed_count=count)


def _score_gold_file(path: Path, scorer: HyperliquidMarkoutScorer, limit: int) -> Sequence[GoldFillScore]:
    return score_gold_training_file(path, scorer, horizon=scorer.report["horizon"], limit=limit, latest=True)


def model_digest(path: Path) -> str:
    """The model file's content hash (first 16 hex digits of SHA-256)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def decision_key(alert_id: str, model_key: str) -> str:
    """One record per fill *and model*: a later model's score of the same fill is a new row,
    so what an earlier model decided is never overwritten."""
    return f"{alert_id}@{model_key}"


@transaction.atomic
def _persist(scores: Sequence[GoldFillScore], *, source_path: str, model_key: str) -> int:
    for score in scores:
        ScoredFillDecision.objects.update_or_create(
            decision_id=decision_key(score.alert_id, model_key),
            defaults={
                "coin": score.coin,
                "ts_ms": score.ts_ms,
                "timestamp": datetime.fromtimestamp(score.ts_ms / 1000.0, tz=UTC),
                "px": score.px,
                "sz": score.sz,
                "side": score.side,
                "maker_side": score.maker_side,
                "model_name": score.model_name,
                "raw_score": score.raw_score,
                "calibrated_score": score.calibrated_score,
                "decision_threshold": score.decision_threshold,
                "action": score.action,
                "severity": _severity(score),
                "markout_bps": score.markout_bps,
                "toxic": score.toxic,
                "tid": score.tid,
                "oid": score.oid,
                "feature_values": dict(score.feature_values),
                "top_features": list(score.top_features()),
                "source_path": source_path,
            },
        )
    return len(scores)


def _severity(score: GoldFillScore) -> str:
    if score.action == "withhold_quote":
        return "critical" if score.calibrated_score >= 0.75 else "high"
    return "medium" if score.calibrated_score >= 0.45 else "low"


def _limit(value: int | None) -> int:
    return max(1, min(100, settings.MARKETIMMUNE_MARKOUT_DECISION_LIMIT if value is None else value))


def _stale(gold_path: Path) -> bool:
    """No decisions yet, decisions from another partition, or older than the refresh TTL."""
    latest = ScoredFillDecision.objects.order_by("-scored_at").first()
    if latest is None or latest.source_path != display_path(gold_path):
        return True
    age_ms = (timezone.now() - latest.scored_at).total_seconds() * 1000.0
    return age_ms >= settings.MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS


def _finish(run: ScoredFillRefreshRun, *, status: str, refreshed_count: int = 0, message: str = "") -> DecisionRefresh:
    run.status = status
    run.refreshed_count = refreshed_count
    run.message = message
    run.finished_at = timezone.now()
    run.duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000.0
    run.save(update_fields=["status", "refreshed_count", "message", "finished_at", "duration_ms"])
    return DecisionRefresh(
        attempted=True,
        refreshed_count=refreshed_count,
        message=message,
        source_path=run.source_path,
        status=status,
        run_id=run.id,
    )


def _decision_payload(row: ScoredFillDecision) -> dict[str, Any]:
    return {
        "decision_id": row.decision_id,
        "coin": row.coin,
        "ts_ms": row.ts_ms,
        "timestamp": row.timestamp.isoformat(),
        "px": row.px,
        "sz": row.sz,
        "side": row.side,
        "maker_side": row.maker_side,
        "model_name": row.model_name,
        "raw_score": row.raw_score,
        "calibrated_score": row.calibrated_score,
        "decision_threshold": row.decision_threshold,
        "action": row.action,
        "severity": row.severity,
        "markout_bps": row.markout_bps,
        "toxic": row.toxic,
        "tid": row.tid,
        "oid": row.oid,
        "top_features": row.top_features,
        "feature_values": row.feature_values,
        "source_path": row.source_path,
        "scored_at": row.scored_at.isoformat(),
    }


def _refresh_payload(run: ScoredFillRefreshRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "trigger": run.trigger,
        "source_path": run.source_path,
        "requested_limit": run.requested_limit,
        "refreshed_count": run.refreshed_count,
        "message": run.message,
        "started_at": run.started_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
        "duration_ms": run.duration_ms,
    }
