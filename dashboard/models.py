from django.db import models


class BenchmarkMetrics(models.Model):
    """Store benchmark phase metrics"""
    phase = models.IntegerField(unique=True)
    title = models.CharField(max_length=200)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['phase']
        verbose_name_plural = 'Benchmark Metrics'

    def __str__(self):
        return f"Phase {self.phase}: {self.title}"


class TaskMetric(models.Model):
    """Store individual task metrics"""
    TASKS = [
        ('event_detection', 'Event Detection'),
        ('session_classification', 'Session Classification'),
        ('early_warning', 'Early Warning'),
        ('harm_estimation', 'Harm Estimation'),
        ('action_selection', 'Action Selection'),
        ('ood_detection', 'OOD Detection'),
    ]
    
    task_name = models.CharField(max_length=50, choices=TASKS)
    pr_auc = models.FloatField(null=True, blank=True)
    auroc = models.FloatField(null=True, blank=True)
    f1_score = models.FloatField(null=True, blank=True)
    other_metrics = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default='active')
    phase = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['phase', 'task_name']

    def __str__(self):
        return f"{self.get_task_name_display()} (Phase {self.phase})"


class ModelMetric(models.Model):
    """Store model performance metrics"""
    MODELS = [
        ('rule_engine', 'RuleEngine Baseline'),
        ('gru_mtpp', 'GRU-MTPP'),
        ('s2p2_nhp', 'S2P2 (Neural Hawkes)'),
    ]
    
    model_name = models.CharField(max_length=50, choices=MODELS)
    task_name = models.CharField(max_length=50)
    pr_auc = models.FloatField()
    auroc = models.FloatField(null=True, blank=True)
    inference_latency_ms = models.FloatField(null=True, blank=True)
    extra_metrics = models.JSONField(default=dict)
    phase = models.IntegerField()
    rank = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f"{self.get_model_name_display()} - {self.task_name}"


class ProjectStats(models.Model):
    """Store overall project statistics"""
    total_examples = models.IntegerField()
    total_tasks = models.IntegerField()
    total_phases = models.IntegerField()
    total_models = models.IntegerField()
    test_coverage = models.FloatField()
    type_errors = models.IntegerField()
    linting_violations = models.IntegerField()
    test_count = models.IntegerField()
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Project Stats'

    def __str__(self):
        return f"Project Statistics (Updated: {self.last_updated})"


class DemoMarketEvent(models.Model):
    """One simulated market microstructure snapshot for the visual demo."""

    timestamp = models.DateTimeField()
    symbol = models.CharField(max_length=20, default='BTCUSDT')
    mid_price = models.FloatField()
    bid_price = models.FloatField()
    ask_price = models.FloatField()
    spread_bps = models.FloatField()
    source = models.CharField(max_length=40, default='demo_simulator')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.symbol} {self.mid_price:.2f} at {self.timestamp}"


class DemoAgentEvent(models.Model):
    """Synthetic autonomous-agent order event paired with a market snapshot."""

    market_event = models.ForeignKey(
        DemoMarketEvent,
        on_delete=models.CASCADE,
        related_name='agent_events',
    )
    agent_id = models.CharField(max_length=40)
    strategy = models.CharField(max_length=80)
    simulated_order = models.CharField(max_length=160)
    simulated_trade = models.CharField(max_length=160)
    side = models.CharField(max_length=8)
    quantity = models.FloatField()
    order_price = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-market_event__timestamp']

    def __str__(self):
        return f"{self.agent_id} {self.side} {self.quantity}"


class DemoFeatureRow(models.Model):
    """Feature row produced from the market and synthetic agent event."""

    market_event = models.ForeignKey(
        DemoMarketEvent,
        on_delete=models.CASCADE,
        related_name='feature_rows',
    )
    features = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-market_event__timestamp']

    def __str__(self):
        return f"Features for event {self.market_event_id}"


class DemoPrediction(models.Model):
    """Model prediction generated from the current feature row."""

    feature_row = models.ForeignKey(
        DemoFeatureRow,
        on_delete=models.CASCADE,
        related_name='predictions',
    )
    model_name = models.CharField(max_length=80)
    risk_score = models.FloatField()
    risk_label = models.CharField(max_length=30)
    explanation = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.model_name}: {self.risk_label} ({self.risk_score:.2f})"


class DemoAlert(models.Model):
    """Risk alert emitted when the demo prediction crosses a threshold."""

    prediction = models.ForeignKey(
        DemoPrediction,
        on_delete=models.CASCADE,
        related_name='alerts',
    )
    severity = models.CharField(max_length=20)
    message = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.severity}: {self.message}"


class DemoTrainingRun(models.Model):
    """Human-readable training history for the demo dashboard."""

    model_name = models.CharField(max_length=80)
    dataset_version = models.CharField(max_length=80)
    split_summary = models.CharField(max_length=120)
    pr_auc = models.FloatField()
    f1 = models.FloatField()
    precision = models.FloatField()
    recall = models.FloatField()
    lead_time_ms = models.FloatField()
    artifact_path = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['model_name']

    def __str__(self):
        return f"{self.model_name} on {self.dataset_version}"


class DemoAgentTrace(models.Model):
    """Structured reasoning trace for recruiter-facing agent explainability."""

    prediction = models.ForeignKey(
        DemoPrediction,
        on_delete=models.CASCADE,
        related_name='agent_traces',
    )
    observation = models.TextField()
    risk_evidence = models.JSONField(default=list)
    decision = models.CharField(max_length=160)
    action = models.CharField(max_length=160)
    confidence = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.decision} ({self.confidence:.2f})"


