from __future__ import annotations

import numpy as np
import pytest

from marketimmune.paper.events import CoinbaseBooks, Depth, RefTop, Top, Trade, parse_hl
from marketimmune.paper.orders import Account, PaperOrder
from marketimmune.paper.signals import FEATURES, CoinState, Ridge, Series, Wallets
from marketimmune.paper.strategies import GapPull, ModelPull, Touch


def test_parse_hl_messages() -> None:
    bbo = {
        "channel": "bbo",
        "data": {"coin": "SOL", "time": 1000, "bbo": [{"px": "89.32", "sz": "2", "n": 1}, {"px": "89.33", "sz": "5", "n": 2}]},
    }
    assert parse_hl(bbo, 1300) == [Top("SOL", 1000, 89.32, 2.0, 89.33, 5.0)]
    one_sided = {"channel": "bbo", "data": {"coin": "SOL", "time": 1000, "bbo": [None, {"px": "1", "sz": "1", "n": 1}]}}
    assert parse_hl(one_sided, 1300) == []
    book = {
        "channel": "l2Book",
        "data": {"coin": "SOL", "time": 900, "levels": [[{"px": "10", "sz": "1", "n": 1}], [{"px": "11", "sz": "2", "n": 1}]]},
    }
    assert parse_hl(book, 1300) == [Depth("SOL", 900, {10.0: 1.0}, {11.0: 2.0})]
    trades = {
        "channel": "trades",
        "data": [
            {"coin": "SOL", "side": "B", "px": "11", "sz": "3", "time": 1200, "users": ["0xbuyer", "0xseller"]},
            {"coin": "SOL", "side": "A", "px": "10", "sz": "1", "time": 1250, "users": ["0xb2", "0xs2"]},
            {"coin": "SOL", "side": "A", "px": "10", "sz": "1", "time": -9000, "users": ["0xold", "0xold"]},  # the replayed snapshot
        ],
    }
    assert parse_hl(trades, 1300) == [Trade("SOL", 1200, 11.0, 3.0, True, "0xbuyer"), Trade("SOL", 1250, 10.0, 1.0, False, "0xs2")]
    assert parse_hl({"channel": "pong"}, 0) == []


def _l2(seq: int, kind: str, updates: list[tuple[str, str, str]]) -> dict[str, object]:
    rows = [{"side": s, "price_level": p, "new_quantity": q} for s, p, q in updates]
    return {"channel": "l2_data", "sequence_num": seq, "events": [{"type": kind, "product_id": "SOL-USD", "updates": rows}]}


def test_coinbase_books_track_the_top_and_reject_gaps() -> None:
    books = CoinbaseBooks()
    assert books.apply(_l2(0, "snapshot", [("bid", "10", "1"), ("bid", "9", "1"), ("offer", "11", "1")]), 5) == [
        RefTop("SOL", 5, 10.0, 11.0)
    ]
    assert books.apply(_l2(1, "update", [("bid", "9", "3")]), 6) == []  # below the top
    assert books.apply(_l2(2, "update", [("bid", "10", "0")]), 7) == [RefTop("SOL", 7, 9.0, 11.0)]  # the best bid leaves
    assert books.apply({"channel": "heartbeats", "sequence_num": 3}, 8) == []
    with pytest.raises(AssertionError, match="sequence gap"):
        books.apply(_l2(5, "update", [("offer", "12", "1")]), 9)


def test_paper_order_queue_and_fills() -> None:
    o = PaperOrder(side=1, px=10.0, qty=2.0, t_live=100, t_cancel=500)
    assert o.match(90, 10.0, 5.0, False, seen_size=0.0) == 0.0  # not in the book yet
    o.see_level(80, 1.0)  # a book message from before the order arrived does not set the queue
    assert o.queue is None
    o.see_level(120, 4.0)
    o.see_level(130, 6.0)  # the queue ahead can only shrink
    assert o.queue == 4.0
    assert o.match(140, 10.0, 3.0, True, seen_size=4.0) == 0.0  # a taker buy never hits a bid
    assert o.match(150, 10.0, 3.0, False, seen_size=4.0) == 0.0 and o.queue == 1.0
    assert o.match(160, 10.0, 2.0, False, seen_size=4.0) == 1.0 and o.qty == 1.0
    assert o.match(170, 9.9, 0.1, False, seen_size=4.0) == 1.0 and o.qty == 0.0  # a sell below the bid empties the level
    late = PaperOrder(side=-1, px=11.0, qty=1.0, t_live=100, t_cancel=200)
    assert late.match(150, 11.5, 0.1, True, seen_size=0.0) == 1.0  # never saw a book: through the ask fills it
    gone = PaperOrder(side=-1, px=11.0, qty=1.0, t_live=100, t_cancel=200)
    assert gone.match(200, 11.5, 1.0, True, seen_size=0.0) == 0.0  # cancelled by then
    queued = PaperOrder(side=-1, px=11.0, qty=1.0, t_live=100)
    assert queued.match(150, 11.0, 2.5, True, seen_size=2.0) == 0.5  # no book seen since t_live: the last seen size


