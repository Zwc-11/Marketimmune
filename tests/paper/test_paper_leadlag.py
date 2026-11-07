from types import SimpleNamespace

from marketimmune.paper.mm import is_mm
from marketimmune.paper.strategies import Dislocation, LeadAS, Sweep, fair_price, parse_lead, quoter
from marketimmune.paper.tailmm import Tail, run


def _coin(bid: float, ask: float, gap: float, sigma: float = 0.5) -> SimpleNamespace:
    top = SimpleNamespace(bid=bid, ask=ask, mid=(bid + ask) / 2)
    return SimpleNamespace(top=top, tick=1.0, gap=lambda: gap, sigma_1s=sigma, coin="BTC")


def test_names_parse_and_run_in_the_risk_layer() -> None:
    for name in ("disloc@d=3/x=1/tol=0.3", "lead@h0=2/skew=0.5", "sweep@move=5/win=3"):
        assert is_mm(name)
        assert quoter(name).p == parse_lead(name.partition("@")[2])


def test_dislocation_quotes_around_coinbase_fair_and_stays_passive() -> None:
    q = Dislocation(parse_lead("d=3"))
    q.qty = 0.01
    coin = _coin(100_000.0, 100_001.0, gap=0.0)
    fair = fair_price(coin)
    assert fair is not None and abs(fair - 100_000.5) < 1e-6
    bid, ask = q.targets(coin, 0, 0.0, 0.04, 0.0)
    assert bid == 99_970.0 and ask == 100_031.0  # 3 bp either side, on the tick grid
    # Coinbase 10 bp higher: the bid would cross; it is capped at the best bid
    bid, ask = q.targets(_coin(100_000.0, 100_001.0, gap=10.0), 0, 0.0, 0.04, 0.0)
    assert bid == 100_000.0 and ask >= 100_001.0
    # long one quote: the ask becomes the exit at fair (at least the best ask)
    _, ask = q.targets(coin, 0, 0.01, 0.04, 0.0)
    assert ask == 100_001.0


def test_lead_as_skews_against_inventory() -> None:
    q = LeadAS(parse_lead("h0=2/skew=1"))
    q.qty = 0.01
    coin = _coin(100_000.0, 100_001.0, gap=0.0, sigma=0.0)
    flat = q.targets(coin, 0, 0.0, 0.04, 0.0)
    long = q.targets(coin, 0, 0.02, 0.04, 0.0)
    assert flat[0] is not None and long[0] is not None and long[0] < flat[0]


def test_sweep_arms_only_after_a_one_venue_move() -> None:
    q = Sweep(parse_lead("move=5/win=3/wait=5"))
    q.qty = 0.01
    assert q.targets(_coin(100_000.0, 100_001.0, gap=0.0), 0, 0.0, 0.04, 0.0) == (None, None)
    bid, ask = q.targets(_coin(99_940.0, 99_941.0, gap=6.0), 3_500, 0.0, 0.04, 0.0)
    assert bid == 99_940.0 and ask is None


def test_tail_maker_fills_through_the_queue() -> None:
    ev = [(0, 0, (1.000, 100.0, 1.001, 100.0))]
    ev += [(1_000 + i, 1, (1.000, 30.0, -1)) for i in range(5)]  # 150 sold at the bid: through our queue
    ev += [(2_000, 0, (1.000, 100.0, 1.001, 100.0)), (3_000, 1, (1.001, 300.0, 1))]
    r = run(ev, Tail(min_spread=3, n_max=1, quote_usd=10.0, latency_ms=100), start_ms=0, end_ms=10_000)
    assert r["fills"] >= 1 and r["fills_table"]["side"].iloc[0] == 1


def test_hush_quotes_deep_only_while_informed_wallets_are_quiet() -> None:
    from marketimmune.paper.events import Trade
    from marketimmune.paper.signals import CoinState, Wallets
    from marketimmune.paper.strategies import Hush, parse_hush

    wallets = Wallets()
    for _ in range(10):
        wallets.add("0xsharp", 3.0)  # scores 30 / (10 + 20) = 1.0 bp
        wallets.add("0xretail", -1.0)
    coin = CoinState("BTC", wallets, sz_decimals=5)
    coin.on_top(SimpleNamespace(t_ms=0, bid=100_000.0, ask=100_001.0, mid=100_000.5), 0)  # type: ignore[arg-type]
    q = Hush(parse_hush("d=1/quiet=5/inf=0.9/n=5"))
    q.qty = 0.01
    bid, ask = q.targets(coin, 1_000, 0.0, 0.04, 0.0)
    assert bid == 99_990.0 and ask == 100_011.0  # 1 bp either side of the mid, on the tick grid
    coin.on_trade(Trade("BTC", 2_000, 100_001.0, 0.1, True, "0xretail"), 2_000)
    assert q.targets(coin, 2_500, 0.0, 0.04, 0.0)[0] is not None  # a low-score wallet does not pull
    coin.on_trade(Trade("BTC", 3_000, 100_001.0, 0.1, True, "0xsharp"), 3_000)
    assert q.targets(coin, 4_000, 0.0, 0.04, 0.0) == (None, None)  # 1 s after an informed take: out
    assert coin.informed_quiet_ms(9_000, 0.9, 5) == 6_000.0
    assert q.targets(coin, 9_000, 0.0, 0.04, 0.0)[0] is not None  # quiet again after 5 s
