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
