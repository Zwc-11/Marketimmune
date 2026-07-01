from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from marketimmune.schemas.events import (
    AgentOrderEvent,
    AggTradeEvent,
    BookDepthEvent,
    BookTickerEvent,
    EventSource,
    EventType,
    HyperliquidFillEvent,
    KlineEvent,
    OrderAction,
    Side,
    TradeEvent,
    parse_event,
)

NOW = datetime(2024, 5, 1, tzinfo=UTC)


def agg_trade() -> AggTradeEvent:
    return AggTradeEvent(
        symbol="BTCUSDT",
        timestamp=NOW,
        sequence=0,
        aggregate_trade_id=1,
        price=65000,
        quantity=1,
        first_trade_id=1,
        last_trade_id=2,
        is_buyer_maker=True,
    )


def test_agg_trade_has_event_id() -> None:
    assert agg_trade().event_id is not None


def test_agg_trade_hash_is_stable() -> None:
    assert agg_trade().event_id == agg_trade().event_id


def test_lowercase_symbol_rejected() -> None:
    with pytest.raises(ValidationError):
        AggTradeEvent(
            symbol="btcusdt",
            timestamp=NOW,
            sequence=0,
            aggregate_trade_id=1,
            price=65000,
            quantity=1,
            first_trade_id=1,
            last_trade_id=2,
            is_buyer_maker=True,
        )


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError):
        TradeEvent(
            symbol="BTCUSDT",
            timestamp=datetime(2024, 5, 1),
            sequence=0,
            trade_id=1,
            price=1,
            quantity=1,
            side=Side.BUY,
        )


def test_negative_price_rejected() -> None:
    with pytest.raises(ValidationError):
        TradeEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=0,
            trade_id=1,
            price=-1,
            quantity=1,
            side=Side.BUY,
        )


def test_book_ticker_crossed_book_rejected() -> None:
    with pytest.raises(ValidationError):
        BookTickerEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=0,
            update_id=1,
            bid_price=2,
            bid_quantity=1,
            ask_price=1,
            ask_quantity=1,
        )


def test_book_ticker_validates_spread() -> None:
    event = BookTickerEvent(
        symbol="BTCUSDT",
        timestamp=NOW,
        sequence=0,
        update_id=1,
        bid_price=1,
        bid_quantity=1,
        ask_price=2,
        ask_quantity=1,
    )
    assert event.ask_price > event.bid_price


def test_book_depth_round_trip() -> None:
    event = BookDepthEvent(
        symbol="BTCUSDT",
        timestamp=NOW,
        sequence=0,
        percentage=-5.0,
        depth=8754.63,
        notional=702612935.17,
    )
    assert parse_event(event.model_dump(mode="json")).event_type == "book_depth"


def test_kline_rejects_bad_high_low() -> None:
    with pytest.raises(ValidationError):
        KlineEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=0,
            interval="1m",
            open_time=NOW,
            close_time=NOW,
            open_price=10,
            high_price=9,
            low_price=8,
            close_price=10,
            volume=1,
            trade_count=1,
        )


def test_kline_rejects_close_before_open() -> None:
    with pytest.raises(ValidationError):
        KlineEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=0,
            interval="1m",
            open_time=NOW,
            close_time=NOW.replace(year=2023),
            open_price=10,
            high_price=11,
            low_price=8,
            close_price=10,
            volume=1,
            trade_count=1,
        )


def test_agent_remaining_quantity_cannot_exceed_quantity() -> None:
    with pytest.raises(ValidationError):
        AgentOrderEvent(
            symbol="BTCUSDT",
            timestamp=NOW,
            sequence=0,
            scenario_id="s1",
            agent_id="a1",
            order_id="o1",
            action=OrderAction.NEW,
            side=Side.BUY,
            price=1,
            quantity=1,
            remaining_quantity=2,
        )


def test_parse_event_round_trip() -> None:
    event = agg_trade()
    assert parse_event(event.model_dump(mode="json")).event_id == event.event_id


def test_hyperliquid_fill_round_trip() -> None:
    event = HyperliquidFillEvent(
        symbol="BTC-PERP",
        timestamp=NOW,
        sequence=0,
        trade_id=123,
        price=65000,
        quantity=0.25,
        side=Side.BUY,
        crossed=True,
        maker_side=-1,
        fee=0.12,
        fee_token="USDC",
    )

    parsed = parse_event(event.model_dump(mode="json"))

    assert parsed.event_type == EventType.HYPERLIQUID_FILL.value
    assert parsed.source == EventSource.HYPERLIQUID_PUBLIC.value
    assert parsed.event_id == event.event_id


def test_hyperliquid_fill_rejects_bad_maker_side() -> None:
    with pytest.raises(ValidationError):
        HyperliquidFillEvent(
            symbol="BTC-PERP",
            timestamp=NOW,
            sequence=0,
            trade_id=None,
            price=65000,
            quantity=0.25,
            side=Side.BUY,
            crossed=None,
            maker_side=0,
            fee=None,
            fee_token=None,
        )
