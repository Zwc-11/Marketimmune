"""Run the paper engine on the live feeds, or replay a recorded run through the same code.

Live: one Hyperliquid connection (``bbo``, ``l2Book`` and ``trades`` per coin) and one Coinbase
connection (``level2`` and ``heartbeats``). Each reconnects on any error with a growing back-off,
and every drop is logged in ``connection_gaps``. Every raw message is kept, gzipped by venue and UTC
hour, as ``<local_ns>\\t<message>`` lines: ``replay`` feeds those back through the engine, so a
night can be re-run with other settings. The engine's 100 ms ticks are kept too (``tick-*.log.gz``:
the time each one ran, and the ms it was given), so a replay of a recording that has them makes every
decision the live run made, in the same order.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import gzip
import heapq
import math
import re
import signal
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import websockets

from marketimmune.logger import init_logger
from marketimmune.paper import fastjson
from marketimmune.paper.dashboard import Board
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


CLOCK_WINDOW_S = 60
CLOCK_SLEW_MS = 1.0  # the most the correction moves in a tick (10 ms a second; a PC drifts ~0.02)


class Clock:
    """This machine's time, put on Coinbase's when ``correct``. A PC clock can be hundreds of ms off
    and drift (Caesar's ran 223-345 ms fast on 2026-11-06), and the engine times paper orders on it
    against Hyperliquid's block times. The offset is the least (receive time - Coinbase's timestamp)
    over the last minute, less ``NETWORK_FLOOR_MS``; it is applied at once when first known, then
    moved at most ``CLOCK_SLEW_MS`` a tick, and the corrected time never runs backwards. Every
    receive time the engine and the raw recording see is the corrected one; the tick lines keep the
    offset applied."""

    def __init__(self, correct: bool) -> None:
        self.correct = correct
        self.offset_ms = 0.0
        self.target_ms: float | None = None
        self.measured_ms: float | None = None  # the uncorrected least delay over the window
        self.least: deque[tuple[int, float]] = deque()  # (second, least delay in it)
        self.started = False
        self.last_ns = 0

    def observe(self, local_ns: int, raw: bytes | str) -> None:
        """A Coinbase message received at ``local_ns`` on this machine's own clock."""
        data = raw.encode() if isinstance(raw, str) else raw
        m = CB_STAMP.search(data, 0, 160)
        if m is None:
            return
        stamp = calendar.timegm(time.strptime(m.group(1).decode(), "%Y-%m-%dT%H:%M:%S")) * 1_000_000_000
        stamp += int(m.group(2).decode().ljust(9, "0")[:9])
        d, sec = (local_ns - stamp) / 1e6, local_ns // 1_000_000_000
        if self.least and self.least[-1][0] == sec:
            if d < self.least[-1][1]:
                self.least[-1] = (sec, d)
        else:
            self.least.append((sec, d))
        while self.least and self.least[0][0] <= sec - CLOCK_WINDOW_S:
            self.least.popleft()
        self.measured_ms = min(x[1] for x in self.least)
        self.target_ms = self.measured_ms - NETWORK_FLOOR_MS

    def step(self) -> None:
        """Once a tick: move the applied offset towards the measured one."""
        if not self.correct or self.target_ms is None:
            return
        if not self.started:
            self.offset_ms, self.started = self.target_ms, True
        else:
            self.offset_ms += max(-CLOCK_SLEW_MS, min(CLOCK_SLEW_MS, self.target_ms - self.offset_ms))

    def now_ns(self) -> int:
        t = time.time_ns() - int(self.offset_ms * 1e6)
        self.last_ns = max(self.last_ns, t)
        return self.last_ns

    def info(self) -> dict[str, Any]:
        return {
            "corrected": self.correct,
            "offset_ms": round(self.offset_ms, 1),
            "measured_ms": None if self.measured_ms is None else round(self.measured_ms, 1),
        }


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


