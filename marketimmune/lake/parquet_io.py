from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.schemas.events import CanonicalEvent, parse_event


def _normalize_record(event: CanonicalEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def write_events(path: Path, events: list[CanonicalEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [_normalize_record(event) for event in events]
    table = pa.Table.from_pylist(records)
    pq.write_table(table, path, compression="zstd")


def read_records(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)
    return [dict(record) for record in table.to_pylist()]


def read_events(path: Path) -> list[CanonicalEvent]:
    return [parse_event(record) for record in read_records(path)]
