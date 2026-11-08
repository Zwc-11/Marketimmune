"""Record Hyperliquid bbo, trades (with users) and activeAssetCtx (oracle, mark) for HIP-3 markets,
in the paper recorder's raw format (receive ns<TAB>json, hourly gz)."""
import asyncio, gzip, json, sys, time
import websockets
COINS = sys.argv[1].split(',')
OUT = sys.argv[2]
async def run():
    while True:
        try:
            async with websockets.connect('wss://api.hyperliquid.xyz/ws', open_timeout=20, ping_interval=20, max_size=None) as ws:
                for c in COINS:
                    for typ in ('bbo', 'trades', 'activeAssetCtx'):
                        await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": typ, "coin": c}}))
                hour = None; f = None; last = 0
                while True:
                    m = await ws.recv()
                    ns = time.time_ns()
                    h = time.strftime('%Y%m%d%H', time.gmtime(ns / 1e9))
                    if h != hour:
                        if f: f.close()
                        f = gzip.open(f'{OUT}/hl-{h}.log.gz', 'at'); hour = h
                    f.write(f'{ns}\t{m}\n')
                    if ns - last > 5e9: f.flush(); last = ns
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'reconnect', repr(e), flush=True); await asyncio.sleep(2)
asyncio.run(run())
