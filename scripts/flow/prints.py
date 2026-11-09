"""Every public trade print of a recording, with both wallets, and the best bid/ask series.

usage: prints.py OUT_DIR NAME=RAW_DIR [NAME=RAW_DIR ...]

Reads RAW_DIR/hl-*.log.gz (lines of "<receive ns>\\t<json>"). Writes, per NAME:
- OUT_DIR/NAME.prints.parquet: t_ms (block time), coin, side (+1 taker bought, -1 taker sold), px, sz,
  zero (the trade's hash is all zeros: not a user-signed order), taker, maker, tid;
- OUT_DIR/NAME.mids.parquet: t_ms, coin, bid, ask (from the bbo channel, on change).
Times are Hyperliquid's own (block) times, so the PC's clock does not matter. Trades older than the
recording's first quote of that coin (the subscription snapshot) are dropped."""

import glob
import gzip
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import orjson
import pandas as pd

ZERO = "0x" + "0" * 64


def lines(f: IO[bytes]) -> Iterator[bytes]:
    """Lines of a gzip file; a file cut off mid-write (a recorder that was killed) ends quietly."""
    try:
        yield from f
    except EOFError:
        return


def read(raw: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    prints, mids, seen = [], [], set()
    last: dict[str, tuple[str, str]] = {}
    for path in sorted(glob.glob(raw + "/hl-*.log.gz")):
        with gzip.open(path, "rb") as f:
            for line in lines(f):
                head = line[20:60]
                if b'"trades"' in head:
                    for d in orjson.loads(line.split(b"\t", 1)[1])["data"]:
                        key = (d["coin"], d["tid"])
                        if key in seen:
                            continue
                        seen.add(key)
                        buyer, seller = d["users"]
                        buy = d["side"] == "B"
                        prints.append(
                            (
                                d["time"],
                                d["coin"],
                                1 if buy else -1,
                                float(d["px"]),
                                float(d["sz"]),
                                d["hash"] == ZERO,
                                buyer if buy else seller,
                                seller if buy else buyer,
                                d["tid"],
                            )
                        )
                elif b'"bbo"' in head:
                    d = orjson.loads(line.split(b"\t", 1)[1])["data"]
                    b, a = d["bbo"]
                    if b is None or a is None:
                        continue
                    px = (b["px"], a["px"])
                    if last.get(d["coin"]) != px:
                        last[d["coin"]] = px
                        mids.append((d["time"], d["coin"], float(px[0]), float(px[1])))
    P = pd.DataFrame(prints, columns=["t_ms", "coin", "side", "px", "sz", "zero", "taker", "maker", "tid"])
    M = pd.DataFrame(mids, columns=["t_ms", "coin", "bid", "ask"])
    if len(P) and len(M):
        first = M.groupby("coin").t_ms.min()
        P = P[P.t_ms >= P.coin.map(first).fillna(float("inf"))]
    return P.sort_values(["t_ms", "tid"]).reset_index(drop=True), M.sort_values("t_ms").reset_index(drop=True)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for spec in sys.argv[2:]:
        name, raw = spec.split("=", 1)
        if (out / f"{name}.prints.parquet").exists():
            continue
        P, M = read(raw)
        P.to_parquet(out / f"{name}.prints.parquet", index=False)
        M.to_parquet(out / f"{name}.mids.parquet", index=False)
        print(name, len(P), "prints", len(M), "quotes", flush=True)


if __name__ == "__main__":
    main()
