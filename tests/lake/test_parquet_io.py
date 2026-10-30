from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from marketimmune.lake.parquet_io import read_events, read_records, write_events
from marketimmune.schemas.events import AggTradeEvent

NOW = datetime(2024, 5, 1, tzinfo=UTC)


def sample_events() -> list[AggTradeEvent]:
    return [
        AggTradeEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=index,
            aggregate_trade_id=index,
            price=65000 + index,
            quantity=1,
            first_trade_id=index,
            last_trade_id=index,
            is_buyer_maker=bool(index % 2),
        )
        for index in range(2)
    ]


def test_parquet_round_trip_preserves_count(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.parquet"
    write_events(path, sample_events())
    assert len(read_events(path)) == 2


def test_parquet_round_trip_preserves_event_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.parquet"
    events = sample_events()
    write_events(path, events)
    assert read_events(path)[0].event_id == events[0].event_id


def test_read_records_returns_dicts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.parquet"
    write_events(path, sample_events())
    assert isinstance(read_records(path)[0], dict)


def test_duckdb_can_query_lake_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "events.parquet"
    write_events(path, sample_events())
    query = f"select count(*) from read_parquet('{path.as_posix()}')"
    count = duckdb.sql(query).fetchall()[0][0]
    assert count == 2
