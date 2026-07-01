"""Agentic immune-loop audit-log ORM models.

The append-only record of every immune-loop run: each agent invocation, its tool
calls and decision traces, the red-team proposal, investigation cases, policy
decisions, the long-term threat memory, and model-promotion verdicts. Written by
``dashboard.services.agentic_service``. This is the project's most defensible
capability (see RESUME_BULLETS.md bullet 2).

Imported and re-exported by ``dashboard/models.py`` so Django registers these
under the ``dashboard`` app and existing migrations keep referencing them.
"""

from django.db import models


class ImmuneLoopRun(models.Model):
    """One full execution of the agentic immune loop."""

    loop_id = models.CharField(max_length=100, unique=True)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    duration_ms = models.FloatField()
    difficulty = models.CharField(max_length=20, default='medium')
    aggregate_posture = models.CharField(max_length=40, default='no_action')
    proposal_name = models.CharField(max_length=200, blank=True, default='')
    new_memory_count = models.IntegerField(default=0)
    alert_count = models.IntegerField(default=0)
    case_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f"ImmuneLoopRun {self.loop_id} ({self.aggregate_posture})"


class AgentRunRecord(models.Model):
    """One agent invocation inside an ImmuneLoopRun."""

    loop = models.ForeignKey(ImmuneLoopRun, on_delete=models.CASCADE, related_name='agent_runs')
    run_id = models.CharField(max_length=100)
    agent_name = models.CharField(max_length=100)
    goal = models.CharField(max_length=200)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    duration_ms = models.FloatField()
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True, default='')
    output = models.JSONField(default=dict)
    linked_artifacts = models.JSONField(default=dict)

    class Meta:
        ordering = ['started_at']

    def __str__(self) -> str:
        return f"{self.agent_name} {self.run_id}"


class AgentToolCallRecord(models.Model):
    """Persisted ToolCall produced by an agent."""

    agent_run = models.ForeignKey(
        AgentRunRecord, on_delete=models.CASCADE, related_name='tool_calls'
    )
    tool = models.CharField(max_length=160)
    arguments = models.JSONField(default=dict)
    duration_ms = models.FloatField(default=0.0)
    result_summary = models.CharField(max_length=400, blank=True, default='')
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ['occurred_at']


class AgentDecisionTraceRecord(models.Model):
    """Persisted DecisionTrace produced by an agent."""

    agent_run = models.ForeignKey(
        AgentRunRecord, on_delete=models.CASCADE, related_name='decision_traces'
    )
    goal = models.CharField(max_length=200)
    observation = models.TextField()
    decision = models.CharField(max_length=200)
    confidence = models.FloatField(default=0.5)
    evidence = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ['occurred_at']


class ScenarioProposalRecord(models.Model):
    """Persisted ScenarioProposal emitted by the RedTeamScenarioAgent."""

    loop = models.ForeignKey(ImmuneLoopRun, on_delete=models.CASCADE, related_name='proposals')
    proposal_id = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    base_scenario = models.CharField(max_length=100)
    cover_scenario = models.CharField(max_length=100, blank=True, null=True)
    expected_attack = models.CharField(max_length=200)
    evasion_strategy = models.CharField(max_length=400, blank=True, default='')
    difficulty = models.CharField(max_length=20, default='medium')
    features = models.JSONField(default=dict)
    rationale = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class InvestigationCaseRecord(models.Model):
    """Persisted InvestigationCase emitted by the InvestigatorAgent."""

    loop = models.ForeignKey(ImmuneLoopRun, on_delete=models.CASCADE, related_name='cases')
    case_id = models.CharField(max_length=120, db_index=True)
    alert_id = models.CharField(max_length=120)
    suspected_behavior = models.CharField(max_length=160)
    severity = models.CharField(max_length=20)
    confidence = models.FloatField()
    observation = models.TextField()
    feature_evidence = models.JSONField(default=dict)
    model_evidence = models.JSONField(default=dict)
    timeline = models.JSONField(default=list)
    matched_rules = models.JSONField(default=list)
    recommended_next_step = models.CharField(max_length=400)
    explanation = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class PolicyDecisionRecord(models.Model):
    """Persisted PolicyDecision emitted by the PolicyAgent."""

    loop = models.ForeignKey(
        ImmuneLoopRun, on_delete=models.CASCADE, related_name='policy_decisions'
    )
    decision_id = models.CharField(max_length=120, db_index=True)
    case_id = models.CharField(max_length=120)
    recommended_action = models.CharField(max_length=60)
    severity = models.CharField(max_length=20)
    rationale = models.TextField()
    confidence = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ImmuneMemoryEntry(models.Model):
    """Persisted ImmuneMemory entries — the long-term threat library."""

    memory_id = models.CharField(max_length=120, unique=True)
    threat_name = models.CharField(max_length=160)
    description = models.TextField()
    scenario_source = models.CharField(max_length=200)
    key_signals = models.JSONField(default=list)
    best_detector = models.CharField(max_length=120)
    failed_detector = models.CharField(max_length=120)
    recommended_detector = models.CharField(max_length=120)
    example_case_id = models.CharField(max_length=120, blank=True, default='')
    novelty_score = models.FloatField(default=0.0)
    times_seen = models.IntegerField(default=1)
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_seen_at']

    def __str__(self) -> str:
        return f"ImmuneMemoryEntry {self.threat_name} ({self.memory_id})"


