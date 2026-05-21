"""Service layer for the agentic immune loop.

Bridges the pure-Python :class:`ImmuneLoop` (no Django dependency)
and the Django ORM. Two responsibilities:

1. Build a loop (optionally seeding it with the existing memory
   shelf).
2. Persist the resulting :class:`LoopResult` across the seven new
   tables in :mod:`dashboard.models` inside a single atomic
   transaction.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from django.db import transaction

from dashboard.models import (
    AgentDecisionTraceRecord,
    AgentRunRecord,
    AgentToolCallRecord,
    ImmuneLoopRun,
    ImmuneMemoryEntry,
    InvestigationCaseRecord,
    ModelPromotionDecision,
    PolicyDecisionRecord,
    ScenarioProposalRecord,
)
from marketimmune.agentic import ImmuneLoop, ImmuneMemory, LoopResult, build_default_llm


class AgenticService:
    """High-level facade used by management commands and views."""

    @staticmethod
    def existing_memories() -> list[ImmuneMemory]:
        """Hydrate the long-term memory shelf into value objects."""
        out: list[ImmuneMemory] = []
        for row in ImmuneMemoryEntry.objects.all():
            out.append(ImmuneMemory(
                memory_id=row.memory_id,
                threat_name=row.threat_name,
                description=row.description,
                scenario_source=row.scenario_source,
                key_signals=tuple(row.key_signals or []),
                best_detector=row.best_detector,
                failed_detector=row.failed_detector,
                recommended_detector=row.recommended_detector,
                example_case_id=row.example_case_id,
                created_at=row.created_at.isoformat(),
                novelty_score=row.novelty_score,
                times_seen=row.times_seen,
            ))
        return out

    @staticmethod
    def run_once(
        *,
        difficulty: str = "medium",
        tick_limit: int = 60,
        enable_self_improvement: bool = True,
    ) -> ImmuneLoopRun:
        """Execute one full loop and persist every artifact."""
        existing = AgenticService.existing_memories()
        llm = build_default_llm()
        loop = ImmuneLoop.with_llm(llm) if llm.name != "null" else ImmuneLoop()
        loop.enable_self_improvement = enable_self_improvement
        # If the most recent ModelPromotionDecision was
        # `needs_more_data`, ask the trainer to retrain even when no
        # new memories arrived this loop.
        retrain_pending = AgenticService._latest_was_needs_more_data()
        started = time.perf_counter()
        result = loop.run(
            difficulty=difficulty,
            tick_limit=tick_limit,
            existing_memories=existing,
            retrain_pending=retrain_pending,
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        loop_row = AgenticService._persist(result, difficulty, duration_ms)
        loop_row.output_provider = llm.name  # type: ignore[attr-defined]
        return loop_row

    @staticmethod
    def _latest_was_needs_more_data() -> bool:
        latest = ModelPromotionDecision.objects.first()
        return bool(latest and latest.verdict == "needs_more_data")

    @staticmethod
    def _promote_candidate(job: Any) -> None:
        """Copy the candidate joblib over the incumbent path.

        The Trainer wrote the candidate into a temp dir; by the time we
        get here, the temp dir is gone. Until we wire a persistent
        candidate-store, "promote" really means "rerun the training
        script with the regular paths so the incumbent is refreshed".
        """
        import contextlib
        import subprocess
        import sys
        from pathlib import Path

        with contextlib.suppress(Exception):
            subprocess.run(
                [sys.executable, str(Path("scripts/train_risk_head.py"))],
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                timeout=120,
            )

    # ---- persistence -----------------------------------------------

    @staticmethod
    @transaction.atomic
    def _persist(
        result: LoopResult,
        difficulty: str,
        duration_ms: float,
    ) -> ImmuneLoopRun:
        loop_id = f"loop_{uuid.uuid4().hex[:12]}"
        first_run = result.agent_runs[0] if result.agent_runs else None
        last_run = result.agent_runs[-1] if result.agent_runs else None
        started_at = _to_aware(first_run.started_at) if first_run else _now()
        finished_at = _to_aware(last_run.finished_at) if last_run else _now()

        loop_row = ImmuneLoopRun.objects.create(
            loop_id=loop_id,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            difficulty=difficulty,
            aggregate_posture=result.aggregate_posture,
            proposal_name=result.proposal.name if result.proposal else "",
            new_memory_count=len(result.new_memories),
            alert_count=len(result.alerts),
            case_count=len(result.cases),
        )

        # 1. Per-agent traces.
        for agent_run in result.agent_runs:
            agent_row = AgentRunRecord.objects.create(
                loop=loop_row,
                run_id=agent_run.run_id,
                agent_name=agent_run.agent_name,
                goal=agent_run.goal,
                started_at=_to_aware(agent_run.started_at),
                finished_at=_to_aware(agent_run.finished_at),
                duration_ms=agent_run.duration_ms,
                success=agent_run.success,
                error=agent_run.error or "",
                output=_json_safe(agent_run.output),
                linked_artifacts=_json_safe_summary(agent_run.linked_artifacts),
            )
            AgentToolCallRecord.objects.bulk_create([
                AgentToolCallRecord(
                    agent_run=agent_row,
                    tool=tc.tool,
                    arguments=_json_safe(tc.arguments),
                    duration_ms=tc.duration_ms,
                    result_summary=tc.result_summary,
                    occurred_at=_to_aware(tc.occurred_at),
                ) for tc in agent_run.tool_calls
            ])
            AgentDecisionTraceRecord.objects.bulk_create([
                AgentDecisionTraceRecord(
                    agent_run=agent_row,
                    goal=tr.goal,
                    observation=tr.observation,
                    decision=tr.decision,
                    confidence=tr.confidence,
                    evidence=_json_safe(tr.evidence),
                    occurred_at=_to_aware(tr.occurred_at),
                ) for tr in agent_run.traces
            ])

        # 2. Loop-level artifacts.
        if result.proposal is not None:
            ScenarioProposalRecord.objects.create(
                loop=loop_row,
                proposal_id=result.proposal.proposal_id,
                name=result.proposal.name,
                base_scenario=result.proposal.base_scenario,
                cover_scenario=result.proposal.cover_scenario,
                expected_attack=result.proposal.expected_attack,
                evasion_strategy=result.proposal.evasion_strategy,
                difficulty=result.proposal.difficulty,
                # Stash provenance inside the features JSON so the UI
                # can show whether the rationale came from an LLM
                # without needing another migration.
                features={
                    **dict(result.proposal.features),
                    "rationale_source": result.proposal.rationale_source,
                },
                rationale=result.proposal.rationale,
            )

        InvestigationCaseRecord.objects.bulk_create([
            InvestigationCaseRecord(
                loop=loop_row,
                case_id=case.case_id,
                alert_id=case.alert_id,
                suspected_behavior=case.suspected_behavior,
                severity=case.severity,
                confidence=case.confidence,
                observation=case.observation,
                feature_evidence=dict(case.feature_evidence),
                # Embed the LLM-or-deterministic narrative inside the
                # JSONField so the template can show it without
                # requiring another migration.
                model_evidence={
                    **dict(case.model_evidence),
                    "narrative": case.narrative,
                    "narrative_source": case.narrative_source,
                },
                timeline=list(case.timeline),
                matched_rules=list(case.matched_rules),
                recommended_next_step=case.recommended_next_step,
                explanation=case.explanation,
            ) for case in result.cases
        ])

        PolicyDecisionRecord.objects.bulk_create([
            PolicyDecisionRecord(
                loop=loop_row,
                decision_id=dec.decision_id,
                case_id=dec.case_id,
                recommended_action=dec.recommended_action,
                severity=dec.severity,
                rationale=dec.rationale,
                confidence=dec.confidence,
            ) for dec in result.decisions
        ])

        # 3. Trainer + Judge artifacts (Day 2).
        if result.judge_verdict is not None:
            verdict = result.judge_verdict
            ModelPromotionDecision.objects.update_or_create(
                decision_id=verdict.decision_id,
                defaults={
                    "candidate_model": verdict.candidate_model,
                    "incumbent_model": verdict.incumbent_model,
                    "verdict": verdict.verdict,
                    "rationale": verdict.rationale,
                    "metrics": _json_safe(dict(verdict.metrics)) | {
                        "criteria": _json_safe(dict(verdict.criteria)),
                        "promote_votes": verdict.promote_votes,
                        "reject_votes": verdict.reject_votes,
                        "loop_id": loop_row.loop_id,
                    },
                },
            )
            # If the Judge said promote and the Trainer wrote a
            # candidate, copy the candidate over the incumbent. We do
            # this here (not inside an agent) because it is the only
            # side-effect that mutates the system of record.
            if verdict.verdict == "promote" and result.training_job is not None:
                AgenticService._promote_candidate(result.training_job)

        for mem in result.new_memories:
            ImmuneMemoryEntry.objects.update_or_create(
                memory_id=mem.memory_id,
                defaults={
                    "threat_name": mem.threat_name,
                    "description": mem.description,
                    "scenario_source": mem.scenario_source,
                    "key_signals": list(mem.key_signals),
                    "best_detector": mem.best_detector,
                    "failed_detector": mem.failed_detector,
                    "recommended_detector": mem.recommended_detector,
                    "example_case_id": mem.example_case_id,
                    "novelty_score": mem.novelty_score,
                    "times_seen": mem.times_seen,
                    "created_at": _parse_iso_or_now(mem.created_at),
                },
            )

        return loop_row


# ---------------------------------------------------------------------------
# Tiny helpers (kept module-private so they don't leak into the public API)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return naive UTC `datetime`.

    The project's Django settings leave ``USE_TZ`` off, so the SQLite
    backend rejects timezone-aware datetimes. We normalise to naive
    UTC at the DB boundary; the agent value objects upstream stay
    timezone-aware so anything that consumes them in JSON gets ISO
    strings with a ``+00:00`` suffix.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _to_aware(dt: datetime) -> datetime:
    """Normalise to naive UTC for storage."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _parse_iso_or_now(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except Exception:  # noqa: BLE001
        return _now()
    return _to_aware(parsed)


def _json_safe(value: Any) -> Any:
    """Drop non-serialisable artifacts so JSONField never crashes."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _json_safe_summary(value: Any) -> Any:
    """Like `_json_safe`, but collapses big objects to a short marker."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            else:
                out[k] = f"<{type(v).__name__}>"
        return out
    return _json_safe(value)
