from __future__ import annotations

import math

import pytest

from marketimmune.paper.engine import Engine, MarketMaker
from marketimmune.paper.events import Depth, RefTop, Top, Trade
from marketimmune.paper.mm import MarketMaking, MMParams, Portfolio, entry_after, parse, sweep
from marketimmune.paper.signals import CoinState, Wallets
from marketimmune.paper.strategies import quoter


def _coin() -> CoinState:
    c = CoinState("BCH", Wallets(), sz_decimals=3)  # tick 0.01 at 270
    c.top = Top("BCH", 0, 270.0, 1.0, 270.1, 1.0)
    c.basis = 0.0
    c.ref = RefTop("BCH", 0, c.top.mid, c.top.mid)  # gap 0, so the forecast is 0
    return c


def test_names_parse_to_parameters() -> None:
    assert parse("") == MMParams()
    assert parse("2").h == 2.0 and parse("2").skew_bps == 2.0 and parse("0").skew_bps == 1.0
    p = parse("h=1/skew=3/stop=0/net=1500")
    assert (p.h, p.skew_bps, p.nskew_bps, p.stop, p.net) == (1.0, 3.0, 3.0, 0.0, 1500.0)
    assert isinstance(quoter("mm@1.5"), MarketMaking)
    with pytest.raises(AssertionError, match="unknown mm parameter"):
        parse("spread=2")


def test_quotes_sit_h_from_fair_and_lean_on_the_position() -> None:
    c, mm = _coin(), MarketMaking(parse("1"))
    assert mm.targets(c, 0, 0.0, 4.0, 0.0) == (270.02, 270.08)  # 270.05 -/+ 1 bp, rounded away from the mid
    bid, ask = mm.targets(c, 0, 4.0, 4.0, 0.0)  # long at the limit: centre 1 bp lower, no bid
    assert bid is None and ask == 270.05 and "coin limit" in mm.why
    assert mm.targets(c, 0, -2.0, 4.0, 0.0) == (270.03, 270.1)  # half short: 0.5 bp higher (270.0905 rounds up)
    bid, ask = mm.targets(c, 0, 0.0, 4.0, 2_000.0)  # net long at the limit: no bids anywhere
    assert bid is None and ask is not None and "net +$2,000" in mm.why


def test_quotes_never_cross_and_follow_the_microprice() -> None:
    c, mm = _coin(), MarketMaking(parse("0"))
    assert mm.targets(c, 0, 0.0, 4.0, 0.0) == (270.05, 270.05 + 0.01)  # h = 0: at fair, one tick apart at least
    c.top = Top("BCH", 0, 270.0, 9.0, 270.1, 1.0)  # bids heavier: microprice 270.09
    bid, ask = mm.targets(c, 0, 0.0, 4.0, 0.0)
    assert bid == 270.09 and ask == 270.1  # the bid moves up; the ask stays post-only at the best ask
    c.top = Top("BCH", 0, 270.0, 1.0, 270.01, 1.0)  # one tick wide
    assert mm.targets(c, 0, 0.0, 4.0, 0.0) == (270.0, 270.01)


def test_entry_averages_up_and_resets_through_zero() -> None:
    entry, pos, opened = entry_after(None, 0.0, 1, 100.0, 1.0, 1e-9)
    assert (entry, pos, opened) == (100.0, 1.0, True)
    entry, pos, _ = entry_after(entry, pos, 1, 103.0, 2.0, 1e-9)
    assert entry == pytest.approx(102.0) and pos == 3.0
    assert entry_after(102.0, 3.0, -1, 110.0, 1.0, 1e-9)[:2] == (102.0, 2.0)  # reducing keeps the entry
    assert entry_after(102.0, 2.0, -1, 99.0, 5.0, 1e-9) == (99.0, -3.0, True)  # through zero: a new short at 99
    assert entry_after(102.0, 2.0, -1, 99.0, 2.0, 1e-9) == (None, 0.0, False)