class ModelPromotionDecision(models.Model):
    """Stubbed Day-2 record: BenchmarkJudge promote/reject decisions."""

    decision_id = models.CharField(max_length=120, unique=True)
    candidate_model = models.CharField(max_length=120)
    incumbent_model = models.CharField(max_length=120, blank=True, default='')
    verdict = models.CharField(max_length=40)  # promote / reject / needs_more_data
    rationale = models.TextField(blank=True, default='')
    metrics = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ScoredFillDecision(models.Model):
    """Persisted promoted-model decision for one real Hyperliquid maker fill."""

    loop = models.ForeignKey(
        ImmuneLoopRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scored_fill_decisions',
    )
    decision_id = models.CharField(max_length=180, unique=True)
    coin = models.CharField(max_length=30)
    ts_ms = models.FloatField()
    timestamp = models.DateTimeField(db_index=True)
    px = models.FloatField()
    sz = models.FloatField()
    side = models.CharField(max_length=20, blank=True, default='')
    maker_side = models.IntegerField()
    model_name = models.CharField(max_length=200, db_index=True)
    raw_score = models.FloatField()
    calibrated_score = models.FloatField()
    decision_threshold = models.FloatField(null=True, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    severity = models.CharField(max_length=20, db_index=True)
    markout_bps = models.FloatField(null=True, blank=True)
    toxic = models.BooleanField(null=True, blank=True)
    tid = models.BigIntegerField(null=True, blank=True)
    oid = models.BigIntegerField(null=True, blank=True)
    feature_values = models.JSONField(default=dict)
    top_features = models.JSONField(default=list)
    source_path = models.CharField(max_length=500, blank=True, default='')
    case_id = models.CharField(max_length=160, blank=True, default='')
    policy_decision_id = models.CharField(max_length=160, blank=True, default='')
    recommended_action = models.CharField(max_length=80, blank=True, default='')
    scored_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self) -> str:
        return f"ScoredFillDecision {self.decision_id} ({self.action})"


class ScoredFillDecisionLink(models.Model):
    """Audit edge from one scored fill to a loop/case/policy action."""

    decision = models.ForeignKey(
        ScoredFillDecision,
        on_delete=models.CASCADE,
        related_name='loop_links',
    )
    loop = models.ForeignKey(
        ImmuneLoopRun,
        on_delete=models.CASCADE,
        related_name='scored_fill_links',
    )
    case_id = models.CharField(max_length=160, db_index=True)
    policy_decision_id = models.CharField(max_length=160, blank=True, default='')
    recommended_action = models.CharField(max_length=80, blank=True, default='')
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-linked_at']
        constraints = [
            models.UniqueConstraint(
                fields=['decision', 'loop', 'case_id'],
                name='uniq_scored_fill_loop_case',
            ),
        ]

    def __str__(self) -> str:
        return f"ScoredFillDecisionLink {self.decision_id} -> {self.loop_id}"


class ScoredFillRefreshRun(models.Model):
    """One promoted-fill scoring refresh attempt."""

    status = models.CharField(max_length=20, db_index=True)
    trigger = models.CharField(max_length=30, db_index=True, default='manual')
    source_path = models.CharField(max_length=500, blank=True, default='')
    requested_limit = models.IntegerField(default=0)
    refreshed_count = models.IntegerField(default=0)
    message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f"ScoredFillRefreshRun {self.status} ({self.refreshed_count})"


class HyperliquidBackfillJob(models.Model):
    """Operator-visible requester-pays Hyperliquid backfill job."""

    job_id = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=20, db_index=True)
    trigger = models.CharField(max_length=30, db_index=True, default='manual')
    coin = models.CharField(max_length=30, db_index=True)
    date = models.CharField(max_length=8, db_index=True)
    hours = models.JSONField(default=list)
    fill_suffixes = models.JSONField(default=list)
    lake_root = models.CharField(max_length=500, default='data/hyperliquid')
    include_asset_ctxs = models.BooleanField(default=True)
    refresh_decisions = models.BooleanField(default=True)
    dry_run = models.BooleanField(default=False)
    book_snapshots = models.IntegerField(default=0)
    asset_contexts = models.IntegerField(default=0)
    fills = models.IntegerField(default=0)
    gold_rows = models.IntegerField(default=0)
    training_rows = models.IntegerField(default=0)
    writes = models.JSONField(default=list)
    refresh_run_id = models.IntegerField(null=True, blank=True)
    message = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.FloatField(default=0.0)

    class Meta:
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f"HyperliquidBackfillJob {self.job_id} ({self.status})"
