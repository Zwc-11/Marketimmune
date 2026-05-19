from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from aegisbench.datasets.builder import BenchmarkExample


def split_name(scenario_id: str) -> str:
    bucket = int(sha256(scenario_id.encode("utf-8")).hexdigest(), 16) % 10
    if bucket < 6:
        return "train"
    if bucket < 8:
        return "validation"
    return "test"


def deterministic_splits(examples: list[BenchmarkExample]) -> dict[str, list[BenchmarkExample]]:
    splits: dict[str, list[BenchmarkExample]] = defaultdict(list)
    for example in examples:
        splits[split_name(example.scenario_id)].append(example)
    return {name: splits.get(name, []) for name in ["train", "validation", "test"]}


def require_non_empty_splits(
    splits: dict[str, list[BenchmarkExample]],
) -> dict[str, list[BenchmarkExample]]:
    missing = [name for name in ["train", "validation", "test"] if not splits.get(name)]
    if missing:
        raise ValueError(f"empty benchmark split(s): {', '.join(missing)}")
    return splits


def has_scenario_leakage(splits: dict[str, list[BenchmarkExample]]) -> bool:
    seen: dict[str, str] = {}
    for split, examples in splits.items():
        for example in examples:
            previous = seen.setdefault(example.scenario_id, split)
            if previous != split:
                return True
    return False
