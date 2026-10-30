"""Always-on market-data recorder (Lesson 3.6).

Writes every WebSocket message as one line, ``<local_ns> <raw_json>``, where
``local_ns`` is the receive time from a chrony-disciplined clock. That is the
input format hftbacktest's Hyperliquid converter reads, so the same files feed
the continuous-matching baseline.

Layout: ``<out>/<venue>/<YYYYMMDD>/<HH>.log`` (UTC hours). ``rotate.sh`` zstd-
compresses closed hours. Every connect, disconnect and error goes to
``<out>/gaps.jsonl`` so gaps are explicit missing-data windows, and message
counts go to ``<out>/stats.jsonl`` once a minute.

Depends only on ``websockets``. Check docs/jurisdiction.md before pointing it at
live endpoints.

    python record.py --out /var/lib/pop/recorder
    python record.py --out /tmp/rec --max-seconds 60     # smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import websockets

HL_URL = "wss://api.hyperliquid.xyz/ws"
BN_URL = "wss://fstream.binance.com/stream?streams=btcusdt@bookTicker/ethusdt@bookTicker/solusdt@bookTicker"
COINS = ("BTC", "ETH", "SOL")
HL_CHANNELS = ("l2Book", "bbo", "trades")
HL_PING_S = 50.0  # Hyperliquid drops connections idle for 60 s
FLUSH_S = 1.0


def hl_subscriptions(
    coins: Sequence[str] = COINS, channels: Sequence[str] = HL_CHANNELS
) -> list[dict[str, Any]]:
    return [{"method": "subscribe", "subscription": {"type": t, "coin": c}} for c in coins for t in channels]


class HourlyWriter:
    """Append lines to ``<root>/<YYYYMMDD>/<HH>.log``, switching files on the UTC hour."""

    def __init__(self, root: Path, clock_ns: Callable[[], int] = time.time_ns) -> None:
        self.root = root
        self.clock_ns = clock_ns
        self._hour: int | None = None
        self._fh: TextIO | None = None
        self.lines = 0

    def path_for(self, t_ns: int) -> Path:
        t = time.gmtime(t_ns // 1_000_000_000)
        return self.root / time.strftime("%Y%m%d", t) / f"{t.tm_hour:02d}.log"

    def write(self, t_ns: int, raw: str) -> None:
        hour = t_ns // 3_600_000_000_000
        if hour != self._hour or self._fh is None:
            self.close()
            p = self.path_for(t_ns)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = p.open("a", encoding="utf-8", buffering=1 << 16)
            self._hour = hour
        self._fh.write(f"{t_ns} {raw}\n")
        self.lines += 1

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


@dataclass
class Feed:
    venue: str
    url: str
    subscriptions: list[dict[str, Any]] = field(default_factory=list)
    app_ping: dict[str, Any] | None = None  # sent every HL_PING_S if set


class JsonlLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def write(self, **rec: Any) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t_ns": time.time_ns(), **rec}) + "\n")


async def run_feed(
    feed: Feed,
    writer: HourlyWriter,
    gaps: JsonlLog,
    counts: Counter[str],
    stop: asyncio.Event,
    max_backoff_s: float = 30.0,
) -> None:
    """Keep one feed connected until ``stop`` is set; log every gap."""
    backoff = 1.0
    while not stop.is_set():
        try:
            async with websockets.connect(
                feed.url, ping_interval=20, ping_timeout=20, max_size=2**24, open_timeout=15
            ) as ws:
                for s in feed.subscriptions:
                    await ws.send(json.dumps(s))
                gaps.write(venue=feed.venue, event="connected", url=feed.url)
                backoff = 1.0
                pinger = asyncio.create_task(_app_ping(ws, feed)) if feed.app_ping else None
                try:
                    async for msg in _until(ws, stop):
                        t = time.time_ns()
                        writer.write(t, msg if isinstance(msg, str) else msg.decode())
                        counts[feed.venue] += 1
                finally:
                    if pinger:
                        pinger.cancel()
                if stop.is_set():
                    break
                gaps.write(venue=feed.venue, event="closed", code=ws.close_code, reason=ws.close_reason)
        except Exception as e:  # any failure is a gap; reconnect
            gaps.write(venue=feed.venue, event="error", error=f"{type(e).__name__}: {e}")
        if stop.is_set():
            break
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        backoff = min(max_backoff_s, backoff * 2)
    gaps.write(venue=feed.venue, event="stopped")


async def _until(ws: Any, stop: asyncio.Event) -> Any:
    """Iterate messages until the socket closes or ``stop`` is set."""
    stop_task = asyncio.create_task(stop.wait())
    try:
        while True:
            recv = asyncio.create_task(ws.recv())
            done, _ = await asyncio.wait({recv, stop_task}, return_when=asyncio.FIRST_COMPLETED)
            if recv not in done:
                recv.cancel()
                return
            try:
                yield recv.result()
            except websockets.ConnectionClosed:
                return
    finally:
        stop_task.cancel()


async def _app_ping(ws: Any, feed: Feed) -> None:
    while True:
        await asyncio.sleep(HL_PING_S)
        await ws.send(json.dumps(feed.app_ping))


async def _flusher(
    writers: Sequence[HourlyWriter], counts: Counter[str], stats: JsonlLog, stop: asyncio.Event
) -> None:
    last_stats = time.monotonic()
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=FLUSH_S)
        for w in writers:
            w.flush()
        if time.monotonic() - last_stats >= 60:
            stats.write(messages=dict(counts))
            counts.clear()
            last_stats = time.monotonic()


async def record(
    out: Path, feeds: Sequence[Feed], max_seconds: float | None = None, handle_signals: bool = False
) -> dict[str, int]:
    """Record until ``max_seconds`` elapse or, with ``handle_signals``, SIGINT/SIGTERM."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    if handle_signals:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows / non-main thread
                loop.add_signal_handler(sig, stop.set)
    writers = {f.venue: HourlyWriter(out / f.venue) for f in feeds}
    gaps, stats = JsonlLog(out / "gaps.jsonl"), JsonlLog(out / "stats.jsonl")
    counts: Counter[str] = Counter()
    tasks = [asyncio.create_task(run_feed(f, writers[f.venue], gaps, counts, stop)) for f in feeds]
    tasks.append(asyncio.create_task(_flusher(list(writers.values()), counts, stats, stop)))
    if max_seconds is not None:
        loop.call_later(max_seconds, stop.set)
    await asyncio.gather(*tasks)
    for w in writers.values():
        w.close()
    return {v: w.lines for v, w in writers.items()}


def default_feeds() -> list[Feed]:
    return [
        Feed("hyperliquid", HL_URL, hl_subscriptions(), app_ping={"method": "ping"}),
        Feed("binance", BN_URL),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Hyperliquid + Binance WebSocket recorder")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-seconds", type=float, default=None, help="stop after this long (smoke tests)")
    args = ap.parse_args(argv)
    lines = asyncio.run(record(args.out, default_feeds(), args.max_seconds, handle_signals=True))
    print(json.dumps({"lines": lines}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
