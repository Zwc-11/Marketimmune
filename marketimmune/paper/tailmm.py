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
* **Moving the touch:** an order whose price is no longer the best is cancelled and requoted at the
  new touch, at the back of the queue.
* **Through-fills:** a trade through the price fills the order.

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
        v.sort(key=lambda e: (e[0], e[1]))
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


def run(events: list[tuple[int, int, Any]], p: Tail, start_ms: int, end_ms: int) -> dict[str, Any]:
    """Replay one coin from ``start_ms`` to ``end_ms``: fills, PnL marked to the mid and closed at the
    touch, and the spread and adverse move of each fill."""
    pos = 0.0  # coins
    cash = 0.0
    fills: list[tuple[int, int, float, float, float]] = []  # t, side, px, qty, mid at fill
    orders: dict[int, _Order | None] = {1: None, -1: None}
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
            if warm:
                continue
            # a taker buy (aggr=+1) hits asks: our ask fills; a taker sell hits bids
            o = orders[-aggr]
            if o is not None and t >= o.live_ms and o.ahead == np.inf and best is not None:
                # live since the last book update: behind everything displayed at its price then
                shown = (
                    best[1]
                    if o.side == 1 and abs(best[0] - o.px) <= 1e-12
                    else best[3]
                    if o.side == -1 and abs(best[2] - o.px) <= 1e-12
                    else np.inf
                )
                o.ahead = shown
            if o is not None and t >= o.live_ms:
                through = (px > o.px + 1e-12) if aggr == 1 else (px < o.px - 1e-12)
                at = abs(px - o.px) <= 1e-12
                filled = 0.0
                if through:
                    filled = qty_coins
                elif at:
                    o.ahead -= sz
                    if o.ahead < 0:
                        filled = min(qty_coins, -o.ahead)
                if filled > 0:
                    side = -aggr  # our side
                    mid = (best[0] + best[2]) / 2 if best else o.px
                    pos += side * filled
                    cash -= side * filled * o.px + filled * o.px * p.maker * 1e-4
                    fills.append((t, side, o.px, filled, mid))
                    orders[side] = None
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
        buy = sum(v for _, s, v in flow if s == 1)
        sell = sum(v for _, s, v in flow if s == -1)
        units = pos / qty_coins if qty_coins else 0.0
        for side, px, sz in ((1, bid, bsz), (-1, ask, asz)):
            o = orders[side]
            want = spread >= p.min_spread - 1e-9
            if side * units >= p.n_max - 1e-9:
                want = False
            if units * side < -1e-9:  # reducing the position: always quote at the touch
                want = True
            if p.flow_s > 0 and want and units * side >= -1e-9:
                hit = sell if side == 1 else buy
                other = buy if side == 1 else sell
                if hit > p.flow_ratio * (other + 1.0) and hit > p.quote_usd:
                    want = False
            if not want:
                orders[side] = None
                continue
            if o is not None and abs(o.px - px) <= 1e-12:
                if t >= o.live_ms:
                    if o.ahead == np.inf:
                        o.ahead = sz
                    o.ahead = min(o.ahead, sz)
                continue
            if o is not None and ((side == 1 and px < o.px - 1e-12) or (side == -1 and px > o.px + 1e-12)) and t >= o.live_ms:
                # the touch moved through our price without a trade print: filled at our price
                pos += side * qty_coins
                cash -= side * qty_coins * o.px + qty_coins * o.px * p.maker * 1e-4
                fills.append((t, side, o.px, qty_coins, mid))
                orders[side] = None
                continue
            orders[side] = _Order(side, px, t + p.latency_ms)
    if best is None:
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
        "end_units": float(pos / qty_coins) if qty_coins else 0.0,
        "fills_table": f,
    }
