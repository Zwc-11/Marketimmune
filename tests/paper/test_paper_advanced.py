from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from marketimmune.paper.dashboard import Board
from marketimmune.paper.engine import Engine
from marketimmune.paper.events import RefTop, Top, Trade
from marketimmune.paper.signals import FORECAST_PRIOR, CoinState, Wallets
from marketimmune.paper.strategies import HawkesPull, Kelly, Reservation, ZGap, quoter


def _coin(gap_bps: float = 0.0) -> CoinState:
    c = CoinState("BCH", Wallets(), sz_decimals=3)
    c.top = Top("BCH", 0, 270.0, 1.0, 270.1, 1.0)  # tick 0.01: ten ticks wide
    c.basis = 0.0
    mid = c.top.mid
    c.ref = RefTop("BCH", 0, mid * math.exp(gap_bps / 1e4), mid * math.exp(gap_bps / 1e4))
    return c


def test_zgap_scales_the_gap_by_its_volatility() -> None:
    c = _coin(gap_bps=1.0)
    c.gap_var = 4.0  # sigma 2 bps: z = 0.5
    assert ZGap(0.25).quotes(c, 0, 0.0, 5.0) == (270.01, None)
    assert ZGap(1.0).quotes(c, 0, 0.0, 5.0) == (270.01, 270.09)
    assert "gap z +0.50" in ZGap(0.25).reason(c, 0)


def test_hawkes_pulls_the_side_hit_in_a_burst() -> None:
    c = _coin()
    for t in range(0, 500, 50):  # ten taker buys in half a second
        c.on_trade(Trade("BCH", t, 270.1, 1.0, True, "0xa"), t)
    c.hawkes_base = {1: 1.0, -1: 1.0}
    assert c.intensity_ratio(1, 500) == pytest.approx(sum(math.exp(-(500 - t) / 2_000) for t in range(0, 500, 50)))
    assert HawkesPull(3.0).quotes(c, 500, 0.0, 5.0) == (270.01, None)
    assert "buy burst" in HawkesPull(3.0).reason(c, 500)
    assert c.intensity_ratio(1, 20_000) < 0.01  # the burst decays


def test_forecast_slope_learns_how_much_of_the_gap_hyperliquid_closes() -> None:
    c = CoinState("SOL", Wallets())
    mid, t = 100.0, 0
    for k in range(4_000):  # the gap is 2 bps on even seconds, -2 on odd; the mid follows half of it 10 s later
        t = k * 100
        gap = 2.0 if (t // 1_000) % 2 == 0 else -2.0
        lagged = 2.0 if ((t - 10_000) // 1_000) % 2 == 0 else -2.0
        mid = 100.0 * math.exp(0.5 * lagged / 1e4) if t >= 10_000 else 100.0
        c.view.add(t, mid)
        c._estimate(t, gap)
    assert c.fc_sxx > 0 and c.forecast_slope == pytest.approx(c.fc_sxy / (c.fc_sxx + FORECAST_PRIOR))
    assert c.sigma_1s is not None and c.gap_sigma == pytest.approx(2.0, rel=0.01)


def test_kelly_quotes_only_toward_its_target() -> None:
    c = _coin(gap_bps=3.0)
    c.var_1s = 1.0  # sigma over 10 s: sqrt(10) bps
    c.fc_sxx, c.fc_sxy = 1e9, 1e9  # forecast slope ~1: forecast ~3 bps
    k = Kelly(1.0)
    target = k.target(c, 5.0)
    assert target == pytest.approx(5.0 * 3.0 / math.sqrt(10), rel=0.01)
    assert k.quotes(c, 0, 0.0, 5.0) == (270.01, None)  # below the target: buy only
    assert k.quotes(c, 0, target + 0.6, 5.0) == (None, 270.09)  # more than half a quote above it: sell only
    assert k.quotes(c, 0, target, 5.0) == (None, None)  # within half a quote: nothing
    assert "target" in k.reason(c, 0)


def test_reservation_quotes_a_side_only_past_the_fee() -> None:
    c = _coin(gap_bps=3.0)
    c.fc_sxx, c.fc_sxy = 1e9, 1e9  # forecast ~3 bps up
    bid, ask = Reservation(1.0).quotes(c, 0, 0.0, 5.0)
    assert bid == 270.01 and ask is None  # buying is worth it; selling 3.3 bps above mid is not past r + fee
    assert Reservation(1.0).quotes(_coin(0.0), 0, 0.0, 5.0) == (None, None)  # no forecast edge: nothing clears the fee
    assert isinstance(quoter("reservation@3"), Reservation) and isinstance(quoter("kelly@0.5"), Kelly)


def test_board_explains_each_decision_and_serves_the_web(tmp_path: Path) -> None:
    e = Engine(("SOL",), latency_ms=100, strategies=("touch", "gap@0.25"))
    e.handle(Top("SOL", 1_000, 99.0, 30.0, 101.0, 30.0), 1_000)
    board = Board()
    board.attach(e)
    state = board.state(2_000)
    reasons = {d["strategy"]: d["reason"] for d in state["decisions"]}
    assert reasons["touch"] == "always both sides at the best price" and "not ready" in reasons["gap@0.25"]
    assert {x["sides"] for x in state["decision_log"]} == {"both"}
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>terminal</title>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("no")

    async def run() -> list[bytes]:
        server = await board.serve(0, web)
        port = server.sockets[0].getsockname()[1]
        out = []
        for path in ("/", "/assets/app.js", "/state.json", "/../secret.txt", "/paper.html"):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"GET {path} HTTP/1.1\r\n\r\n".encode())
            await writer.drain()
            out.append(await reader.read())
            writer.close()
        server.close()
        await server.wait_closed()
        return out

    index, script, state_raw, secret, page = asyncio.run(run())
    assert b"<title>terminal</title>" in index and b"text/javascript" in script
    assert b"Access-Control-Allow-Origin: *" in state_raw
    assert secret.startswith(b"HTTP/1.1 404") and b"Paper Trading Live" in page