def test_account_equity_and_fees() -> None:
    a = Account()
    a.fill(1, 1, 100.0, 2.0, 1.5e-4)
    a.fill(2, -1, 101.0, 1.0, 1.5e-4)
    assert a.position == 1.0 and a.fills == 2 and a.notional == 301.0
    assert a.equity(102.0) == pytest.approx(-200 + 101 + 102 - 301 * 1.5e-4)


def test_series_and_ridge() -> None:
    s = Series(1_000)
    s.add(10, 1.0)
    s.add(20, 2.0)
    s.add(15, 3.0)  # out of order: clamped to the last time
    assert s.at(5) is None and s.at(12) == 1.0 and s.at(20) == 3.0
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2_000, 3))
    y = 2.0 * x[:, 0] - 1.0 * x[:, 2] + 0.5
    model = Ridge.fit(x, y, lam=1e-6)
    assert np.allclose(model.predict(x[:5]), y[:5], atol=1e-6)


def _coin_with_tops() -> CoinState:
    c = CoinState("SOL", Wallets())
    c.on_top(Top("SOL", 1_000, 99.99, 1.0, 100.01, 1.0), 1_300)
    c.on_ref(RefTop("SOL", 1_310, 100.04, 100.06), 1_310)
    return c


def test_gap_is_demeaned_and_features_line_up() -> None:
    c = _coin_with_tops()
    assert c.raw_gap() == pytest.approx(np.log(100.05 / 100.0) * 1e4)
    assert c.gap() is None  # no basis before the first grid sample
    c.sample(1_400)
    assert c.gap() == pytest.approx(0.0)
    c.on_ref(RefTop("SOL", 1_500, 100.09, 100.11), 1_500)  # Coinbase up 5 bps more
    assert c.gap() == pytest.approx(np.log(100.10 / 100.05) * 1e4)
    x = c.features(1_500)
    assert x is not None and len(x) == len(FEATURES)
    assert x[FEATURES.index("spread")] == pytest.approx(2.0)


def test_wallet_scores_use_the_mid_ten_seconds_later() -> None:
    w = Wallets()
    c = CoinState("SOL", w)
    c.on_top(Top("SOL", 1_000, 99.99, 1.0, 100.01, 1.0), 1_300)
    c.on_trade(Trade("SOL", 1_100, 100.01, 1.0, True, "0xfast"), 1_400)
    c.on_top(Top("SOL", 10_000, 100.09, 1.0, 100.11, 1.0), 10_300)
    assert w.count == {}  # the horizon (11.1 s) has not passed
    c.on_top(Top("SOL", 11_200, 100.09, 1.0, 100.11, 1.0), 11_500)
    assert w.count == {"0xfast": 1} and w.score("0xfast") == pytest.approx(10.0 / 21)


def test_labels_skip_gaps_in_the_grid() -> None:
    c = CoinState("SOL", Wallets())
    c.rows = [[0.0] * len(FEATURES) for _ in range(30)]
    c.row_ms = [k * 100 for k in range(20)] + [60_000 + k * 100 for k in range(10)]
    c.row_mid = [100.0] * 15 + [101.0] * 15
    x, y = c.labelled()
    assert y.size == 10  # rows 0-9 have a row 1 s later; 10-19 face the gap; the last 10 run out
    assert np.allclose(y[5:], np.log(101 / 100) * 1e4)


class _Stub(CoinState):
    def __init__(self, move: float | None) -> None:
        super().__init__("SOL", Wallets())
        self.top = Top("SOL", 0, 10.0, 1.0, 10.1, 1.0)
        self.move = move

    def predict(self, local_ms: int) -> float | None:
        return self.move


def test_strategies_pull_the_side_at_risk() -> None:
    coin = _Stub(None)
    assert Touch().quotes(coin, 0, 0.0, 5.0) == (10.0, 10.1)
    assert Touch().quotes(coin, 0, 5.0, 5.0) == (None, 10.1)  # at the position cap
    coin.basis = 0.0
    coin.ref = RefTop("SOL", 0, 10.052, 10.052)  # 1.99 bps above Hyperliquid's mid
    assert GapPull(1.0).quotes(coin, 0, 0.0, 5.0) == (10.0, None)
    assert GapPull(2.0).quotes(coin, 0, 0.0, 5.0) == (10.0, 10.1)
    assert ModelPull(1.0).quotes(_Stub(-1.5), 0, 0.0, 5.0) == (None, 10.1)
    assert ModelPull(1.0).quotes(_Stub(None), 0, 0.0, 5.0) == (10.0, 10.1)  # no model yet: like Touch


def test_tick_sizes_follow_the_price_rules() -> None:
    from marketimmune.paper.signals import on_tick, tick_size

    assert tick_size(104_523.0, 5) == 1.0  # integers are always allowed
    assert tick_size(3_512.3, 4) == pytest.approx(0.1)
    assert tick_size(89.32, 2) == pytest.approx(0.001)
    assert tick_size(0.0912, 0) == pytest.approx(1e-6)
    assert tick_size(0.0912, 2) == pytest.approx(1e-4)  # capped by 6 - szDecimals decimals
    assert on_tick(0.16345 + 0.00001, 1e-5) == 0.16346