class ReplaySession(models.Model):
    """Stores replay session parameters and run identification."""
    run_id = models.CharField(max_length=100, unique=True)
    symbol = models.CharField(max_length=20, default='BTCUSDT')
    scenario_name = models.CharField(max_length=100)
    started_at = models.DateTimeField(auto_now_add=True)
    speed = models.IntegerField(default=1)
    status = models.CharField(max_length=20, default='completed')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Session {self.run_id} ({self.scenario_name})"


class ReplayEvent(models.Model):
    """Stores normalized replay events representing historical BTC data."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='events')
    event_id = models.CharField(max_length=100)
    timestamp = models.DateTimeField()
    symbol = models.CharField(max_length=20)
    event_type = models.CharField(max_length=50)
    price = models.FloatField(null=True, blank=True)
    quantity = models.FloatField(null=True, blank=True)
    bid = models.FloatField(null=True, blank=True)
    ask = models.FloatField(null=True, blank=True)
    mid_price = models.FloatField(null=True, blank=True)
    spread = models.FloatField(null=True, blank=True)
    volume = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=50)
    raw_payload = models.JSONField(default=dict)
    # Real OHLC pulled straight from the Binance kline parquet so the
    # cockpit can render honest candles instead of synthesising them.
    open_price = models.FloatField(null=True, blank=True)
    high_price = models.FloatField(null=True, blank=True)
    low_price = models.FloatField(null=True, blank=True)
    # Aggregated L2 snapshot from Binance bookDepth parquet aligned to
    # this event's minute. Each entry is {"percentage": float, "depth":
    # float, "notional": float}. Empty list when no depth file is present.
    depth_levels = models.JSONField(default=list)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Event {self.event_type} at {self.timestamp}"


class ReplayCursor(models.Model):
    """Maintains the active replay pointer state for a session."""
    session = models.OneToOneField(ReplaySession, on_delete=models.CASCADE, related_name='cursor')
    current_index = models.IntegerField(default=0)
    current_timestamp = models.DateTimeField()
    total_events = models.IntegerField(default=0)

    def __str__(self):
        return f"Cursor for {self.session.run_id}: index {self.current_index}/{self.total_events}"


class SimulatedAgentOrder(models.Model):
    """Contains simulated agent order overlay information."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='agent_orders')
    event_id = models.CharField(max_length=100)
    order_id = models.CharField(max_length=100)
    agent_id = models.CharField(max_length=100)
    strategy = models.CharField(max_length=100)
    timestamp = models.DateTimeField()
    side = models.CharField(max_length=20)
    price = models.FloatField()
    quantity = models.FloatField()
    remaining_quantity = models.FloatField()
    status = models.CharField(max_length=20, default='new')

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"AgentOrder {self.order_id} ({self.side} {self.quantity})"


class SimulatedAgentTrade(models.Model):
    """Contains simulated agent fills / completed trade markers."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='agent_trades')
    trade_id = models.CharField(max_length=100)
    order_id = models.CharField(max_length=100)
    agent_id = models.CharField(max_length=100)
    timestamp = models.DateTimeField()
    price = models.FloatField()
    quantity = models.FloatField()
    side = models.CharField(max_length=20)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"AgentTrade {self.trade_id} @ {self.price}"


class FeatureSnapshot(models.Model):
    """Multi-window multi-modal features evaluated for each replay state."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='feature_snapshots')
    timestamp = models.DateTimeField()
    features = models.JSONField(default=dict)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Features for {self.session_id} @ {self.timestamp}"


class ModelPrediction(models.Model):
    """Machine learning model outputs and evaluation scores."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='predictions')
    timestamp = models.DateTimeField()
    model_name = models.CharField(max_length=100)
    risk_score = models.FloatField()
    risk_label = models.CharField(max_length=50)
    explanation = models.TextField()
    confidence = models.FloatField(default=1.0)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Prediction {self.model_name}: {self.risk_score} ({self.risk_label})"


class RiskAlert(models.Model):
    """Triggered risk warnings matching rules or high scores."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='alerts')
    timestamp = models.DateTimeField()
    severity = models.CharField(max_length=20)
    message = models.TextField()
    metric_name = models.CharField(max_length=100, null=True, blank=True)
    metric_value = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Alert [{self.severity}] {self.message}"


class DecisionAuditTrace(models.Model):
    """Full decision explanations mapping labels/features to policy control action."""
    session = models.ForeignKey(ReplaySession, on_delete=models.CASCADE, related_name='decision_traces')
    timestamp = models.DateTimeField()
    observation = models.TextField()
    feature_evidence = models.JSONField(default=dict)
    model_interpretation = models.TextField()
    policy_decision = models.CharField(max_length=100)
    recommended_control = models.CharField(max_length=200)
    linked_event_id = models.CharField(max_length=100, blank=True, default='')
    linked_prediction_id = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Audit {self.policy_decision} at {self.timestamp}"


# ---------------------------------------------------------------------------
# Agentic loop persistence
# ---------------------------------------------------------------------------


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

    agent_run = models.ForeignKey(AgentRunRecord, on_delete=models.CASCADE, related_name='tool_calls')
    tool = models.CharField(max_length=160)
    arguments = models.JSONField(default=dict)
    duration_ms = models.FloatField(default=0.0)
    result_summary = models.CharField(max_length=400, blank=True, default='')
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ['occurred_at']


class AgentDecisionTraceRecord(models.Model):
    """Persisted DecisionTrace produced by an agent."""

    agent_run = models.ForeignKey(AgentRunRecord, on_delete=models.CASCADE, related_name='decision_traces')
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
    case_id = models.CharField(max_length=120, unique=True)
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

    loop = models.ForeignKey(ImmuneLoopRun, on_delete=models.CASCADE, related_name='policy_decisions')
    decision_id = models.CharField(max_length=120, unique=True)
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

