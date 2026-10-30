"""Persisted state behind the API: scored fills, scoring refreshes, backfill jobs."""

from django.db import models


class ScoredFillDecision(models.Model):
    """Persisted promoted-model decision for one real Hyperliquid maker fill."""

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
    scored_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self) -> str:
        return f"ScoredFillDecision {self.decision_id} ({self.action})"


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
    lake_root = models.CharField(max_length=500, default='data')
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
