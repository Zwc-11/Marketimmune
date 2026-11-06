"""The decision journal of a paper run: what every strategy did, and what it saw when it did it.

Five gzipped JSON-lines files under ``<out>/journal/``. Each is flushed every minute of the run, and
a flush ends a deflate block, so the lines up to the last flush can be read while the run goes on or
after a crash (``read`` keeps what is whole). Times: ``t`` is local ms (when this machine saw it),
``blk`` is Hyperliquid block ms. Signals are in bps.

- ``signals.jsonl.gz``: each second, each coin. ``mid``, ``spr`` (spread), ``cb`` (Coinbase mid),
  ``gap`` (Coinbase over Hyperliquid less the 5-minute basis), ``z`` (gap over its own volatility),
  ``fc`` (10 s forecast), ``m1`` (1 s ridge model), ``sig`` (1 s volatility), ``bb`` / ``sb``
  (buy / sell burst: Hawkes intensity over its base), ``blk`` (block of the top).
- ``decisions.jsonl.gz``: each change of the sides a maker quotes on a coin: ``s`` (strategy),
  ``c`` (coin), ``want`` (sides the quoter asked for), ``sides`` (after the budget), ``why`` (the
  quoter's reason), ``pos`` (position, coins), ``pos_usd``, and ``ctx`` (the signals above).
- ``fills.jsonl.gz``: every paper fill. Maker: ``placed`` (local ms of the decision), ``live``
  (block ms the order reached the book), ``q0`` (queue ahead when it joined), ``ahead`` (queue ahead
  just before this fill), ``through`` (the trade went through the order's price), ``mid0`` (the
  last Hyperliquid mid before the fill's block), ``ctx`` (signals when the order was placed).
  Taker: ``leg`` (entry or exit), ``ctx`` (signals at the decision). Both: ``blk``, ``side``
  (+1 bought), ``px``, ``qty``, ``fee`` (USD), ``pos`` (position after, coins).
- ``minutes.jsonl.gz``: each minute, each strategy and coin: ``orders`` and ``cancels`` sent,
  ``fills``, ``ms`` (time quoted with both sides, bid only, ask only, none), ``budget`` (decisions
  where the budget dropped a side), ``changes`` (side changes), ``pos_usd``, ``equity``.
- ``taker.jsonl.gz``: each taker decision (entry or exit sent), with ``ctx``.

Order actions themselves (thousands a minute per strategy) are counted, not listed: the raw
recording replays every one of them (``paper.live.replay``).
"""

from __future__ import annotations

import gzip
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from marketimmune.logger import init_logger
from marketimmune.paper import fastjson
from marketimmune.paper.signals import CoinState

logger = init_logger(__name__)
STREAMS = ("signals", "decisions", "fills", "minutes", "taker")
SIGNAL_MS = 1_000
SIDES = ("both", "bid", "ask", "none")


def num(x: float | None, digits: int = 4) -> float | None:
    """``x`` rounded, or None when missing or not finite (JSON has no NaN)."""
    if x is None or not math.isfinite(x):
        return None
    return round(float(x), digits)


def context(coin: CoinState, local_ms: int) -> dict[str, Any]:
    """The signals a strategy could see on ``coin`` at ``local_ms``."""
    top, ref = coin.top, coin.ref
    gap = coin.gap()
    gs = coin.gap_sigma
    return {
        "mid": top.mid if top else None,
        "spr": num((top.ask - top.bid) / top.mid * 1e4, 3) if top else None,
        "cb": ref.mid if ref else None,
        "gap": num(gap, 3),
        "z": num(gap / gs, 3) if gap is not None and gs else None,
        "fc": num(coin.forecast(), 3),
        "m1": num(coin.predict(local_ms), 3),
        "sig": num(coin.sigma_1s, 3),
        "bb": num(coin.intensity_ratio(1, local_ms), 3),
        "sb": num(coin.intensity_ratio(-1, local_ms), 3),
    }


class Journal:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.files = {k: gzip.GzipFile(root / f"{k}.jsonl.gz", "ab", compresslevel=1) for k in STREAMS}
        self.rows = dict.fromkeys(STREAMS, 0)
        self.closed = False

    def write(self, stream: str, row: dict[str, Any]) -> None:
        if not self.closed:
            self.files[stream].write(fastjson.dumps(row) + b"\n")
            self.rows[stream] += 1

    def flush(self) -> None:
        if not self.closed:
            for fh in self.files.values():
                fh.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for fh in self.files.values():
            fh.close()
        logger.info(f"journal {self.root}: " + ", ".join(f"{k} {v}" for k, v in self.rows.items()))


def read(path: Path) -> Iterator[dict[str, Any]]:
    """The whole lines of one journal file, also while it is being written."""
    with gzip.open(path, "rb") as fh:
        try:
            for line in fh:
                if line.endswith(b"\n"):
                    yield fastjson.loads(line)
        except EOFError:
            pass
