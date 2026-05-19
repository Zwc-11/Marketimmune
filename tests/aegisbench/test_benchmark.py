from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisbench.datasets.builder import BenchmarkExample, build_examples, examples_to_rows
from aegisbench.datasets.splits import (
    deterministic_splits,
    has_scenario_leakage,
    require_non_empty_splits,
    split_name,
)
from aegisbench.leaderboard.csv import write_leaderboard
from aegisbench.metrics.classification import auroc, f1_at_threshold, pr_auc, precision_at_k
from aegisbench.reports.json_report import write_json_report, write_markdown_report
from aegisbench.tasks.action_selection import ActionSelectionTask
from aegisbench.tasks.early_warning import EarlyWarningTask
from aegisbench.tasks.event_detection import EventDetectionTask
from aegisbench.tasks.harm_estimation import HarmEstimationTask
from aegisbench.tasks.ood_detection import OODDetectionTask
from aegisbench.tasks.session_classification import SessionClassificationTask
from marketimmune.scenarios.config import ScenarioConfig
from marketimmune.scenarios.generator import generate_scenario
from marketimmune.schemas.events import AggTradeEvent

NOW = datetime(2024, 5, 1, tzinfo=UTC)


def sample_examples() -> list[BenchmarkExample]:
    return [
        BenchmarkExample("s1", "e1", 0.0, "quote_stuffing", True, {"x": 1.0}),
        BenchmarkExample("s1", "e2", 100.0, "quote_stuffing", True, {"x": 2.0}),
        BenchmarkExample("s2", "e3", 0.0, "passive_market_maker", False, {"x": 0.0}),
        BenchmarkExample("s3", "e4", 0.0, "momentum_ignition", True, {"x": 3.0}),
    ]


def test_build_examples_and_rows(tmp_path: Path) -> None:
    scenario = generate_scenario(
        ScenarioConfig(
            scenario_id="scenario-a",
            family="quote_stuffing",
            seed=1,
            start=NOW,
            mid_price=65000,
            event_count=3,
            unsafe=True,
        )
    )
    scenario.write(tmp_path)
    examples = build_examples(tmp_path)
    assert len(examples) == 3
    assert examples_to_rows(examples)[0]["scenario_id"] == "scenario-a"
    assert examples[0].mark.startswith("agent_order:new:")


def test_build_examples_uses_event_labels_not_manifest(tmp_path: Path) -> None:
    scenario = generate_scenario(
        ScenarioConfig(
            scenario_id="scenario-label-source",
            family="quote_stuffing",
            seed=1,
            start=NOW,
            mid_price=65000,
            event_count=2,
            unsafe=True,
        )
    )
    scenario.write(tmp_path)
    manifest_path = tmp_path / "scenario-label-source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unsafe"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    examples = build_examples(tmp_path)
    assert any(example.unsafe for example in examples)


def test_build_examples_rejects_non_agent_events(tmp_path: Path) -> None:
    event = AggTradeEvent(
        symbol="BTCUSDT",
        timestamp=NOW,
        sequence=0,
        aggregate_trade_id=1,
        price=1,
        quantity=1,
        first_trade_id=1,
        last_trade_id=1,
        is_buyer_maker=True,
    )
    scenario_id = "scenario-b"
    (tmp_path / f"{scenario_id}_events.json").write_text(
        json.dumps([event.model_dump(mode="json")]),
        encoding="utf-8",
    )
    (tmp_path / f"{scenario_id}_manifest.json").write_text(
        json.dumps({"family": "bad", "unsafe": False}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected agent order"):
        build_examples(tmp_path)


def test_splits_are_deterministic_and_detect_leakage() -> None:
    examples = sample_examples()
    assert split_name("s1") == split_name("s1")
    seen_splits = {split_name(f"scenario-{index}") for index in range(100)}
    assert seen_splits == {"train", "validation", "test"}
    splits = deterministic_splits(examples)
    assert not has_scenario_leakage(splits)
    complete_splits = deterministic_splits(
        [
            BenchmarkExample(f"scenario-{index}", f"e-{index}", 0.0, "quote_stuffing", True, {})
            for index in range(100)
        ]
    )
    assert require_non_empty_splits(complete_splits) is complete_splits
    with pytest.raises(ValueError, match="empty benchmark split"):
        require_non_empty_splits({"train": examples, "validation": [], "test": []})
    assert has_scenario_leakage(
        {
            "train": [examples[0]],
            "validation": [examples[1]],
            "test": [],
        }
    )


def test_classification_metrics_and_errors() -> None:
    scores = [1.0, 0.8, 0.1]
    labels = [True, True, False]
    assert pr_auc(scores, labels) == 1.0
    assert auroc(scores, labels) == 1.0
    assert auroc([0.5, 0.5, 0.1], [True, False, False]) == 0.75
    assert f1_at_threshold(scores, labels) == 1.0
    assert precision_at_k(scores, labels, 2) == 1.0
    assert pr_auc([0.1], [False]) == 0.0
    assert auroc([0.1], [False]) == 0.0
    with pytest.raises(ValueError):
        pr_auc([0.1], [True, False])
    with pytest.raises(ValueError):
        auroc([0.1], [True, False])
    with pytest.raises(ValueError):
        f1_at_threshold([0.1], [True, False])
    with pytest.raises(ValueError):
        precision_at_k([0.1], [True], 0)


def test_tasks_evaluate() -> None:
    examples = sample_examples()
    scores = [0.9, 0.8, 0.1, 0.7]
    assert EventDetectionTask().evaluate(examples, scores)["pr_auc"] > 0
    assert SessionClassificationTask().evaluate(examples, scores)["f1"] > 0
    assert EarlyWarningTask().evaluate(examples, scores)["sessions_warned"] == 2
    assert ActionSelectionTask().evaluate(examples, scores)["false_blocks_per_100k"] == 0
    assert HarmEstimationTask().evaluate(examples, scores)["mae"] >= 0
    assert OODDetectionTask({"momentum_ignition"}).evaluate(examples, scores)["pr_auc"] > 0


def test_harm_estimation_single_example_and_rank_error() -> None:
    example = BenchmarkExample("s", "e", 0.0, "quote_stuffing", True, {})
    assert HarmEstimationTask().evaluate([example], [1.0])["rank_correlation"] == 0.0
    with pytest.raises(ValueError):
        from aegisbench.tasks.harm_estimation import _spearman

        _spearman([1.0], [1.0, 0.0])


def test_early_warning_without_warning() -> None:
    examples = [BenchmarkExample("s", "e", 0.0, "quote_stuffing", True, {})]
    metrics = EarlyWarningTask().evaluate(examples, [0.1])
    assert metrics["mean_lead_time_ms"] == 0.0


def test_report_and_leaderboard_writers(tmp_path: Path) -> None:
    write_json_report(tmp_path / "report.json", {"x": 1})
    assert json.loads((tmp_path / "report.json").read_text()) == {"x": 1}
    write_markdown_report(tmp_path / "report.md", "Title", {"task": {"metric": 1.2}})
    assert "Title" in (tmp_path / "report.md").read_text()
    write_leaderboard(tmp_path / "leaderboard.csv", [{"model": "m", "score": 1.0}])
    with (tmp_path / "leaderboard.csv").open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["model"] == "m"
