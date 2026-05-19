from __future__ import annotations

from aegisbench.datasets.builder import BenchmarkExample
from aegisbench.metrics.classification import auroc, pr_auc


class OODDetectionTask:
    name = "ood_detection"

    def __init__(self, ood_families: set[str] | None = None) -> None:
        self.ood_families = ood_families or {
            "latency_edge",
            "volatility_feedback",
        }

    def evaluate(self, examples: list[BenchmarkExample], scores: list[float]) -> dict[str, float]:
        labels = [example.family in self.ood_families for example in examples]
        return {"pr_auc": pr_auc(scores, labels), "auroc": auroc(scores, labels)}
