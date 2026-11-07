"""A touch market maker for Hyperliquid perps whose spread is wider than two maker fees (the
"long tail"), replayed from recorded ``bbo`` and ``trades`` messages with a queue model.

Orders:
* **Quotes:** join the best bid and the best ask with ``quote_usd`` each, only while the spread is
  at least ``min_spread`` bps. A quote reaches the book ``latency_ms`` after the decision.
* **Inventory:** up to ``n_max`` quotes of inventory a side. With a position, the side that would
  add to it stops once the limit is reached; the other side keeps quoting at the touch.
* **Flow filter (``flow_s`` > 0):** the side that taker flow over the last ``flow_s`` seconds is
  hitting harder (by more than ``flow_ratio`` to 1) is not quoted.

Queue model (as ``paper.engine``):
* **On arrival:** an order joins behind everything displayed at its price.
* **Trades:** takers at that price eat the queue ahead first.
* **Cancels:** they come from behind, unless the displayed size falls below the queue ahead.
* **Fills:** only trades fill an order, at its price once the queue ahead is gone, or through it.
* **Repricing:** an order whose price is no longer the touch is cancelled after the latency and
  requoted at the back of the new touch. Until the cancel lands, it can still be filled.

Fees: maker 1.5 bp per fill. Positions are marked to the mid at the end, and also closed at the
touch with the taker fee (``flat_usd``) for a conservative figure.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def load_events(raw: list[Path]) -> dict[str, list[tuple[int, int, Any]]]:
    """Per coin, time-ordered events: (block ms, kind 0=bbo 1=trade, payload)."""
    ev: dict[str, list[tuple[int, int, Any]]] = {}
    for f in sorted(raw):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    try:
                        m = json.loads(line.split("\t", 1)[1])
                    except (ValueError, IndexError):
                        continue
                    ch = m.get("channel")
                    if ch == "bbo":
                        d = m["data"]
                        b, a = d["bbo"]
                        if b and a:
                            ev.setdefault(d["coin"], []).append(
                                (d["time"], 0, (float(b["px"]), float(b["sz"]), float(a["px"]), float(a["sz"])))
                            )
                    elif ch == "trades":
                        for tr in m["data"]:
                            ev.setdefault(tr["coin"], []).append(
                                (tr["time"], 1, (float(tr["px"]), float(tr["sz"]), 1 if tr["side"] == "B" else -1))
                            )
        except EOFError:
            pass
    for v in ev.values():
        v.sort(key=lambda e: (e[0], -e[1]))  # in the same block, trades before the book update they caused
    return ev


@dataclass(frozen=True)
class Tail:
    min_spread: float = 3.0
    n_max: int = 1
    flow_s: float = 0.0
    flow_ratio: float = 3.0
    quote_usd: float = 200.0
    latency_ms: int = 200
    maker: float = 1.5
    taker: float = 4.5

    def label(self) -> str:
        return f"tail@spread={self.min_spread:g}/n={self.n_max}/flow={self.flow_s:g}"


@dataclass
class _Order:
    side: int
    px: float
    live_ms: int
    ahead: float = np.inf
    cancel_ms: int = 2**62


def run(events: list[tuple[int, int, Any]], p: Tail, start_ms: int, end_ms: int) -> dict[str, Any]:
    """Replay one coin from ``start_ms`` to ``end_ms``: fills, PnL marked to the mid and closed at the
    touch, and the spread captured by each fill.

    * **Repricing:** a quote whose price is no longer the touch is cancelled ``latency_ms`` later
      and replaced at the new touch, live after the same delay.
    * **Exposure while cancelling:** if the touch moved away from the quote because the level was
      pulled, the quote is the best price until the cancel lands, first in the queue. A taker trading
      through it in that window fills it.
    * **Fills come only from trades:** at the quote's price once the queue ahead is eaten, or
      through it.
    """
    pos = 0.0  # coins
    cash = 0.0
    fills: list[tuple[int, int, float, float, float]] = []  # t, side, px, qty, mid at fill
    live: dict[int, list[_Order]] = {1: [], -1: []}
    best: tuple[float, float, float, float] | None = None
    flow: list[tuple[int, int, float]] = []
    qty_coins = 0.0
    for t, kind, x in events:
        if t < start_ms - 600_000:
            continue
        if t >= end_ms:
            break
        warm = t < start_ms
        if kind == 1:
            px, sz, aggr = x
            flow.append((t, aggr, px * sz))
            if warm or qty_coins == 0.0:
                continue
            side = -aggr  # a taker sell (aggr -1) hits bids: our side +1
            for o in list(live[side]):
                if t < o.live_ms or t >= o.cancel_ms:
                    continue
                if o.ahead == np.inf and best is not None:
                    o.ahead = (
                        best[1]
                        if side == 1 and abs(best[0] - o.px) <= 1e-12
                        else best[3]
                        if side == -1 and abs(best[2] - o.px) <= 1e-12
                        else 0.0
                    )
                through = (px < o.px - 1e-12) if side == 1 else (px > o.px + 1e-12)
                filled = 0.0
                if through:
                    filled = qty_coins
                elif abs(px - o.px) <= 1e-12:
                    o.ahead -= sz
                    if o.ahead < 0:
                        filled = qty_coins  # the rest of the trade fills the whole quote (sizes here are small)
                if filled > 0:
                    mid = (best[0] + best[2]) / 2 if best else o.px
                    pos += side * filled
                    cash -= side * filled * o.px + filled * o.px * p.maker * 1e-4
                    fills.append((t, side, o.px, filled, mid))
                    live[side] = []  # one quote a side: a fill ends it, and its replacement
                    break
            continue
        bid, bsz, ask, asz = x
        best = x
        if warm:
            continue
        mid = (bid + ask) / 2
        if qty_coins == 0.0:
            qty_coins = p.quote_usd / mid
        spread = (ask - bid) / mid * 1e4
        while flow and flow[0][0] < t - max(p.flow_s, 1.0) * 1000:
            flow.pop(0)
        buy = sum(v for _, s_, v in flow if s_ == 1)
        sell = sum(v for _, s_, v in flow if s_ == -1)
        units = pos / qty_coins
        for side, px, sz in ((1, bid, bsz), (-1, ask, asz)):
            live[side] = [o for o in live[side] if o.cancel_ms > t]
            want = spread >= p.min_spread - 1e-9 and side * units < p.n_max - 1e-9
            if units * side < -1e-9:  # reducing the position: always quote at the touch
                want = True
            if p.flow_s > 0 and want and units * side >= -1e-9:
                hit, other = (sell, buy) if side == 1 else (buy, sell)
                if hit > p.flow_ratio * (other + 1.0) and hit > p.quote_usd:
                    want = False
            current = [o for o in live[side] if o.cancel_ms == 2**62]
            for o in current:
                if want and abs(o.px - px) <= 1e-12:
                    if t >= o.live_ms:
                        o.ahead = sz if o.ahead == np.inf else min(o.ahead, sz)
                    continue
                o.cancel_ms = t + p.latency_ms
                if (side == 1 and o.px > px + 1e-12) or (side == -1 and o.px < px - 1e-12):
                    o.ahead = 0.0  # the level was pulled: alone at the top until the cancel lands
            if want and not any(o.cancel_ms == 2**62 for o in live[side]):
                live[side].append(_Order(side, px, t + p.latency_ms))
    if best is None or qty_coins == 0.0:
        return {"fills": 0}
    bid, _, ask, _ = best
    mid = (bid + ask) / 2
    marked = cash + pos * mid
    flat = cash + (pos * bid if pos > 0 else pos * ask) - abs(pos) * mid * p.taker * 1e-4
    f = pd.DataFrame(fills, columns=["t", "side", "px", "qty", "mid"])
    return {
        "fills": len(f),
        "notional": float((f["px"] * f["qty"]).sum()) if len(f) else 0.0,
        "pnl_marked_usd": float(marked),
        "pnl_flat_usd": float(flat),
        "spread_bps": float((f["side"] * (f["mid"] / f["px"] - 1) * 1e4).mean()) if len(f) else float("nan"),
        "end_units": float(pos / qty_coins),
        "fills_table": f,
    }
