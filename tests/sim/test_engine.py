from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from marketimmune.sim import engine
from marketimmune.sim.attribution import PX_SCALE, Costs, attribute_day
from marketimmune.sim.engine import ADD, BID, CANCEL, FIFO, FILL, NO_QUOTE, RISK_AVERSE, DayBook, MakerResult, MakerSpec, simulate_day
from marketimmune.sim.strategies import QuantileBacker, StaleQuotePuller, TouchQuoter

Row = tuple[int, list[tuple[int, float]], list[tuple[int, float]]]
Event = tuple[int, int, bool, int, float, int, bool]  # ts, kind, is_ask, px, sz, added, alo


def _book(rows: list[Row], events: list[Event], depth: int = 2) -> DayBook:
    def levels(side: list[tuple[int, float]]) -> tuple[list[int], list[float]]:
        padded = [*side, *[(0, 0.0)] * (depth - len(side))]
        return [p for p, _ in padded], [s for _, s in padded]

    bids = [levels(b) for _, b, _ in rows]
    asks = [levels(a) for _, _, a in rows]
    ev = list(zip(*events, strict=True)) if events else [[] for _ in range(7)]
    return DayBook(
        l2_ts=np.array([t for t, _, _ in rows], dtype=np.int64),
        bid_px=np.array([p for p, _ in bids], dtype=np.int64),
        bid_sz=np.array([s for _, s in bids], dtype=np.float64),
        ask_px=np.array([p for p, _ in asks], dtype=np.int64),
        ask_sz=np.array([s for _, s in asks], dtype=np.float64),
        ev_ts=np.array(ev[0], dtype=np.int64),
        ev_kind=np.array(ev[1], dtype=np.int8),
        ev_ask=np.array(ev[2], dtype=bool),
        ev_px=np.array(ev[3], dtype=np.int64),
        ev_sz=np.array(ev[4], dtype=np.float64),
        ev_added=np.array(ev[5], dtype=np.int64),
        ev_alo=np.array(ev[6], dtype=bool),
    )


@dataclass
class Fixed:
    bid: int = NO_QUOTE
    ask: int = NO_QUOTE
    until: int = 1 << 62  # quote on rows before this time

    def quotes(self, row: int, ts: int, bid: int, ask: int, position: float) -> tuple[int, int]:
        return (self.bid, self.ask) if ts < self.until else (NO_QUOTE, NO_QUOTE)


def _fills(r: MakerResult) -> list[tuple[int, int, int, float]]:
    return list(zip(r.ts, r.side, r.px, r.qty, strict=True))


TOP = ([(100, 5.0)], [(101, 5.0)])


def test_fifo_counts_only_the_queue_ahead_while_risk_averse_waits_for_trades() -> None:
    # five rest at 100 before us; ten more join behind us; four of the five ahead cancel
    events = [
        (20, ADD, False, 100, 10.0, 20, False),
        (30, CANCEL, False, 100, 4.0, 1, False),
        (40, FILL, False, 100, 1.0, 1, False),
        (50, FILL, False, 100, 2.0, 20, False),  # a taker reached an order behind us
        (60, FILL, False, 100, 9.0, 20, False),
    ]
    book = _book([(10, *TOP)], events)
    specs = [MakerSpec(q, Fixed(bid=100), q, 3.0) for q in (FIFO, RISK_AVERSE)]
    fifo, averse = simulate_day(book, specs, delay_ns=5)
    assert _fills(fifo) == [(50, BID, 100, 2.0), (60, BID, 100, 1.0)]
    # risk averse: 5 ahead, minus 1 traded -> 4; the 2 traded at 50 leave 2 ahead; 9 at 60 fill us
    assert _fills(averse) == [(60, BID, 100, 3.0)]
    assert fifo.placed == averse.placed == 1


def test_same_block_alo_adds_go_ahead_and_gtc_adds_behind() -> None:
    events = [
        (20, ADD, False, 100, 2.0, 20, True),  # post-only in our block: ahead
        (20, ADD, False, 100, 3.0, 20, False),  # GTC in our block: behind
        (30, FILL, False, 100, 7.0, 1, False),  # the five from before
        (30, FILL, False, 100, 2.0, 20, True),  # the post-only one
        (40, FILL, False, 100, 1.0, 20, False),  # the GTC behind us: we are next
    ]
    (r,) = simulate_day(_book([(10, *TOP)], events), [MakerSpec("m", Fixed(bid=100), FIFO, 1.0)], delay_ns=5)
    assert _fills(r) == [(40, BID, 100, 1.0)]


def test_sweeps_fill_through_and_cancels_beat_takers_in_their_block() -> None:
    events = [
        (20, FILL, True, 102, 3.0, 1, False),  # bought above our ask: swept our level
        (45, FILL, True, 102, 3.0, 1, False),
    ]
    rows = [(10, *TOP), (30, *TOP), (40, [(100, 5.0)], [(101, 5.0), (102, 1.0)])]
    (r,) = simulate_day(_book(rows, events), [MakerSpec("m", Fixed(ask=101, until=40), FIFO, 2.0)], delay_ns=5)
    # placed at 20 before the taker: filled 2; re-quoted at 30 (lands at 40), the cancel decided
    # at 40 lands at 45, before that block's taker
    assert _fills(r) == [(20, -1, 101, 2.0)]
    assert r.placed == 2 and r.cancelled == 1


