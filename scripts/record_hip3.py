"""Record HIP-3 public messages as receive-ns<TAB>JSON in hourly gzip files."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import websockets

from marketimmune.paper import fastjson
from marketimmune.paper.live import RawWriter


async def record(coins: tuple[str, ...], root: Path) -> None:
    writer = RawWriter(root)
    try:
        while True:
            try:
                async with websockets.connect("wss://api.hyperliquid.xyz/ws", open_timeout=20, ping_interval=20, max_size=2**24) as ws:
                    for coin in coins:
                        for channel in ("bbo", "trades", "activeAssetCtx"):
                            await ws.send(fastjson.dumps({"method": "subscribe", "subscription": {"type": channel, "coin": coin}}).decode())
                            await asyncio.sleep(0.02)
                    last_flush = time.monotonic()
                    async for raw in ws:
                        writer.write("hl", time.time_ns(), raw)
                        if time.monotonic() - last_flush > 5:
                            for _, handle in writer.files.values():
                                handle.flush()
                            last_flush = time.monotonic()
            except (OSError, websockets.WebSocketException, TimeoutError) as error:
                print(time.strftime("%H:%M:%S"), "reconnect", repr(error), flush=True)
                await asyncio.sleep(2)
    finally:
        writer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coins", help="comma-separated instrument names")
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    asyncio.run(record(tuple(coin.strip() for coin in args.coins.split(",") if coin.strip()), args.out))


if __name__ == "__main__":
    main()
