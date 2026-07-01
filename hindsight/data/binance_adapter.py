"""Canonical-event adapter for the Binance parquet lake."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from hindsight.core.cursor import CursorEvent, EventCursor
from hindsight.data.repositories import AggTradeRepository, BookTickerRepository
from hindsight.ports.market_data import MarketDataPort
from marketimmune.schemas.events import (
    AggTradeEvent,
    BookDepthEvent,
    BookTickerEvent,
    CanonicalEvent,
    KlineEvent,
)
from marketimmune.simulator.data_loader import DepthRepository, KlineRepository


class BinanceLakeAdapter(MarketDataPort):
    """Streams Binance lake rows as canonical events."""

    def __init__(self, lake_root: Path):
        root = Path(lake_root)
        self.kline_repo = KlineRepository(root)
        self.depth_repo = DepthRepository(root)
        self.agg_trade_repo = AggTradeRepository(root)
        self.book_ticker_repo = BookTickerRepository(root)

    def stream_events(
        self,
        *,
        symbol: str,
        date: str | None,
        limit: int,
    ) -> Iterator[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        events.extend(self._kline_events(symbol=symbol, date=date, limit=limit))
        events.extend(self._book_depth_events(symbol=symbol, date=date))
        events.extend(self._agg_trade_events(symbol=symbol, date=date, limit=limit))
        events.extend(self._book_ticker_events(symbol=symbol, date=date, limit=limit))
        for event in EventCursor(cast(list[CursorEvent], events)):
            yield cast(CanonicalEvent, event)

    def _kline_events(
        self,
        *,
        symbol: str,
        date: str | None,
        limit: int,
    ) -> list[KlineEvent]:
        records = self.kline_repo.load(symbol, date, limit)
        events: list[KlineEvent] = []
        for sequence, record in enumerate(records):
            timestamp = _ensure_utc(record.timestamp)
            events.append(
                KlineEvent(
                    event_id=_event_id(record.event_id),
                    symbol=record.symbol,
                    timestamp=timestamp,
                    sequence=sequence,
                    interval="1m",
                    open_time=timestamp,
                    close_time=timestamp,
                    open_price=record.open,
                    high_price=record.high,
                    low_price=record.low,
                    close_price=record.close,
                    volume=record.volume,
                    trade_count=record.trade_count,
                )
            )
        return events

    def _book_depth_events(self, *, symbol: str, date: str | None) -> list[BookDepthEvent]:
        if date is None:
            dates = self.depth_repo.available_dates(symbol)
            # Fallback reason: the CLI can run without an explicit date, and the
            # existing repository exposes available dates as the deterministic way
            # to select a partition. If none exist, depth contributes no events.
            if not dates:
                return []
            date = dates[0]
        snapshots = self.depth_repo.load(symbol, date)
        events: list[BookDepthEvent] = []
        sequence = 0
        for snapshot in snapshots:
            timestamp = _ensure_utc(snapshot.timestamp)
            for level in snapshot.levels:
                events.append(
                    BookDepthEvent(
                        symbol=symbol.upper(),
                        timestamp=timestamp,
                        sequence=sequence,
                        percentage=level.percentage,
                        depth=level.depth,
                        notional=level.notional,
                    )
                )
                sequence += 1
        return events

    def _agg_trade_events(
        self,
        *,
        symbol: str,
        date: str | None,
        limit: int,
    ) -> list[AggTradeEvent]:
        records = self.agg_trade_repo.load(symbol, date, limit)
        events: list[AggTradeEvent] = []
        for sequence, record in enumerate(records):
            events.append(
                AggTradeEvent(
                    event_id=_event_id(record.event_id),
                    symbol=record.symbol,
                    timestamp=_ensure_utc(record.timestamp),
                    sequence=sequence,
                    aggregate_trade_id=record.aggregate_trade_id,
                    price=record.price,
                    quantity=record.quantity,
                    first_trade_id=record.first_trade_id,
                    last_trade_id=record.last_trade_id,
                    is_buyer_maker=record.is_buyer_maker,
                )
            )
        return events

    def _book_ticker_events(
        self,
        *,
        symbol: str,
        date: str | None,
        limit: int,
    ) -> list[BookTickerEvent]:
        records = self.book_ticker_repo.load(symbol, date, limit)
        events: list[BookTickerEvent] = []
        for sequence, record in enumerate(records):
            events.append(
                BookTickerEvent(
                    event_id=_event_id(record.event_id),
                    symbol=record.symbol,
                    timestamp=_ensure_utc(record.timestamp),
                    sequence=sequence,
                    update_id=record.update_id,
                    bid_price=record.bid_price,
                    bid_quantity=record.bid_quantity,
                    ask_price=record.ask_price,
                    ask_quantity=record.ask_quantity,
                )
            )
        return events


def _ensure_utc(timestamp: datetime) -> datetime:
    # Boundary normalization: simulator.data_loader emits naive UTC wall time,
    # while the canonical event schema requires aware UTC timestamps.
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _event_id(value: str) -> str | None:
    # Existing lake rows can omit event ids; passing None lets the schema compute
    # a deterministic id instead of preserving an empty string.
    if value == "":
        return None
    return value
