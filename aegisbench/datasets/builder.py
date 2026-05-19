from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from marketimmune.features.feature_store import build_feature_store
from marketimmune.schemas.events import AgentOrderEvent, parse_event
from marketimmune.schemas.labels import EventLabel


@dataclass(frozen=True)
class BenchmarkExample:
    scenario_id: str
    event_id: str
    timestamp_ms: float
    family: str
    unsafe: bool
    features: dict[str, float]
    mark: str = "agent_order:new"


def _load_events(path: Path) -> list[AgentOrderEvent]:
    payloads = json.loads(path.read_text(encoding="utf-8"))
    events: list[AgentOrderEvent] = []
    for payload in payloads:
        event = parse_event(payload)
        if not isinstance(event, AgentOrderEvent):
            raise ValueError(f"expected agent order event in {path}")
        events.append(event)
    return events


def _load_manifest(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _load_labels(path: Path) -> dict[str, EventLabel]:
    payloads = json.loads(path.read_text(encoding="utf-8"))
    labels = [EventLabel.model_validate(payload) for payload in payloads]
    return {label.event_id: label for label in labels}


def build_examples(scenario_root: Path) -> list[BenchmarkExample]:
    examples: list[BenchmarkExample] = []
    for event_file in sorted(scenario_root.glob("*_events.json")):
        scenario_id = event_file.name.removesuffix("_events.json")
        manifest = _load_manifest(scenario_root / f"{scenario_id}_manifest.json")
        events = _load_events(event_file)
        labels_by_event_id = _load_labels(scenario_root / f"{scenario_id}_labels.json")
        feature_rows, _ = build_feature_store(events)
        for event, features in zip(events, feature_rows, strict=True):
            label = labels_by_event_id[event.event_id or ""]
            examples.append(
                BenchmarkExample(
                    scenario_id=scenario_id,
                    event_id=event.event_id or "",
                    timestamp_ms=event.timestamp.timestamp() * 1000,
                    family=str(manifest["family"]),
                    unsafe=label.unsafe,
                    features=features,
                    mark=f"{event.event_type}:{event.action}:{event.side}",
                )
            )
    return examples


def examples_to_rows(examples: list[BenchmarkExample]) -> list[dict[str, object]]:
    return [
        {
            "scenario_id": example.scenario_id,
            "event_id": example.event_id,
            "timestamp_ms": example.timestamp_ms,
            "family": example.family,
            "unsafe": example.unsafe,
            "features": example.features,
            "mark": example.mark,
        }
        for example in examples
    ]