def test_a_taker_sweep_walks_the_seen_book() -> None:
    top = Top("SOL", 0, 99.0, 1.0, 100.0, 1.0)
    depth = Depth("SOL", 0, {99.0: 1.0, 98.5: 3.0}, {100.0: 1.0, 100.5: 2.0, 101.0: 5.0})
    assert sweep(top, depth, 1, 2.5) == pytest.approx((100.0 + 1.5 * 100.5) / 2.5)
    assert sweep(top, depth, -1, 2.0) == pytest.approx((99.0 + 98.5) / 2)
    assert sweep(top, None, 1, 3.0) == 100.0  # no depth: the rest at the top's price


def test_kill_switch_trips_on_the_drawdown_and_pauses() -> None:
    port = Portfolio(parse("h=1/dd=50/pause=60"), {})
    assert not port.mark(0, 10.0, 0.0) and port.peak == 10.0
    assert not port.mark(100, -39.0, 0.0)
    assert port.mark(200, -41.0, 0.0) and port.paused(200) and port.paused(60_199) and not port.paused(60_200)
    assert port.kills == 1 and port.peak == -41.0
    assert not port.mark(300, -100.0, 0.0)  # paused: no second trip


def _engine(name: str) -> tuple[Engine, MarketMaker]:
    e = Engine(("BCH",), latency_ms=100, quote_usd=270.05, max_quotes=4, strategies=(name,), sz_decimals={"BCH": 3})
    e.handle(Top("BCH", 1_000, 270.0, 1.0, 270.1, 1.0), 1_000)
    e.handle(RefTop("BCH", 1_000, 270.05, 270.05), 1_000)
    e.tick(1_000)  # the basis: gap 0
    e.handle(Top("BCH", 1_010, 270.0, 1.0, 270.1, 1.0), 1_040)
    m = e.makers["BCH"][0]
    assert isinstance(m, MarketMaker)
    return e, m


def test_live_orders_stay_within_the_tolerance() -> None:
    e, m = _engine("mm@h=1/tol=1")
    bid = m.current[1]
    assert bid is not None and bid.px == 270.02 and m.current[-1] is not None
    e.handle(Top("BCH", 1_100, 270.01, 1.0, 270.11, 1.0), 1_140)  # target 270.03: one tick, inside 1 bp
    assert m.current[1] is bid and bid.t_cancel > 10**15
    e.handle(Top("BCH", 1_200, 270.05, 1.0, 270.15, 1.0), 1_240)  # target 270.07: moved
    assert m.current[1] is not bid and bid.t_cancel == 1_340


def test_a_stop_closes_with_a_taker_order_and_cools_down() -> None:
    e, m = _engine("mm@h=1/stop=10/cool=30/dd=0")
    e.handle(Trade("BCH", 1_150, 270.0, 5.0, False, "0xa"), 1_160)  # through our bid at 270.02: long 1
    assert m.account.position == pytest.approx(1.0) and m.entry == 270.02 and e.portfolios["mm@h=1/stop=10/cool=30/dd=0"].net_usd > 0
    e.handle(Top("BCH", 1_200, 269.6, 1.0, 269.7, 1.0), 1_240)  # mid 269.65: -13.7 bps
    assert m.pending == (-1, 1_340, "stop") and m.exits["stop"] == 1
    assert m.current[1] is None and m.current[-1] is None
    e.handle(Top("BCH", 1_350, 269.6, 1.0, 269.7, 1.0), 1_400)
    assert m.account.position == 0.0 and m.pending is None and m.entry is None
    assert m.account.equity(269.65) == pytest.approx(269.6 - 270.02 - 270.02 * 1.5e-4 - 269.6 * 4.5e-4)
    e.handle(Top("BCH", 1_400, 269.6, 1.0, 269.7, 1.0), 1_440)
    assert m.current[1] is None and "stopped out" in m.mm.why
    e.handle(RefTop("BCH", 31_500, 269.65, 269.65), 31_500)
    e.handle(Top("BCH", 31_520, 269.6, 1.0, 269.7, 1.0), 31_520)  # the cool-down is over, both feeds alive
    assert m.current[1] is not None


