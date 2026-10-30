from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
import websockets

from tests.conftest import load_path

rec = load_path("record", "deploy/recorder/record.py")

HOUR_NS = 3_600_000_000_000
T0 = 1_765_800_000_000_000_000  # 2025-12-15T12:00:00Z


def test_hourly_writer_rotates_on_utc_hour(tmp_path: Path) -> None:
    w = rec.HourlyWriter(tmp_path)
    w.write(T0 + 1, '{"a":1}')
    w.write(T0 + HOUR_NS - 1, '{"a":2}')
    w.write(T0 + HOUR_NS, '{"a":3}')
    w.close()
    a, b = tmp_path / "20251215" / "12.log", tmp_path / "20251215" / "13.log"
    assert a.read_text().splitlines() == [f"{T0 + 1} " + '{"a":1}', f"{T0 + HOUR_NS - 1} " + '{"a":2}']
    assert b.read_text() == f"{T0 + HOUR_NS} " + '{"a":3}\n'
    assert w.lines == 3


def test_subscriptions() -> None:
    subs = rec.hl_subscriptions()
    assert len(subs) == 9 and subs[0] == {
        "method": "subscribe",
        "subscription": {"type": "l2Book", "coin": "BTC"},
    }


async def _serve(n_msgs: int, drops: int, received: list[str]) -> tuple[websockets.Server, str]:
    state = {"conns": 0}

    async def handler(ws: websockets.ServerConnection) -> None:
        state["conns"] += 1
        sub = await ws.recv()
        received.append(str(sub))
        for i in range(n_msgs):
            await ws.send(json.dumps({"channel": "trades", "i": i, "conn": state["conns"]}))
        if state["conns"] <= drops:
            await ws.close(code=1011, reason="test drop")
            return
        await ws.wait_closed()  # stay open until the client leaves

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, f"ws://127.0.0.1:{port}"


def test_reconnects_logs_gaps_and_writes_every_message(tmp_path: Path) -> None:
    async def go() -> dict[str, int]:
        received: list[str] = []
        server, url = await _serve(n_msgs=5, drops=2, received=received)
        feed = rec.Feed(
            "fake", url, [{"method": "subscribe", "subscription": {"type": "trades", "coin": "BTC"}}]
        )
        try:
            lines = await rec.record(tmp_path, [feed], max_seconds=4.0)
        finally:
            server.close()
            await server.wait_closed()
        assert len(received) == 3  # initial connect + two reconnects, each resubscribed
        return lines

    lines = asyncio.run(go())
    assert lines == {"fake": 15}
    written = [ln for p in sorted((tmp_path / "fake").rglob("*.log")) for ln in p.read_text().splitlines()]
    assert len(written) == 15
    ns, raw = written[0].split(" ", 1)
    assert int(ns) > T0 and json.loads(raw)["channel"] == "trades"
    events = Counter(json.loads(x)["event"] for x in (tmp_path / "gaps.jsonl").read_text().splitlines())
    assert events["connected"] == 3 and events["closed"] == 2 and events["stopped"] == 1


def test_unreachable_endpoint_is_logged_not_fatal(tmp_path: Path) -> None:
    feed = rec.Feed("dead", "ws://127.0.0.1:9", [])
    lines = asyncio.run(rec.record(tmp_path, [feed], max_seconds=1.5))
    assert lines == {"dead": 0}
    events = [json.loads(x)["event"] for x in (tmp_path / "gaps.jsonl").read_text().splitlines()]
    assert events[0] == "error" and events[-1] == "stopped"


@pytest.mark.network
def test_live_smoke(tmp_path: Path) -> None:
    """Only run once docs/jurisdiction.md clears live endpoints."""
    lines = asyncio.run(rec.record(tmp_path, rec.default_feeds(), max_seconds=20))
    assert lines["hyperliquid"] > 0 and lines["binance"] > 0