async def hl_feed(engine: Engine, writer: RawWriter | None, clock: Clock) -> None:
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(HL_URL, max_size=2**24, ping_interval=None) as ws:
                for coin in engine.coins:
                    for channel in HL_CHANNELS + (("activeAssetCtx",) if ":" in coin else ()):  # HIP-3: the oracle is the reference
                        await ws.send(fastjson.dumps({"method": "subscribe", "subscription": {"type": channel, "coin": coin}}).decode())
                        await asyncio.sleep(0.02)
                logger.info(f"hyperliquid: subscribed {len(engine.coins)} coins")
                backoff = 1.0
                last_ping = time.monotonic()
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=HL_PING_S)
                    local_ns = clock.now_ns()
                    if writer is not None:
                        writer.write("hl", local_ns, raw)
                    for ev in parse_hl(fastjson.loads(raw), local_ns // 1_000_000):
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


async def cb_feed(engine: Engine, writer: RawWriter | None, clock: Clock) -> None:
    backoff = 1.0
    # HIP-3 markets (``dex:NAME``) have no Coinbase product; with none of the majors, BTC-USD is still
    # subscribed so the receive clock can be corrected (the engine ignores coins it does not trade)
    products = [f"{c}-USD" for c in engine.coins if ":" not in c] or ["BTC-USD"]
    while True:
        books = CoinbaseBooks()
        try:
            async with websockets.connect(CB_URL, max_size=2**26, ping_interval=20) as ws:
                await ws.send(fastjson.dumps({"type": "subscribe", "product_ids": products, "channel": "level2"}).decode())
                await ws.send(fastjson.dumps({"type": "subscribe", "channel": "heartbeats"}).decode())
                logger.info(f"coinbase: subscribed {len(products)} products")
                backoff = 1.0
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    clock.observe(time.time_ns(), raw)
                    local_ns = clock.now_ns()
                    if writer is not None:
                        writer.write("cb", local_ns, raw)
                    for ev in books.apply(fastjson.loads(raw), local_ns // 1_000_000):
                        engine.handle(ev, local_ns // 1_000_000)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # includes a sequence gap: reconnect for a fresh snapshot
            engine.gaps.append({"venue": "cb", "t_ms": now_ms(), "error": repr(e)[:200]})
            logger.warning(f"coinbase dropped ({e!r}); reconnecting in {backoff:.0f} s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def run_live(engine: Engine, out: Path, seconds: float, raw: bool, board: Board | None = None, clock: Clock | None = None) -> bool:
    """Until ``seconds`` have passed or SIGINT / SIGTERM arrives; either way the run is written by
    the caller. Returns True when a signal stopped it. ``board`` is refreshed every tick. ``clock``
    (kept across segments) puts receive times on Coinbase's clock when it corrects."""
    clock = clock or Clock(correct=False)
    writer = RawWriter(out / "raw") if raw else None
    feeds = [asyncio.create_task(hl_feed(engine, writer, clock)), asyncio.create_task(cb_feed(engine, writer, clock))]
    stop = time.monotonic() + seconds
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except NotImplementedError:  # Windows: no loop signal handlers; Ctrl+C still sets the event
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stopped.set))
    next_write = time.monotonic() + WRITE_S
    late = 0
    try:
        while time.monotonic() < stop and not stopped.is_set():
            await asyncio.sleep(TICK_MS / 1000)
            t0 = time.perf_counter()
            clock.step()
            tick_ns = clock.now_ns()
            if writer is not None:
                writer.write("tick", tick_ns, b"%d %.1f" % (tick_ns // 1_000_000, clock.offset_ms))
            engine.tick(tick_ns // 1_000_000)
            engine.clock = clock.info()
            if board is not None:
                board.sample(tick_ns // 1_000_000)
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
    return stopped.is_set()


def raw_lines(root: Path) -> Iterator[tuple[int, str, bytes]]:
    """Every recorded message under ``root`` in receive order: (local ns, venue, raw)."""

    def one(path: Path) -> Iterator[tuple[int, str, bytes]]:
        venue = path.name.split("-")[0]
        with gzip.open(path, "rb") as fh:
            try:
                for line in fh:
                    t, _, msg = line.rstrip(b"\n").partition(b"\t")
                    if msg and line.endswith(b"\n"):
                        yield int(t), venue, msg
            except EOFError:  # a file still being written, or cut by a crash: keep what is whole
                logger.warning(f"{path}: ends mid-stream; replaying the lines before the cut")

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
            msg = fastjson.loads(raw)
            if msg.get("channel") == "trades":
                msg["data"] = [x for x in msg["data"] if local_ms - int(x["time"]) <= STALE_TRADE_MS]
                raw = fastjson.dumps(msg)
            t = block_ms(msg)
            if t is None:
                if msg.get("channel") != "activeAssetCtx":
                    continue
                # an oracle update has no block time: it moves by as much as the feed's typical lag
                new = local_ms + retime["hl"] - retime.get("ctx_lag", 250)
            else:
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


CB_STAMP = re.compile(rb'"timestamp":"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d+)Z"')
NETWORK_FLOOR_MS = 15.0  # the least Coinbase to here, as the cloud measured it (14-25 ms)


def clock_offsets(root: Path, until_ms: int | None = None) -> dict[int, float]:
    """How far ahead of Coinbase's clock this machine's was, per UTC minute of the recording: the
    least (receive time - Coinbase's message timestamp) in the minute, less ``NETWORK_FLOOR_MS``.
    A clock that is ahead makes every order and cancel later against Hyperliquid's blocks. With
    ``until_ms``, only the lines received by then (as the recording's clock read)."""
    least: dict[int, float] = {}
    for local_ns, venue, raw in raw_lines(root):
        if until_ms is not None and local_ns > until_ms * 1_000_000:
            break
        if venue != "cb":
            continue
        m = CB_STAMP.search(raw, 0, 160)
        if m is None or b'"snapshot"' in raw[:200]:
            continue
        stamp = calendar.timegm(time.strptime(m.group(1).decode(), "%Y-%m-%dT%H:%M:%S")) * 1_000_000_000
        stamp += int(m.group(2).decode().ljust(9, "0")[:9])
        minute = local_ns // 60_000_000_000
        d = (local_ns - stamp) / 1e6
        if d < least.get(minute, math.inf):
            least[minute] = d
    return {k: v - NETWORK_FLOOR_MS for k, v in sorted(least.items())}


def reclocked(
    lines: Iterator[tuple[int, str, bytes]], offsets: dict[int, float] | float, causal: bool = False
) -> Iterator[tuple[int, str, bytes]]:
    """``lines`` with their receive times put on the right clock: minus the offset (a constant, or
    per minute from ``clock_offsets``, interpolated between minute midpoints, which keeps the order).

    The midpoints use up to 30 s of later Coinbase timestamps. ``causal``: a minute's offset is
    reached only one minute after that minute ends, so every receive time is corrected from
    timestamps received before it (the live ``Clock`` does the same over a rolling minute)."""
    if not isinstance(offsets, dict):
        shift = int(offsets * 1e6)
        for local_ns, venue, raw in lines:
            yield local_ns - shift, venue, raw
        return
    xs = np.asarray([((k + 2) * 60 if causal else k * 60 + 30) * 1e9 for k in offsets], np.float64)
    ys = np.asarray(list(offsets.values()), np.float64) * 1e6
    for local_ns, venue, raw in lines:
        yield local_ns - int(np.interp(local_ns, xs, ys)), venue, raw


def replay_lines(
    root: Path, retime: dict[str, int] | None = None, clock: dict[int, float] | float | None = None, causal: bool = False
) -> Iterator[tuple[int, str, bytes]]:
    """A recording's lines as ``replay`` feeds them: receive times put on the right clock first, then
    retimed (a Hyperliquid message from its block time, a Coinbase one from its corrected arrival)."""
    lines = raw_lines(root)
    if clock is not None:
        lines = reclocked(lines, clock, causal)
    if retime is not None:
        lines = retimed((x for x in lines if x[1] != "tick"), retime)
    return lines


def replay(
    engine: Engine,
    root: Path,
    retime: dict[str, int] | None = None,
    until_ms: int | None = None,
    clock: dict[int, float] | float | None = None,
    causal: bool = False,
) -> None:
    """Feed a recorded run through ``engine`` in receive order (or ``retimed``); with ``until_ms``,
    only the messages received by then (to compare with a live run's ``summary.json``, whose
    ``last_ms`` it is). The engine ticks when the live run did if the recording kept its ticks (and
    is not retimed), else every 100 ms of receive time. ``clock``: how far ahead this machine's clock
    was (``clock_offsets``, or ms; negative to play a slow clock fast), taken off every receive time."""
    books = CoinbaseBooks()
    next_tick: int | None = None
    exact = retime is None and any(root.glob("tick-*.log.gz"))
    for local_ns, venue, raw in replay_lines(root, retime, clock, causal):
        local_ms = local_ns // 1_000_000
        if until_ms is not None and local_ms > until_ms:
            break
        if venue == "tick":
            engine.tick(int(raw.split()[0]))
            continue
        if not exact:
            if next_tick is None:
                next_tick = local_ms
            while next_tick <= local_ms:
                engine.tick(next_tick)
                next_tick += TICK_MS
        msg: dict[str, Any] = fastjson.loads(raw)
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