def test_latency_rejection_crossing_gtc_and_gaps() -> None:
    events = [
        (12, FILL, False, 99, 5.0, 1, False),  # before our order lands: no fill
        (20, ADD, True, 100, 0.5, 20, True),  # post-only ask at our bid: it would be rejected, no trade
        (25, ADD, True, 100, 0.5, 25, False),  # GTC ask at our bid: trades with us
        (31_000_000_100, FILL, False, 99, 5.0, 1, False),  # after a gap our order is gone
    ]
    rows = [(10, *TOP), (31_000_000_000, *TOP)]
    crossing = MakerSpec("cross", Fixed(ask=100), FIFO, 1.0)  # an ask at the best bid
    (r, x) = simulate_day(_book(rows, events), [MakerSpec("m", Fixed(bid=100, until=20), FIFO, 1.0), crossing], delay_ns=5)
    assert _fills(r) == [(25, BID, 100, 0.5)]
    assert x.rejected >= 1 and x.placed == 0
    # an L2 backtester also fills on the post-only ask at 20
    (r2, _) = simulate_day(
        _book(rows, events), [MakerSpec("m", Fixed(bid=100, until=20), FIFO, 1.0), crossing], delay_ns=5, l2_crossing_fills=True
    )
    assert _fills(r2) == [(20, BID, 100, 0.5), (25, BID, 100, 0.5)]


def test_attribution_components_add_up() -> None:
    def ticks(px: float) -> int:
        return round(px * PX_SCALE)

    second = 1_000_000_000
    l2_ts = np.array([0, 2 * second, 10 * second], dtype=np.int64)
    bid = np.array([ticks(99.99), ticks(100.04), ticks(100.09)], dtype=np.int64)
    ask = np.array([ticks(100.01), ticks(100.06), ticks(100.11)], dtype=np.int64)
    r = MakerResult("m", ts=[1 * second], side=[1], px=[ticks(99.99)], qty=[2.0], placed=1)
    out = attribute_day(r, l2_ts, bid, ask, Costs(maker_fee_bps=1.5, taker_fee_bps=4.5, horizon_ns=1 * second))
    assert out["spread_usd"] == pytest.approx(0.02)
    assert out["adverse_usd"] == pytest.approx(0.10)  # mid 100.00 -> 100.05 one second later
    assert out["inventory_usd"] == pytest.approx(0.10)  # -> 100.10 at the day's end
    assert out["fee_usd"] == pytest.approx(-1.5e-4 * 199.98)
    assert out["hedge_usd"] == pytest.approx(-2.0 * (0.01 + 4.5e-4 * 100.10))
    parts = sum(out[f"{c}_usd"] for c in ("spread", "adverse", "inventory", "fee", "hedge"))
    assert out["total_usd"] == pytest.approx(parts) and out["pnl_usd"] == out["total_usd"]
    assert out["spread_usd"] + out["adverse_usd"] + out["inventory_usd"] == pytest.approx((100.10 - 99.99) * 2.0)


def test_touch_quoter_and_stale_rule() -> None:
    s1 = TouchQuoter(max_position=2.0)
    assert s1.quotes(0, 0, 100, 101, 0.0) == (100, 101)
    assert s1.quotes(0, 0, 100, 101, 2.0) == (NO_QUOTE, 101)
    rule = StaleQuotePuller(s1, np.array([-3.0, np.nan]), np.array([0.0, -2.0]), threshold_bps=2.0)
    assert rule.quotes(0, 0, 100, 101, 0.0) == (NO_QUOTE, 101)
    assert rule.quotes(1, 0, 100, 101, 0.0) == (100, NO_QUOTE)


def test_quantile_backer_steps_back_to_the_second_level() -> None:
    s1 = TouchQuoter(max_position=2.0)
    bid_q10, ask_q10 = np.array([-3.0, -3.0, np.nan]), np.array([0.0, -3.0, -3.0])
    back = QuantileBacker(s1, bid_q10, ask_q10, 2.0, np.array([99, 0, 99]), np.array([102, 102, 102]))
    assert back.quotes(0, 0, 100, 101, 0.0) == (99, 101)  # the bid steps back, the ask stays at the touch
    assert back.quotes(1, 0, 100, 101, 0.0) == (NO_QUOTE, 102)  # a side showing one level stops quoting
    assert back.quotes(2, 0, 100, 101, 2.0) == (NO_QUOTE, 102)  # NaN keeps the touch, but the position cap still pulls


def test_chunked_event_lists_give_the_same_fills(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        (20, ADD, False, 100, 10.0, 20, False),
        (30, CANCEL, False, 100, 4.0, 1, False),
        (40, FILL, False, 100, 1.0, 1, False),
        (40, FILL, False, 100, 2.0, 20, False),
        (60, FILL, False, 100, 9.0, 20, False),
    ]
    book = _book([(10, *TOP), (50, *TOP)], events)
    specs = [MakerSpec(q, Fixed(bid=100), q, 3.0) for q in (FIFO, RISK_AVERSE)]
    whole = simulate_day(book, specs, delay_ns=5)
    monkeypatch.setattr(engine, "CHUNK_EVENTS", 1)  # the two events of block 40 stay together
    assert simulate_day(book, specs, delay_ns=5) == whole
