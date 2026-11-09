"""Execution and causality regressions for the actual port-8770 strategy engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from marketimmune.paper.engine import Engine, Maker, MarketMaker, Taker
from marketimmune.paper.events import Depth, RefTop, Top, Trade, parse_hl
from marketimmune.paper.live import Clock, RawWriter, raw_lines
from marketimmune.paper.mm import MMParams, sweep, sweep_fill
from marketimmune.paper.orders import PaperOrder
from marketimmune.paper.signals import CoinState, Wallets
from marketimmune.paper.strategies import Hush, HushParams, Touch

HUSH = "hush@d=8/quiet=0/tol=0.3"


def top(coin: str = "io:X", time: int = 1000) -> Top:
    return Top(coin, time, 99.99, 10, 100.01, 10)


def ready(engine: Engine, coin: str, time: int = 1000) -> None:
    engine.handle(RefTop(coin, time, 100, 100), time)
    engine.handle(top(coin, time), time)


def test_queue_does_not_award_unobserved_cancellations() -> None:
    order = PaperOrder(1, 100, 1, 1000)
    order.see_level(1100, 10)
    order.see_level(1200, 1)
    assert order.match(1300, 100, 2, False, 1) == 0
    assert order.queue == 8


def test_trade_through_does_not_create_more_volume_than_the_print() -> None:
    order = PaperOrder(1, 100, 10, 1000)
    assert order.match(1200, 99, 0.1, False, 0) <= 0.1


def test_one_print_is_shared_by_all_orders_in_one_account() -> None:
    maker = Maker("touch", Touch(), 3, 10, 100, 0)
    maker.orders = [PaperOrder(1, 100, 3, 1000, queue=10), PaperOrder(1, 100, 3, 1001, queue=10)]
    state = CoinState("io:X", Wallets(), 2)
    state.on_top(top(), 1000)
    maker.on_trade(Trade("io:X", 1200, 100, 15, False, "seller"), state, 1200)
    assert maker.account.position == 5


def test_budget_reserves_pending_orders_across_coins() -> None:
    engine = Engine(("io:X", "io:Y"), strategies=(HUSH,), quote_usd=100, max_quotes=4, budget_usd=100, sz_decimals={"io:X": 2, "io:Y": 2})
    ready(engine, "io:X")
    ready(engine, "io:Y")
    reserved = sum(
        max(sum(o.qty for o in maker.orders if o.side == side) for side in (1, -1)) * 100
        for makers in engine.makers.values()
        for maker in makers
    )
    assert reserved <= 100


def test_stale_coin_is_pulled_while_other_coins_keep_streaming() -> None:
    engine = Engine(("io:X", "io:Y"), strategies=(HUSH,), quote_usd=100, sz_decimals={"io:X": 2, "io:Y": 2})
    ready(engine, "io:X")
    ready(engine, "io:Y")
    ready(engine, "io:Y", 5000)
    engine.tick(5000)
    maker = engine.makers["io:X"][0]
    assert all(o.t_cancel <= 5000 + engine.latency_ms for o in maker.orders)


def test_duplicate_trade_id_cannot_fill_twice() -> None:
    engine = Engine(("io:X",), strategies=("touch",), quote_usd=100, latency_ms=100)
    ready(engine, "io:X")
    frame = {
        "channel": "trades",
        "data": [{"coin": "io:X", "time": 1200, "tid": 7, "px": "99", "sz": "0.25", "side": "A", "users": ["buyer", "seller"]}],
    }
    for _ in range(2):
        for event in parse_hl(frame, 1200):
            engine.handle(event, 1200)
    assert engine.makers["io:X"][0].account.position == pytest.approx(0.25)


def test_post_only_order_crossing_on_arrival_is_rejected() -> None:
    engine = Engine(("io:X",), strategies=("touch",), quote_usd=100, latency_ms=100)
    ready(engine, "io:X")
    engine.handle(Top("io:X", 1100, 98, 10, 98.5, 10), 1100)
    engine.handle(Trade("io:X", 1120, 98.4, 1, False, "seller"), 1120)
    assert engine.makers["io:X"][0].account.fills == 0


def test_unknown_deep_queue_does_not_become_zero() -> None:
    maker = Maker("touch", Touch(), 1, 4, 100, 0)
    maker.orders = [PaperOrder(1, 90, 1, 1000)]
    state = CoinState("io:X", Wallets(), 2)
    state.on_top(top(), 1000)
    state.on_depth(Depth("io:X", 1000, {99.99: 10, 99: 10}, {100.01: 10}))
    maker.on_trade(Trade("io:X", 1200, 90, 1, False, "seller"), state, 1200)
    assert maker.account.fills == 0


def test_invalid_and_reordered_books_do_not_corrupt_state() -> None:
    engine = Engine(("io:X",), strategies=("touch",), quote_usd=100)
    ready(engine, "io:X", 2000)
    engine.handle(top(time=1000), 2100)
    engine.handle(Top("io:X", 2200, float("nan"), 1, 100, 1), 2200)
    assert engine.states["io:X"].top == top(time=2000)


def test_exit_quantity_is_fixed_when_the_order_is_sent() -> None:
    engine = Engine(("io:X",), strategies=(HUSH,), quote_usd=100, sz_decimals={"io:X": 2})
    ready(engine, "io:X")
    maker = engine.makers["io:X"][0]
    assert isinstance(maker, MarketMaker)
    maker.account.fill(1000, 1, 100, 1, 0)
    maker.absorb()
    maker.exit(1100, "hold", None)
    maker.account.fill(1150, 1, 100, 1, 0)
    maker.absorb()
    engine.handle(top(time=1500), 1500)
    assert maker.account.position == pytest.approx(1)


def test_depth_sweep_cannot_fabricate_unseen_liquidity() -> None:
    # The caller must receive a partial fill or an explicit insufficient-depth error.
    with pytest.raises(ValueError, match="depth"):
        sweep(Top("io:X", 1000, 99, 0.1, 101, 0.1), None, -1, 1)


def test_partial_exit_keeps_the_unfilled_position() -> None:
    engine = Engine(("io:X",), strategies=(HUSH,), quote_usd=100, sz_decimals={"io:X": 2})
    ready(engine, "io:X")
    maker = engine.makers["io:X"][0]
    assert isinstance(maker, MarketMaker)
    maker.account.fill(1000, 1, 100, 1, 0)
    maker.absorb()
    maker.exit(1100, "hold", None)
    engine.handle(Top("io:X", 1500, 99, 0.1, 101, 0.1), 1500)
    assert maker.account.position == pytest.approx(0.9)


def test_quote_quantity_respects_instrument_lot_size() -> None:
    engine = Engine(("io:X",), strategies=(HUSH,), quote_usd=10, sz_decimals={"io:X": 0})
    ready(engine, "io:X")
    assert engine.makers["io:X"] == []


def test_clock_correction_preserves_cross_feed_record_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("marketimmune.paper.live.time.time_ns", lambda: 1_000_000_000)
    clock = Clock(correct=True)
    first, second = clock.now_ns(), clock.now_ns()
    assert second > first
    writer = RawWriter(tmp_path)
    writer.write("hl", first, b"first")
    writer.write("cb", second, b"second")
    writer.close()
    assert [venue for _, venue, _ in raw_lines(tmp_path)] == ["hl", "cb"]


def test_stale_prices_cannot_create_training_rows() -> None:
    state = CoinState("io:X", Wallets(), 2)
    state.on_top(top(), 1000)
    state.on_ref(RefTop("io:X", 1000, 100, 100), 1000)
    state.sample(1000)
    count = len(state.rows)
    state.sample(5000)
    assert len(state.rows) == count


def test_cancelled_order_reserves_budget_until_exchange_progresses() -> None:
    engine = Engine(("io:X", "io:Y"), strategies=("touch",), quote_usd=100, budget_usd=100)
    ready(engine, "io:X")
    ready(engine, "io:Y")
    maker = engine.makers["io:X"][0]
    for order in maker.orders:
        order.t_cancel = 1250
    maker.current = {1: None, -1: None}
    engine.tick(2000)  # receive clock alone is not an exchange cancellation acknowledgement
    assert engine.room("touch", "io:Y") == 0
    engine.handle(Depth("io:X", 1300, {99.99: 10}, {100.01: 10}), 2100)
    assert engine.room("touch", "io:Y") > 0


def test_drawdown_kill_cancels_and_sends_exit_without_another_book() -> None:
    engine = Engine(("io:X",), strategies=(HUSH + "/dd=1",), quote_usd=100, sz_decimals={"io:X": 2})
    ready(engine, "io:X")
    maker = engine.makers["io:X"][0]
    assert isinstance(maker, MarketMaker)
    engine.tick(1000)
    maker.account.fill(1010, 1, 200, 1, 0)
    engine.tick(1100)
    assert maker.pending == (-1, 1300, "kill")
    assert all(order.t_cancel <= 1300 for order in maker.orders)


def test_taker_exit_preserves_position_and_open_time_after_partial_fill() -> None:
    taker = Taker("taker@1", 1, 1, 100, 0)
    taker.account.fill(1000, 1, 100, 1, 0)
    taker.entered_ms = 1000
    taker.pending = (-1, 1200)
    taker.on_top(Top("io:X", 1200, 99, 0.1, 101, 0.1), 1200)
    assert taker.account.position == pytest.approx(0.9)
    assert taker.entered_ms == 1000


def test_pre_activation_receipt_cannot_set_an_orders_queue() -> None:
    maker = Maker("touch", Touch(), 1, 4, 100, 0)
    order = PaperOrder(1, 99.99, 1, 1200)
    maker.orders = [order]
    maker.on_top(top(time=1300), 1100)  # exchange clock is ahead of receipt clock
    assert not order.arrived
    assert order.queue is None


def test_old_depth_liquidity_cannot_be_reused_by_a_later_exit() -> None:
    depth = Depth("io:X", 1100, {99: 1, 98: 1}, {101: 1})
    used: dict[tuple[int, int, float], float] = {}
    assert sweep_fill(Top("io:X", 1200, 99, 0, 101, 1), depth, -1, 1, used)[1] == 1
    assert sweep_fill(Top("io:X", 1300, 99, 0, 101, 1), depth, -1, 1, used)[1] == 0


@pytest.mark.parametrize("params", [{"h": float("nan")}, {"stop": -1}, {"stale": float("inf")}])
def test_invalid_market_maker_risk_parameters_are_rejected(params: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        MMParams(**params)


def test_hush_lean_limit_keeps_only_the_inventory_reducing_quote() -> None:
    strategy = Hush(HushParams(d=8, quiet=0, lean=0.5))
    strategy.qty = 1
    state = CoinState("io:X", Wallets(), 2)
    state.on_top(top(), 1000)
    bid, ask = strategy.targets(state, 1000, 2, 4, 0)
    assert bid is None
    assert ask is not None