def test_silent_feeds_cancel_every_quote() -> None:
    e, m = _engine("mm@1")
    bid = m.current[1]
    assert bid is not None
    e.tick(3_500)  # Coinbase silent 2.5 s: still fine
    assert m.current[1] is bid
    e.handle(Top("BCH", 4_100, 270.0, 1.0, 270.1, 1.0), 4_100)  # Hyperliquid alone: Coinbase silent 3.1 s
    assert m.current[1] is None and "silent" in m.mm.why
    assert bid.t_cancel == 4_200
    e.tick(4_300)
    assert m.sides == "none"
    assert e.summary()["instances"][0]["exits"] == {"stop": 0, "hold": 0, "kill": 0}


def test_engine_summary_records_the_parameters() -> None:
    e, _ = _engine("mm@h=2/net=1000")
    settings = e.summary()["settings"]["mm"]["mm@h=2/net=1000"]
    assert settings["h"] == 2.0 and settings["net"] == 1000.0 and settings["skew_bps"] == 2.0
    assert math.isinf(e.room("mm@h=2/net=1000", "BCH"))


def test_wallet_factor_weights_each_takers_score() -> None:
    c = _coin()
    c.flow.extend([(100, 2_000.0, 2_000.0, 3.0), (200, -1_000.0, 1_000.0, -1.0), (900, 1_000.0, 1_000.0, 0.0)])
    assert c.informed(1_000) == pytest.approx((2_000 * 3.0 + 1_000 * 1.0) / 4_000)  # a seller whose sells lost: +1
    assert c.informed(1_000, 500) == 0.0  # only the score-0 buyer in the last 0.5 s
    assert c.informed(10_000) == 0.0


def test_guard_pulls_on_the_gap_and_on_informed_wallets() -> None:
    from marketimmune.paper.strategies import Guard, GuardParams, parse_guard

    assert parse_guard("") == GuardParams() and parse_guard("z=0.1/w=1/net=2000").w == 1.0
    with pytest.raises(AssertionError, match="unknown guard parameter"):
        parse_guard("h=1")
    c = _coin()
    c.gap_var = 1.0
    c.flow.append((0, 1_000.0, 1_000.0, 2.0))  # an informed buyer: wallet factor +2 bps
    c.informed_var = {1_000: 1.0, 5_000: 1.0}  # wallet z +2 over either window
    g = Guard(parse_guard("z=0.5/w=1"))
    assert g.targets(c, 0, 0.0, 4.0, 0.0) == (270.01, None)  # gap z 0: both sides; wallets z +2: no ask
    assert "wallets z +2.00: ask pulled" in g.why
    assert Guard(parse_guard("z=0.5")).targets(c, 0, 0.0, 4.0, 0.0) == (270.01, 270.09)  # wallet factor off
    c.ref = RefTop("BCH", 0, 270.05 * math.exp(-1e-4), 270.05 * math.exp(-1e-4))  # Coinbase 1 bp lower: gap z -1
    assert Guard(parse_guard("z=0.5")).targets(c, 0, 0.0, 4.0, 0.0) == (None, 270.09)
    lean = Guard(parse_guard("z=5/lean=0.5/net=1000"))
    assert lean.targets(c, 0, 2.0, 4.0, 0.0) == (None, 270.09)  # half the limit long: only sell
    assert lean.targets(c, 0, 0.0, 4.0, -1_500.0) == (270.01, None)  # net short past $1,000: only buy
    assert "net -$1,500: no asks" in lean.why


def test_guard_runs_with_the_risk_layer() -> None:
    e, m = _engine("guard@z=0.05/stop=10/net=1000")
    assert m.current[1] is not None and m.current[1].px == 270.01  # one tick inside the 10-tick spread
    assert e.summary()["settings"]["mm"]["guard@z=0.05/stop=10/net=1000"]["net"] == 1000.0
    e.handle(Trade("BCH", 1_150, 270.0, 5.0, False, "0xa"), 1_160)  # through the bid: long
    e.handle(Top("BCH", 1_200, 269.6, 1.0, 269.7, 1.0), 1_240)  # 13 bps against it
    assert m.pending is not None and m.pending[2] == "stop"
