"""Replay / cockpit simulator ORM models.

These back the ``/simulator/`` cockpit: a deterministic replay of Binance kline +
book-depth data with simulated agent overlays, per-state features, model
predictions, alerts, and decision-audit traces. Persisted via
``dashboard.services.simulator_service``.

Imported and re-exported by ``dashboard/models.py`` so Django registers these
under the ``dashboard`` app and existing migrations keep referencing them.
"""

from django.db import models


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
    session = models.ForeignKey(
        ReplaySession, on_delete=models.CASCADE, related_name='agent_orders'
    )
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
    session = models.ForeignKey(
        ReplaySession, on_delete=models.CASCADE, related_name='agent_trades'
    )
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
    session = models.ForeignKey(
        ReplaySession, on_delete=models.CASCADE, related_name='feature_snapshots'
    )
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
    session = models.ForeignKey(
        ReplaySession, on_delete=models.CASCADE, related_name='decision_traces'
    )
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
