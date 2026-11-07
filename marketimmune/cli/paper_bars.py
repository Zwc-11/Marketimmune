"""One-second bars from the raw recordings: per coin and second, the last Hyperliquid best bid and
ask (block time), the last Coinbase best bid and ask (from the level-2 book, receive time on the
PC clock, which runs ahead, so Coinbase is if anything stamped late), and Hyperliquid's taker
volume by side.

    python -m marketimmune.cli.paper_bars --raw data/paper/seg2-20261106T0448/raw ... --out data/paper/bars

One parquet per raw directory (named after its parent). Columns: coin, t (second, ms), hl_bid,
hl_ask, cb_bid, cb_ask (carried forward), buy_usd, sell_usd, trades.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from marketimmune.paper.events import CoinbaseBooks
from marketimmune.paper.fastjson import loads
from marketimmune.paper.live import raw_lines

COINS = ("BTC", "ETH", "SOL", "XRP", "LTC", "BCH", "LINK", "AVAX", "DOGE")


def bars(raw: Path) -> pd.DataFrame:
    hl: dict[tuple[str, int], tuple[float, float]] = {}
    cb: dict[tuple[str, int], tuple[float, float]] = {}
    flow: dict[tuple[str, int], list[float]] = {}
    books = CoinbaseBooks()
    for local_ns, venue, msg in raw_lines(raw):
        if venue == "hl":
            m = loads(msg)
            ch = m.get("channel")
            if ch == "bbo":
                d = m["data"]
                b, a = d["bbo"]
                if b and a:
                    hl[(d["coin"], d["time"] // 1000)] = (float(b["px"]), float(a["px"]))
            elif ch == "trades":
                for tr in m["data"]:
                    k = (tr["coin"], tr["time"] // 1000)
                    f = flow.setdefault(k, [0.0, 0.0, 0.0])
                    usd = float(tr["px"]) * float(tr["sz"])
                    f[0 if tr["side"] == "B" else 1] += usd
                    f[2] += 1
        elif venue == "cb":
            m = loads(msg)
            try:
                tops = books.apply(m, local_ns // 1_000_000)
            except AssertionError:  # a sequence gap: the recorder reconnected; start a fresh book
                books = CoinbaseBooks()
                tops = books.apply(m, local_ns // 1_000_000)
            for t in tops:
                cb[(t.coin, t.t_ms // 1000)] = (t.bid, t.ask)
    frames = []
    for coin in COINS:
        ks = sorted(s for c, s in hl if c == coin)
        if not ks:
            continue
        sec = np.arange(ks[0], ks[-1] + 1)
        h = pd.DataFrame([hl[(coin, s)] for s in ks], index=ks, columns=["hl_bid", "hl_ask"]).reindex(sec).ffill()
        cs = sorted(s for c, s in cb if c == coin)
        c = pd.DataFrame([cb[(coin, s)] for s in cs], index=cs, columns=["cb_bid", "cb_ask"]).reindex(sec).ffill()
        fl = pd.DataFrame(
            [flow.get((coin, s), [0.0, 0.0, 0.0]) for s in sec], index=sec, columns=["buy_usd", "sell_usd", "trades"]
        )
        df = pd.concat([h, c, fl], axis=1)
        df.insert(0, "t", sec * 1000)
        df.insert(0, "coin", coin)
        frames.append(df.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True)


def _one(args: tuple[Path, Path]) -> str:
    raw, out = args
    dest = out / f"{raw.parent.name}.parquet"
    if dest.exists():
        return f"{dest} exists"
    df = bars(raw)
    df.to_parquet(dest)
    return f"{dest}: {len(df)} rows, {df['t'].min()}-{df['t'].max()}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(a.workers) as ex:
        for line in ex.map(_one, [(r, a.out) for r in a.raw]):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
