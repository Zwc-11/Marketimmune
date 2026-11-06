from __future__ import annotations

import asyncio
import json

import pytest

from marketimmune.paper.dashboard import Board
from marketimmune.paper.engine import Engine
from marketimmune.paper.events import Top, Trade


def _filled_engine() -> Engine:
    e = Engine(("SOL",), latency_ms=100, strategies=("touch", "gap@0.25"))
    e.handle(Top("SOL", 1_000, 99.0, 30.0, 101.0, 30.0), 1_000)  # both quote 99 / 101, 10 coins
    e.handle(Trade("SOL", 1_250, 98.0, 1.0, False, "0xa"), 1_260)  # through the bids
    return e


def test_board_sums_segments_and_counts_actions() -> None:
    board = Board()
    first = _filled_engine()
    board.attach(first)
    board.sample(5_000)
    state = board.state(5_000)
    touch = next(s for s in state["strategies"] if s["strategy"] == "touch")
    assert touch["fills"] == 1 and touch["pnl"] == pytest.approx(first.makers["SOL"][0].account.equity(100.0))
    assert touch["actions"] == 2  # a bid and an ask sent
    assert state["coins"][0]["positions"]["touch"] == pytest.approx(1_000.0)
    assert state["tape"][0]["side"] == 1 and state["history"]["touch"][-1][1] == pytest.approx(touch["pnl"], abs=0.01)
    board.close_segment(first)
    board.attach(_filled_engine())
    again = next(s for s in board.state(6_000)["strategies"] if s["strategy"] == "touch")
    assert again["fills"] == 2 and again["pnl"] == pytest.approx(2 * touch["pnl"])
    assert board.segments == 2


def test_dashboard_serves_the_page_and_the_state() -> None:
    async def run() -> tuple[bytes, bytes, bytes]:
        board = Board()
        board.attach(_filled_engine())
        server = await board.serve(0)
        port = server.sockets[0].getsockname()[1]

        async def get(path: str) -> bytes:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            await writer.drain()
            data = await reader.read()
            writer.close()
            return data

        out = (await get("/"), await get("/state.json"), await get("/nope"))
        server.close()
        await server.wait_closed()
        return out

    page, state, missing = asyncio.run(run())
    assert page.startswith(b"HTTP/1.1 200") and b"<title>Paper Trading Live</title>" in page
    body = json.loads(state.split(b"\r\n\r\n", 1)[1])
    assert {s["strategy"] for s in body["strategies"]} == {"touch", "gap@0.25"}
    assert missing.startswith(b"HTTP/1.1 404")
