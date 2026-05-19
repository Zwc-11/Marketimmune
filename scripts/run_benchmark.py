from __future__ import annotations

import argparse
import json
from pathlib import Path

from aegisbench.datasets.builder import build_examples, examples_to_rows
from aegisbench.datasets.splits import (
    deterministic_splits,
    has_scenario_leakage,
    require_non_empty_splits,
)
from aegisbench.leaderboard.csv import write_leaderboard
from aegisbench.reports.json_report import write_json_report, write_markdown_report
from aegisbench.tasks.action_selection import ActionSelectionTask
from aegisbench.tasks.early_warning import EarlyWarningTask
from aegisbench.tasks.event_detection import EventDetectionTask
from aegisbench.tasks.harm_estimation import HarmEstimationTask
from aegisbench.tasks.ood_detection import OODDetectionTask
from aegisbench.tasks.session_classification import SessionClassificationTask
from marketimmune.policy.rules import PolicyAction, RuleEngine


def rule_scores(examples: list) -> list[float]:  # type: ignore[type-arg]
    engine = RuleEngine()
    scores: list[float] = []
    for example in examples:
        decision = engine.decide(example.features)
        if decision.action is PolicyAction.BLOCK:
            scores.append(1.0)
        elif decision.action is PolicyAction.ALERT:
            scores.append(0.5)
        else:
            scores.append(0.0)
    return scores


def calibrate_block_threshold(
    examples: list,  # type: ignore[type-arg]
    scores: list[float],
    false_blocks_per_100k_budget: float = 1000.0,
) -> float:
    candidates = sorted(set(scores + [1.1]), reverse=True)
    benign = [not example.unsafe for example in examples]
    for threshold in candidates:
        false_blocks = sum(
            score >= threshold
            for score, is_benign in zip(scores, benign, strict=True)
            if is_benign
        )
        benign_count = sum(benign)
        per_100k = false_blocks * 100_000 / max(benign_count, 1)
        if per_100k <= false_blocks_per_100k_budget:
            return threshold
    return 1.1


def apply_block_threshold(scores: list[float], threshold: float) -> list[float]:
    return [1.0 if score >= threshold else min(score, 0.5) for score in scores]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AegisBench phase-7 benchmark.")
    parser.add_argument("--scenario-root", default="reports/phase5/scenarios")
    parser.add_argument("--output-dir", default="reports/phase7")
    args = parser.parse_args()

    examples = build_examples(Path(args.scenario_root))
    splits = require_non_empty_splits(deterministic_splits(examples))
    leakage = has_scenario_leakage(splits)
    evaluation_examples = splits["test"]
    validation_scores = rule_scores(splits["validation"])
    block_threshold = calibrate_block_threshold(splits["validation"], validation_scores)
    scores = apply_block_threshold(rule_scores(evaluation_examples), block_threshold)
    tasks = [
        EventDetectionTask(),
        SessionClassificationTask(),
        EarlyWarningTask(),
        ActionSelectionTask(),
        HarmEstimationTask(),
        OODDetectionTask(),
    ]
    metrics = {task.name: task.evaluate(evaluation_examples, scores) for task in tasks}
    output_dir = Path(args.output_dir)
    report = {
        "examples": len(examples),
        "splits": {name: len(rows) for name, rows in splits.items()},
        "scenario_leakage": leakage,
        "rule_calibration": {
            "block_threshold": block_threshold,
            "false_blocks_per_100k_budget": 1000.0,
        },
        "tasks": metrics,
    }
    write_json_report(output_dir / "benchmark_report.json", report)
    write_json_report(output_dir / "dataset_rows.json", {"rows": examples_to_rows(examples)})
    write_markdown_report(output_dir / "benchmark_report.md", "AegisBench Phase 7", metrics)
    write_leaderboard(
        output_dir / "leaderboard.csv",
        [{"model": "RuleEngine", "task": task, **values} for task, values in metrics.items()],
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not leakage and len(metrics) >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
