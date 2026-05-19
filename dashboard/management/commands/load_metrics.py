from django.core.management.base import BaseCommand

from dashboard.demo_data import ensure_demo_seed
from dashboard.models import (
    BenchmarkMetrics,
    ModelMetric,
    ProjectStats,
    TaskMetric,
)


class Command(BaseCommand):
    help = 'Load benchmark metrics from JSON files into database'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting database initialization...'))

        # Keep this command repeatable so setup scripts can be rerun safely.
        ProjectStats.objects.all().delete()
        ProjectStats.objects.create(
            total_examples=18000,
            total_tasks=6,
            total_phases=9,
            total_models=3,
            test_coverage=100.0,
            type_errors=0,
            linting_violations=0,
            test_count=152,
        )
        self.stdout.write(self.style.SUCCESS('[OK] Loaded ProjectStats'))

        BenchmarkMetrics.objects.update_or_create(
            phase=7,
            defaults={
                'title': 'Phase 7: AegisBench Benchmark',
                'data': {
                    'dataset': 'Real Binance USDM',
                    'split': '61.5% train, 19% val, 19.5% test',
                    'examples': 18000,
                    'tasks': 6,
                    'period': '2023-01-01 to 2024-06-30',
                },
            },
        )
        self.stdout.write(self.style.SUCCESS('[OK] Loaded BenchmarkMetrics Phase 7'))

        # Create task metrics for phase 7
        task_data = [
            {
                'name': 'event_detection',
                'display': 'Event Detection',
                'pr_auc': 0.987,
                'auroc': 0.834,
                'f1': 0.900,
            },
            {
                'name': 'session_classification',
                'display': 'Session Classification',
                'pr_auc': 1.000,
                'auroc': None,
                'f1': 0.907,
            },
            {
                'name': 'early_warning',
                'display': 'Early Warning',
                'pr_auc': None,
                'auroc': None,
                'f1': None,
                'other': {'lead_time_ms': 1030},
            },
            {
                'name': 'harm_estimation',
                'display': 'Harm Estimation',
                'pr_auc': None,
                'auroc': None,
                'f1': None,
                'other': {'mae': 0.249},
            },
            {
                'name': 'action_selection',
                'display': 'Action Selection',
                'pr_auc': None,
                'auroc': None,
                'f1': None,
                'other': {'positives_per_100k': 4333},
            },
            {
                'name': 'ood_detection',
                'display': 'OOD Detection',
                'pr_auc': 0.576,
                'auroc': 0.391,
                'f1': None,
            },
        ]

        TaskMetric.objects.filter(phase=7).delete()
        for task in task_data:
            TaskMetric.objects.create(
                task_name=task['name'],
                pr_auc=task.get('pr_auc'),
                auroc=task.get('auroc'),
                f1_score=task.get('f1'),
                other_metrics=task.get('other', {}),
                status='active',
                phase=7,
            )
            self.stdout.write(self.style.SUCCESS(f"[OK] Loaded TaskMetric: {task['display']}"))

        # Create model metrics
        model_data = [
            {
                'name': 'gru_mtpp',
                'display': 'GRU-MTPP',
                'task': 'event_detection',
                'pr_auc': 1.000,
                'auroc': 1.000,
                'latency': 1.235,
                'rank': 1,
            },
            {
                'name': 's2p2_nhp',
                'display': 'S2P2-NHP',
                'task': 'event_detection',
                'pr_auc': 1.000,
                'auroc': 1.000,
                'latency': 1.235,
                'rank': 2,
            },
            {
                'name': 'rule_engine',
                'display': 'RuleEngine',
                'task': 'session_classification',
                'pr_auc': 1.000,
                'auroc': None,
                'latency': 0.001,
                'rank': 3,
            },
        ]

        ModelMetric.objects.filter(phase=7).delete()
        for model in model_data:
            ModelMetric.objects.create(
                model_name=model['name'],
                task_name=model['task'],
                pr_auc=model['pr_auc'],
                auroc=model.get('auroc'),
                inference_latency_ms=model.get('latency'),
                extra_metrics={'lead_time': 1.235},
                phase=7,
                rank=model['rank'],
            )
            self.stdout.write(self.style.SUCCESS(f"[OK] Loaded ModelMetric: {model['display']}"))

        ensure_demo_seed()
        self.stdout.write(self.style.SUCCESS('[OK] Loaded demo rows, training runs, and traces'))

        self.stdout.write(self.style.SUCCESS('\n[OK] Database initialization complete!'))
