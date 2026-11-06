"""Run the paper engine on the live feeds, or replay a recorded run through the same code.

Live: one Hyperliquid connection (``bbo``, ``l2Book`` and ``trades`` per coin) and one Coinbase
connection (``level2`` and ``heartbeats``). Each reconnects on any error with a growing back-off,
and every drop is logged in ``connection_gaps``. Every raw message is kept, gzipped by venue and UTC
hour, as ``<local_ns>\\t<message>`` lines: ``replay`` feeds those back through the engine, so a
night can be re-run with other settings.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import heapq
import signal
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import orjson
import websockets

from marketimmune.logger import init_logger
from marketimmune.paper.engine import Engine
from marketimmune.paper.events import STALE_TRADE_MS, CoinbaseBooks, parse_hl

logger = init_logger(__name__)
HL_URL = "wss://api.hyperliquid.xyz/ws"
CB_URL = "wss://advanced-trade-ws.coinbase.com"
HL_CHANNELS = ("bbo", "l2Book", "trades")
HL_PING_S = 50.0
TICK_MS = 100
WRITE_S = 60.0


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class RawWriter:
    """Gzipped ``<local_ns>\\t<raw>`` lines in ``<root>/<venue>-<YYYYMMDDHH>.log.gz`` (UTC hours)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.files: dict[str, tuple[str, gzip.GzipFile]] = {}

    def write(self, venue: str, local_ns: int, raw: str | bytes) -> None:
        hour = time.strftime("%Y%m%d%H", time.gmtime(local_ns // 1_000_000_000))
        cur = self.files.get(venue)
        if cur is None or cur[0] != hour:
            if cur is not None:
                cur[1].close()
            fh = gzip.GzipFile(self.root / f"{venue}-{hour}.log.gz", "ab", compresslevel=1)
            self.files[venue] = cur = (hour, fh)
        cur[1].write(b"%d\t%s\n" % (local_ns, raw.encode() if isinstance(raw, str) else raw))

    def close(self) -> None:
        for _, fh in self.files.values():
            fh.close()
        self.files.clear()


async def hl_feed(engine: Engine, writer: RawWriter | None) -> None:
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(HL_URL, max_size=2**24, ping_interval=None) as ws:
                for coin in engine.coins:
                    for channel in HL_CHANNELS:
                        await ws.send(orjson.dumps({"method": "subscribe", "subscription": {"type": channel, "coin": coin}}).decode())
                        await asyncio.sleep(0.02)
                logger.info(f"hyperliquid: subscribed {len(engine.coins)} coins")
                backoff = 1.0
                last_ping = time.monotonic()
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=HL_PING_S)
                    local_ns = time.time_ns()
                    if writer is not None:
                        writer.write("hl", local_ns, raw)
                    for ev in parse_hl(orjson.loads(raw), local_ns // 1_000_000):
                        engine.handle(ev, local_ns // 1_000_000)
                    if time.monotonic() - last_ping > HL_PING_S:
                        await ws.send('{"method":"ping"}')
                        last_ping = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # any drop: log the gap and reconnect
            engine.gaps.append({"venue": "hl", "t_ms": now_ms(), "error": repr(e)[:200]})
            logger.warning(f"hyperliquid dropped ({e!r}); reconnecting in {backoff:.0f} s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def cb_feed(engine: Engine, writer: RawWriter | None) -> None:
    backoff = 1.0
    products = [f"{c}-USD" for c in engine.coins]
    while True:
        books = CoinbaseBooks()
        try:
            async with websockets.connect(CB_URL, max_size=2**26, ping_interval=20) as ws:
                await ws.send(orjson.dumps({"type": "subscribe", "product_ids": products, "channel": "level2"}).decode())
                await ws.send(orjson.dumps({"type": "subscribe", "channel": "heartbeats"}).decode())
                logger.info(f"coinbase: subscribed {len(products)} products")
                backoff = 1.0
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    local_ns = time.time_ns()
                    if writer is not None:
                        writer.write("cb", local_ns, raw)
                    for ev in books.apply(orjson.loads(raw), local_ns // 1_000_000):
                        engine.handle(ev, local_ns // 1_000_000)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # includes a sequence gap: reconnect for a fresh snapshot
            engine.gaps.append({"venue": "cb", "t_ms": now_ms(), "error": repr(e)[:200]})
            logger.warning(f"coinbase dropped ({e!r}); reconnecting in {backoff:.0f} s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def run_live(engine: Engine, out: Path, seconds: float, raw: bool) -> None:
    """Until ``seconds`` have passed or SIGINT / SIGTERM arrives; either way the run is written."""
    writer = RawWriter(out / "raw") if raw else None
    feeds = [asyncio.create_task(hl_feed(engine, writer)), asyncio.create_task(cb_feed(engine, writer))]
    stop = time.monotonic() + seconds
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    next_write = time.monotonic() + WRITE_S
    late = 0
    try:
        while time.monotonic() < stop and not stopped.is_set():
            await asyncio.sleep(TICK_MS / 1000)
            t0 = time.perf_counter()
            engine.tick(now_ms())
            late += (time.perf_counter() - t0) > 0.05
            if time.monotonic() >= next_write:
                next_write = time.monotonic() + WRITE_S
                engine.counts["slow_ticks"] = late
                engine.write(out, final=False)
                if writer is not None:
                    for _, fh in writer.files.values():
                        fh.flush()
    finally:
        for f in feeds:
            f.cancel()
        for f in feeds:
            with contextlib.suppress(asyncio.CancelledError):
                await f
        if writer is not None:
            writer.close()


def raw_lines(root: Path) -> Iterator[tuple[int, str, bytes]]:
    """Every recorded message under ``root`` in receive order: (local ns, venue, raw)."""

    def one(path: Path) -> Iterator[tuple[int, str, bytes]]:
        venue = path.name.split("-")[0]
        with gzip.open(path, "rb") as fh:
            for line in fh:
                t, _, msg = line.rstrip(b"\n").partition(b"\t")
                if msg:
                    yield int(t), venue, msg

    yield from heapq.merge(*(one(p) for p in sorted(root.glob("*.log.gz"))), key=lambda x: x[0])


RETIME_WINDOW_MS = 10_000


def block_ms(msg: dict[str, Any]) -> int | None:
    """The block time of a Hyperliquid message: its book's, or its newest fresh trade's."""
    data: Any = msg.get("data")
    if msg.get("channel") in ("bbo", "l2Book"):
        return int(data["time"])
    if msg.get("channel") == "trades" and data:
        return max(int(x["time"]) for x in data)
    return None


def retimed(lines: Iterator[tuple[int, str, bytes]], retime: dict[str, int]) -> Iterator[tuple[int, str, bytes]]:
    """``lines`` with each message's receive time moved to where another maker would have seen it:
    a Hyperliquid message ``retime["hl"]`` ms after its block, a Coinbase one ``retime["cb"]`` ms
    after it arrived here. A reorder buffer of ``RETIME_WINDOW_MS`` puts them back in time order;
    a message later than that window is held at the last time already sent. The trades replayed at
    each subscription are dropped first, as ``parse_hl`` would."""
    heap: list[tuple[int, int, str, bytes]] = []
    sent = 0
    for seq, (local_ns, venue, raw) in enumerate(lines):
        local_ms = local_ns // 1_000_000
        if venue == "hl":
            msg = orjson.loads(raw)
            if msg.get("channel") == "trades":
                msg["data"] = [x for x in msg["data"] if local_ms - int(x["time"]) <= STALE_TRADE_MS]
                raw = orjson.dumps(msg)
            t = block_ms(msg)
            if t is None:
                continue
            new = t + retime["hl"]
        else:
            new = local_ms + retime["cb"]
        heapq.heappush(heap, (new, seq, venue, raw))
        while heap and heap[0][0] <= local_ms - RETIME_WINDOW_MS:
            t, _, v, r = heapq.heappop(heap)
            sent = max(sent, t)
            yield sent * 1_000_000, v, r
    while heap:
        t, _, v, r = heapq.heappop(heap)
        sent = max(sent, t)
        yield sent * 1_000_000, v, r


def replay(engine: Engine, root: Path, retime: dict[str, int] | None = None) -> None:
    """Feed a recorded run through ``engine`` in receive order (or ``retimed``), ticking every
    100 ms of receive time."""
    books = CoinbaseBooks()
    next_tick: int | None = None
    lines = raw_lines(root) if retime is None else retimed(raw_lines(root), retime)
    for local_ns, venue, raw in lines:
        local_ms = local_ns // 1_000_000
        if next_tick is None:
            next_tick = local_ms
        while next_tick <= local_ms:
            engine.tick(next_tick)
            next_tick += TICK_MS
        msg: dict[str, Any] = orjson.loads(raw)
        if venue == "hl":
            events = parse_hl(msg, local_ms)
        else:
            try:
                events = list(books.apply(msg, local_ms))
            except AssertionError:  # the live run reconnected here; its next snapshot restarts the book
                books = CoinbaseBooks()
                events = []
        for ev in events:
            engine.handle(ev, local_ms)
