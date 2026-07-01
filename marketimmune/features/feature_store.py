from __future__ import annotations

import time
from datetime import timedelta

from marketimmune.features.agentic_features import agentic_features
from marketimmune.features.market_features import market_features
from marketimmune.features.order_features import order_features
from marketimmune.features.windows import windows_for_events
from marketimmune.schemas.events import AgentOrderEvent
from marketimmune.stats import p95

HORIZONS = [timedelta(seconds=1), timedelta(seconds=5), timedelta(seconds=60)]


def feature_snapshot(events: list[AgentOrderEvent]) -> dict[str, float]:
    features: dict[str, float] = {}
    for prefix, fn in [
        ("order", order_features),
        ("market", market_features),
        ("agentic", agentic_features),
    ]:
        for key, value in fn(events).items():
            features[f"{prefix}_{key}"] = value
    return features


def build_feature_store(events: list[AgentOrderEvent]) -> tuple[list[dict[str, float]], float]:
    snapshots = windows_for_events(events, HORIZONS)
    rows: list[dict[str, float]] = []
    latencies: list[float] = []
    sorted_events = sorted(events, key=lambda item: item.timestamp)
    for event, by_window in zip(sorted_events, snapshots, strict=True):
        started = time.perf_counter()
        row: dict[str, float] = {"timestamp_ms": event.timestamp.timestamp() * 1000}
        for window_name, window_events in by_window.items():
            for key, value in feature_snapshot(window_events).items():
                row[f"w{window_name}_{key}"] = value
        rows.append(row)
        latencies.append((time.perf_counter() - started) * 1000)
    return rows, p95(latencies)