def test_improve_steps_inside_wide_spreads_only() -> None:
    from marketimmune.paper.strategies import Improve

    coin = CoinState("BCH", Wallets(), sz_decimals=3)
    coin.top = Top("BCH", 0, 270.0, 1.0, 270.1, 1.0)  # tick 0.01: 10 ticks wide
    assert Improve().quotes(coin, 0, 0.0, 5.0) == (270.01, 270.09)
    assert Improve().quotes(coin, 0, 5.0, 5.0) == (None, 270.09)
    coin.top = Top("BCH", 0, 270.0, 1.0, 270.02, 1.0)  # two ticks: stay at the touch
    assert Improve().quotes(coin, 0, 0.0, 5.0) == (270.0, 270.02)
    coin.basis, coin.ref = 0.0, RefTop("BCH", 0, 270.1, 270.1)  # Coinbase 3.3 bps above
    assert Improve(2.0).quotes(coin, 0, 0.0, 5.0) == (270.0, None)


def test_strategies_by_name() -> None:
    from marketimmune.paper.strategies import Improve, quoter, taker_threshold

    assert isinstance(quoter("touch"), Touch) and quoter("gap@1.5").threshold_bps == 1.5  # type: ignore[attr-defined]
    assert isinstance(quoter("model@0.25"), ModelPull) and quoter("improve+gap@1").gap_bps == 1.0  # type: ignore[attr-defined]
    assert isinstance(quoter("improve"), Improve)
    assert taker_threshold("taker@6") == 6.0 and taker_threshold("gap@6") is None
    with pytest.raises(AssertionError, match="unknown"):
        quoter("spread@2")


def test_fastjson_round_trips_with_and_without_orjson(monkeypatch: pytest.MonkeyPatch) -> None:
    from marketimmune.paper import fastjson

    msg = {"channel": "bbo", "data": {"coin": "SOL", "time": 1, "bbo": [None, {"px": "1.5"}]}}
    assert fastjson.loads(fastjson.dumps(msg)) == msg
    monkeypatch.setattr(fastjson, "orjson", None)
    assert fastjson.loads(fastjson.dumps(msg)) == msg and fastjson.loads(b'{"a": 1}') == {"a": 1}


def test_hip3_oracle_is_the_reference_and_coin_names_keep_their_dex() -> None:
    from marketimmune.cli.paper_trade import coin_list
    from marketimmune.paper.events import RefTop, parse_hl

    msg = {"channel": "activeAssetCtx", "data": {"coin": "xyz:XYZ100", "ctx": {"oraclePx": "26945.0", "markPx": "26948.0"}}}
    assert parse_hl(msg, 1_000) == [RefTop("xyz:XYZ100", 1_000, 26945.0, 26945.0)]
    # a major's context is not a reference (Coinbase is)
    assert parse_hl({"channel": "activeAssetCtx", "data": {"coin": "BTC", "ctx": {"oraclePx": "1"}}}, 1_000) == []
    assert coin_list("xyz:XYZ100,btc,io:ANTH") == ("BTC", "xyz:XYZ100", "io:ANTH")
    assert coin_list("xyz:CL") == ("xyz:CL",)


def test_a_twin_market_takes_its_reference_from_the_leader_book() -> None:
    from marketimmune.paper.engine import Engine
    from marketimmune.paper.events import RefTop, Top

    eng = Engine(("io:SNDK", "xyz:SNDK"), strategies=("touch",), twins={"io:SNDK": "xyz:SNDK"}, sz_decimals={"io:SNDK": 2, "xyz:SNDK": 2})
    eng.handle(RefTop("io:SNDK", 1_000, 830.0, 830.0), 1_000)  # its own oracle: ignored
    assert eng.states["io:SNDK"].ref is None
    eng.handle(Top("xyz:SNDK", 1_000, 833.0, 1.0, 833.5, 1.0), 1_010)
    ref = eng.states["io:SNDK"].ref
    assert ref is not None and (ref.bid, ref.ask) == (833.0, 833.5)
    eng.handle(RefTop("xyz:SNDK", 1_020, 832.0, 832.0), 1_020)  # the leader keeps its oracle
    assert eng.states["xyz:SNDK"].ref is not None


def test_capped_through_fill_is_a_sensitivity_setting():
    from marketimmune.paper import orders

    full = PaperOrder(side=1, px=10.0, qty=5.0, t_live=0)
    assert full.match(10, 9.9, 2.0, False, 0.0) == 5.0  # a trade through the bid fills it all
    orders.CAP_THROUGH = True
    try:
        capped = PaperOrder(side=1, px=10.0, qty=5.0, t_live=0)
        assert capped.match(10, 9.9, 2.0, False, 0.0) == 2.0  # at most the print's size
        assert capped.match(11, 9.9, 4.0, False, 0.0) == 3.0  # then the rest
    finally:
        orders.CAP_THROUGH = False
