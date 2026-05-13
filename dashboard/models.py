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
