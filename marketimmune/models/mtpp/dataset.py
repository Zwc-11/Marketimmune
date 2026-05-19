from __future__ import annotations

from dataclasses import dataclass

from aegisbench.datasets.builder import BenchmarkExample


@dataclass(frozen=True)
class SequenceExample:
    scenario_id: str
    times_ms: list[float]
    marks: list[str]
    labels: list[bool]
    features: list[dict[str, float]]


def build_sequences(examples: list[BenchmarkExample]) -> list[SequenceExample]:
    by_scenario: dict[str, list[BenchmarkExample]] = {}
    for example in examples:
        by_scenario.setdefault(example.scenario_id, []).append(example)
    sequences: list[SequenceExample] = []
    for scenario_id, rows in sorted(by_scenario.items()):
        ordered = sorted(rows, key=lambda row: row.timestamp_ms)
        sequences.append(
            SequenceExample(
                scenario_id=scenario_id,
                times_ms=[row.timestamp_ms for row in ordered],
                marks=[row.mark for row in ordered],
                labels=[row.unsafe for row in ordered],
                features=[row.features for row in ordered],
            )
        )
    return sequences
