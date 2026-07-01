"""Persist and expose promoted-model decisions for real Hyperliquid fills."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from dashboard.models import (
    ScoredFillDecision,
    ScoredFillDecisionLink,
    ScoredFillRefreshRun,
)
from marketimmune.agentic import LoopResult
from marketimmune.agentic.investigator import InvestigationCase
from marketimmune.agentic.policy import PolicyDecision
from marketimmune.models import (
    GoldFillScore,
    HyperliquidMarkoutScorer,
    MarkoutScorerError,
    score_gold_training_file,
)

ScorerLoader = Callable[[Path, Path, Path], HyperliquidMarkoutScorer]
GoldFileScorer = Callable[
    [Path, HyperliquidMarkoutScorer, int],
    Sequence[GoldFillScore],
]
_GOLD_DATE_RE = re.compile(r"-training-(\d{8})\.parquet$")


@dataclass(frozen=True, slots=True)
class DecisionRefresh:
    """Summary of one optional score-and-persist pass."""

    attempted: bool
    refreshed_count: int = 0
    message: str = ""
    source_path: str = ""
    status: str = "skipped"
    run_id: int | None = None


def recent_markout_fill_decisions(
    *,
    limit: int | None = None,
    refresh: bool | None = None,
    loader: ScorerLoader = HyperliquidMarkoutScorer.load,
    file_scorer: GoldFileScorer | None = None,
) -> dict[str, Any]:
    """Return recent scored-fill decisions, refreshing from Gold parquet if needed.

    ``refresh=None`` means auto: score only when the table is empty or stale.
    ``refresh=True`` forces a score pass, and ``False`` only reads persisted rows.
    """
    resolved_limit = _limit(limit)
    gold_path = _resolved_gold_path()
    refresh_result = DecisionRefresh(attempted=False)
    if _should_refresh(refresh, gold_path=gold_path):
        refresh_result = refresh_markout_fill_decisions(
            limit=resolved_limit,
            loader=loader,
            file_scorer=file_scorer,
            trigger="api",
        )

    rows = list(
        ScoredFillDecision.objects.order_by("-scored_at", "-timestamp")[:resolved_limit]
    )
    return {
        "available": bool(rows) and not refresh_result.message,
        "kind": "hyperliquid_markout_fill_decisions",
        "source_path": refresh_result.source_path or _display_path(gold_path),
        "configured_limit": resolved_limit,
        "refresh_attempted": refresh_result.attempted,
        "refreshed_count": refresh_result.refreshed_count,
        "message": refresh_result.message,
        "latest_refresh": _latest_refresh_payload(),
        "decisions": [_decision_payload(row) for row in rows],
    }


def gold_fill_scores_for_loop(
    *,
    limit: int | None = None,
    refresh: bool = True,
) -> tuple[GoldFillScore, ...]:
    """Return recent persisted scored fills as loop-ready value objects."""
    resolved_limit = _limit(limit)
    if refresh:
        refresh_markout_fill_decisions(limit=resolved_limit, trigger="loop")
    rows = ScoredFillDecision.objects.order_by("-scored_at", "-timestamp")[:resolved_limit]
    return tuple(_score_from_decision(row) for row in rows)


def link_markout_decisions_to_loop(*, loop: Any, result: LoopResult) -> int:
    """Attach scored-fill rows to the loop/case/policy records that consumed them."""
    decisions_by_case = {decision.case_id: decision for decision in result.decisions}
    linked = 0
    for case in result.cases:
        fill_id = _fill_decision_id_from_case(case)
        if not fill_id:
            continue
        policy_decision = decisions_by_case.get(case.case_id)
        updated = _link_fill_decision(
            fill_id=fill_id,
            loop=loop,
            case=case,
            policy_decision=policy_decision,
        )
        linked += updated
    return linked


def refresh_markout_fill_decisions(
    *,
    limit: int | None = None,
    loader: ScorerLoader = HyperliquidMarkoutScorer.load,
    file_scorer: GoldFileScorer | None = None,
    trigger: str = "manual",
) -> DecisionRefresh:
    """Score latest Gold rows with the promoted model and upsert persisted decisions."""
    resolved_limit = _limit(limit)
    model_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_MODEL_PATH")
    calibrator_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_CALIBRATOR_PATH")
    report_path = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_REPORT_PATH")
    gold_path = _resolved_gold_path()
    refresh_run = _start_refresh_run(
        trigger=trigger,
        source_path=gold_path,
        requested_limit=resolved_limit,
    )
    missing = [
        path
        for path in (model_path, calibrator_path, report_path, gold_path)
        if not path.exists()
    ]
    if missing:
        return _finish_refresh_run(
            refresh_run,
            status="failed",
            message=f"Missing artifact: {_display_path(missing[0])}",
        )

    try:
        scorer = loader(model_path, calibrator_path, report_path)
        score_file = file_scorer or _score_gold_file
        scores = score_file(gold_path, scorer, resolved_limit)
        if len(scores) > resolved_limit:
            scores = tuple(scores)[-resolved_limit:]
        persisted = _persist_scores(
            scores,
            source_path=_display_path(gold_path),
        )
    except (ImportError, FileNotFoundError, MarkoutScorerError, ValueError) as exc:
        return _finish_refresh_run(refresh_run, status="failed", message=str(exc))

    return _finish_refresh_run(
        refresh_run,
        status="succeeded",
        refreshed_count=persisted,
    )


def _score_gold_file(
    path: Path,
    scorer: HyperliquidMarkoutScorer,
    limit: int,
) -> Sequence[GoldFillScore]:
    horizon = str(scorer.report.get("horizon") or "10s")
    return score_gold_training_file(path, scorer, horizon=horizon, limit=limit, latest=True)


@transaction.atomic
def _persist_scores(
    scores: Sequence[GoldFillScore],
    *,
    source_path: str,
) -> int:
    count = 0
    for score in scores:
        ScoredFillDecision.objects.update_or_create(
            decision_id=score.alert_id,
            defaults=_score_defaults(score, source_path=source_path),
        )
        count += 1
    return count


def _score_defaults(
    score: GoldFillScore,
    *,
    source_path: str,
) -> dict[str, Any]:
    markout_bps = score.markout_bps
    feature_values = dict(score.feature_values)
    return {
        "coin": score.coin,
        "ts_ms": score.ts_ms,
        "timestamp": _timestamp(score.ts_ms),
        "px": score.px,
        "sz": score.sz,
        "side": score.side,
        "maker_side": score.maker_side,
        "model_name": score.model_name,
        "raw_score": score.raw_score,
        "calibrated_score": score.calibrated_score,
        "decision_threshold": score.decision_threshold,
        "action": score.action,
        "severity": _severity_for_score(score),
        "markout_bps": markout_bps,
        "toxic": score.toxic,
        "tid": score.tid,
        "oid": score.oid,
        "feature_values": feature_values,
        "top_features": list(score.top_features()),
        "source_path": source_path,
    }


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
        "top_features": list(row.top_features or []),
        "feature_values": dict(row.feature_values or {}),
        "source_path": row.source_path,
        "loop_id": row.loop.loop_id if row.loop_id else "",
        "case_id": row.case_id,
        "policy_decision_id": row.policy_decision_id,
        "recommended_action": row.recommended_action,
        "scored_at": row.scored_at.isoformat(),
    }


def _score_from_decision(row: ScoredFillDecision) -> GoldFillScore:
    return GoldFillScore(
        coin=row.coin,
        ts_ms=row.ts_ms,
        px=row.px,
        sz=row.sz,
        side=row.side,
        maker_side=row.maker_side,
        model_name=row.model_name,
        raw_score=row.raw_score,
        calibrated_score=row.calibrated_score,
        decision_threshold=row.decision_threshold,
        action=row.action,
        feature_values=dict(row.feature_values or {}),
        markout_bps=row.markout_bps,
        toxic=row.toxic,
        tid=row.tid,
        oid=row.oid,
    )


def _fill_decision_id_from_case(case: InvestigationCase) -> str:
    if not case.alert_id.startswith("alert_hl_"):
        return ""
    return case.alert_id.removeprefix("alert_")


def _link_fill_decision(
    *,
    fill_id: str,
    loop: Any,
    case: InvestigationCase,
    policy_decision: PolicyDecision | None,
) -> int:
    defaults = {
        "loop": loop,
        "case_id": case.case_id,
        "policy_decision_id": policy_decision.decision_id if policy_decision else "",
        "recommended_action": policy_decision.recommended_action if policy_decision else "",
    }
    try:
        decision = ScoredFillDecision.objects.get(decision_id=fill_id)
    except ScoredFillDecision.DoesNotExist:
        return 0

    for field, value in defaults.items():
        setattr(decision, field, value)
    decision.save(update_fields=[*defaults.keys(), "scored_at"])
    ScoredFillDecisionLink.objects.update_or_create(
        decision=decision,
        loop=loop,
        case_id=case.case_id,
        defaults={
            "policy_decision_id": defaults["policy_decision_id"],
            "recommended_action": defaults["recommended_action"],
        },
    )
    return 1


def _latest_refresh_payload() -> dict[str, Any] | None:
    latest = ScoredFillRefreshRun.objects.order_by("-started_at").first()
    if latest is None:
        return None
    return {
        "id": latest.id,
        "status": latest.status,
        "trigger": latest.trigger,
        "source_path": latest.source_path,
        "requested_limit": latest.requested_limit,
        "refreshed_count": latest.refreshed_count,
        "message": latest.message,
        "started_at": latest.started_at.isoformat(),
        "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
        "duration_ms": latest.duration_ms,
    }


def _should_refresh(refresh: bool | None, *, gold_path: Path) -> bool:
    if refresh is not None:
        return refresh
    latest = ScoredFillDecision.objects.order_by("-scored_at").first()
    if latest is None:
        return True
    if latest.source_path != _display_path(gold_path):
        return True
    elapsed_ms = (_now() - latest.scored_at.replace(tzinfo=None)).total_seconds() * 1000.0
    return elapsed_ms >= _refresh_ttl_ms()


def _severity_for_score(score: GoldFillScore) -> str:
    if score.action == "withhold_quote" and score.calibrated_score >= 0.75:
        return "critical"
    if score.action == "withhold_quote":
        return "high"
    if score.calibrated_score >= 0.45:
        return "medium"
    return "low"


def _limit(value: int | None) -> int:
    fallback = int(getattr(settings, "MARKETIMMUNE_MARKOUT_DECISION_LIMIT", 20))
    raw = fallback if value is None else value
    return max(1, min(100, int(raw)))


def _refresh_ttl_ms() -> float:
    return max(0.0, float(getattr(settings, "MARKETIMMUNE_MARKOUT_DECISION_REFRESH_TTL_MS", 30000)))


def _resolved_gold_path() -> Path:
    configured = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_PATH")
    if not _auto_discover_gold():
        return configured

    search_dirs = [configured.parent if configured.suffix else configured]
    root = _configured_path("MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_ROOT")
    if root not in search_dirs:
        search_dirs.append(root)
    for directory in search_dirs:
        latest = _latest_gold_partition(directory)
        if latest is not None:
            return latest
    return configured


def _latest_gold_partition(directory: Path) -> Path | None:
    if directory.is_file():
        return directory
    if not directory.exists():
        return None
    candidates = [path for path in directory.rglob("*-training-*.parquet") if path.is_file()]
    return max(candidates, key=_gold_partition_sort_key, default=None)


def _gold_partition_sort_key(path: Path) -> tuple[str, int, str]:
    match = _GOLD_DATE_RE.search(path.name)
    date_key = match.group(1) if match else ""
    try:
        modified = path.stat().st_mtime_ns
    except OSError:
        modified = 0
    return (date_key, modified, str(path))


def _auto_discover_gold() -> bool:
    raw = str(getattr(settings, "MARKETIMMUNE_PROMOTED_MARKOUT_GOLD_AUTO_DISCOVER", "1"))
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _configured_path(name: str) -> Path:
    raw = str(getattr(settings, name))
    path = Path(raw)
    return path if path.is_absolute() else Path(settings.BASE_DIR) / path


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(settings.BASE_DIR).resolve()))
    except ValueError:
        return str(path)


def _timestamp(ts_ms: float) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).replace(tzinfo=None)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _start_refresh_run(
    *,
    trigger: str,
    source_path: Path,
    requested_limit: int,
) -> ScoredFillRefreshRun:
    return ScoredFillRefreshRun.objects.create(
        status="running",
        trigger=trigger,
        source_path=_display_path(source_path),
        requested_limit=requested_limit,
        started_at=_now(),
    )


def _finish_refresh_run(
    refresh_run: ScoredFillRefreshRun,
    *,
    status: str,
    refreshed_count: int = 0,
    message: str = "",
) -> DecisionRefresh:
    finished_at = _now()
    duration_ms = (finished_at - refresh_run.started_at.replace(tzinfo=None)).total_seconds()
    refresh_run.status = status
    refresh_run.refreshed_count = refreshed_count
    refresh_run.message = message
    refresh_run.finished_at = finished_at
    refresh_run.duration_ms = duration_ms * 1000.0
    refresh_run.save(
        update_fields=[
            "status",
            "refreshed_count",
            "message",
            "finished_at",
            "duration_ms",
        ]
    )
    return DecisionRefresh(
        attempted=True,
        refreshed_count=refreshed_count,
        message=message,
        source_path=refresh_run.source_path,
        status=status,
        run_id=refresh_run.id,
    )
