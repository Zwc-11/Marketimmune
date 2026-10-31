"""The hftbacktest baseline: the same day, as continuous L2 depth plus trades, with S1 run by
hftbacktest (nkaz001/hftbacktest) under its own queue models.

hftbacktest knows no blocks: its exchange matches our orders against the trade prints and
estimates queue position from depth changes at our price (``risk_adverse`` or the power
probability model). It is the continuous-time check on ``marketimmune.sim.engine``: same book,
same takers and the same strategy, with independent queue and latency handling.

* Depth: each Silver L2 row is diffed against the previous one. A level whose size changed or
  that is new is sent with its size. A level gone from inside the visible range is sent as 0. A
  level that only fell below the fifth is left as last seen.
* Trades: every fill of a resting order in the near-touch L4 events, at the maker's price, with
  the taker's side.
* Latency: the feed arrives ``feed_ns`` after its block, and an order reaches the exchange
  ``entry_ns`` after it is sent. The engine's ``delay_ns`` is their sum.
* Exchange: ``NoPartialFillExchange``, so an order the queue model says was reached fills in full.
  NOTE: with ``PartialFillExchange`` and the risk-averse model, hftbacktest 2.4.4 stops with
  error 14 (``InvalidOrderStatus``) on SOL 2025-12-01 after 147 s of quoting, with both orders
  resting and unfilled. So compare fill counts and bps per filled dollar, not notional.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from hftbacktest import (
    BUY_EVENT,
    DEPTH_EVENT,
    EXCH_EVENT,
    GTX,
    LIMIT,
    LOCAL_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    BacktestAsset,
    HashMapMarketDepthBacktest,
    event_dtype,
)
from hftbacktest.order import BUY, CANCELED, NEW, PARTIALLY_FILLED
from numba import njit, types
from numba.typed import Dict

from marketimmune.sim.attribution import PX_SCALE
from marketimmune.sim.engine import FILL, DayBook, FloatArray, IntArray, MakerResult

HFT_QUEUE_MODELS = ("risk_adverse", "power_prob3")
_FILLS_CAP = 4_000_000


def _depth_diffs(ts: IntArray, px: IntArray, sz: FloatArray, *, bid: bool) -> tuple[IntArray, IntArray, FloatArray]:
    """(ts, px ticks, size) of every level that changed between consecutive L2 rows on one side:
    new or resized levels with their size, and levels gone from inside the visible range with 0."""
    prev_px, prev_sz = np.vstack([np.zeros((1, px.shape[1]), np.int64), px[:-1]]), np.vstack([np.zeros((1, sz.shape[1])), sz[:-1]])
    same = px[:, :, None] == prev_px[:, None, :]  # (rows, level now, level before)
    matched = same.any(axis=2)
    before = np.where(matched, (same * prev_sz[:, None, :]).sum(axis=2), np.nan)
    changed = (px > 0) & ~(matched & (before == sz))
    deepest = np.where(px > 0, px, np.iinfo(np.int64).max).min(axis=1) if bid else px.max(axis=1)
    gone = (prev_px > 0) & ~same.any(axis=1) & ((prev_px > deepest[:, None]) if bid else (prev_px < deepest[:, None]))
    rows_c, cols_c = np.nonzero(changed)
    rows_g, cols_g = np.nonzero(gone)
    return (
        np.concatenate([ts[rows_c], ts[rows_g]]),
        np.concatenate([px[rows_c, cols_c], prev_px[rows_g, cols_g]]),
        np.concatenate([sz[rows_c, cols_c], np.zeros(rows_g.size)]),
    )


def day_events(book: DayBook, *, feed_ns: int) -> npt.NDArray[np.void]:
    """hftbacktest events for one day: L2 depth diffs and trade prints, in exchange time order
    (a block's trades before the L2 row that shows the book after it)."""
    parts: list[tuple[npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any], npt.NDArray[Any], int]] = []  # ts, flags, px, qty, rank
    for bid, px, sz in ((True, book.bid_px, book.bid_sz), (False, book.ask_px, book.ask_sz)):
        ts, p, q = _depth_diffs(book.l2_ts, px, sz, bid=bid)
        parts.append(
            (ts, np.full(ts.size, DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT | (BUY_EVENT if bid else SELL_EVENT), np.uint64), p, q, 1)
        )
    fills = book.ev_kind == FILL
    flags = np.where(book.ev_ask[fills], BUY_EVENT, SELL_EVENT).astype(np.uint64) | np.uint64(TRADE_EVENT | EXCH_EVENT | LOCAL_EVENT)
    parts.append((book.ev_ts[fills], flags, book.ev_px[fills], book.ev_sz[fills], 0))
    ts = np.concatenate([x[0] for x in parts])
    rank = np.concatenate([np.full(x[0].size, x[4]) for x in parts])
    order = np.lexsort((rank, ts))
    out = np.zeros(ts.size, dtype=event_dtype)
    out["ev"] = np.concatenate([x[1] for x in parts])[order]
    out["exch_ts"] = ts[order]
    out["local_ts"] = ts[order] + feed_ns
    out["px"] = np.concatenate([x[2] for x in parts])[order] / PX_SCALE
    out["qty"] = np.concatenate([x[3] for x in parts])[order]
    return out


@njit
def _touch_quoter(hbt, qty, max_position, step_ns, fills):  # type: ignore[no-untyped-def]  # noqa: ANN001, ANN202
    """S1 in hftbacktest: every ``step_ns`` join the best bid and ask (post-only) within the
    position limit; record each order's newly executed size as a fill (ts, side, px, qty)."""
    left = Dict.empty(key_type=types.uint64, value_type=types.float64)
    n = 0
    next_id = np.uint64(1)
    while hbt.elapse(step_ns) == 0:
        orders = hbt.orders(0)
        values = orders.values()
        while values.has_next():
            o = values.get()
            if o.order_id in left:
                done = left[o.order_id] - o.leaves_qty
                if done > 1e-12 and n < fills.shape[0]:
                    fills[n, 0] = o.exch_timestamp  # the fill's exchange time, not the step's
                    fills[n, 1] = 1.0 if o.side == BUY else -1.0
                    fills[n, 2] = o.price
                    fills[n, 3] = done
                    n += 1
                left[o.order_id] = o.leaves_qty
        hbt.clear_inactive_orders(0)
        depth = hbt.depth(0)
        position = hbt.position(0)
        want_bid = depth.best_bid_tick if position < max_position else np.int64(-1)
        want_ask = depth.best_ask_tick if position > -max_position else np.int64(-1)
        have_bid = False
        have_ask = False
        values = orders.values()
        while values.has_next():
            o = values.get()
            active = (o.status == NEW or o.status == PARTIALLY_FILLED or o.req == NEW) and o.req != CANCELED
            if not active:
                continue
            want = want_bid if o.side == BUY else want_ask
            if o.price_tick == want:
                if o.side == BUY:
                    have_bid = True
                else:
                    have_ask = True
            elif o.cancellable:
                hbt.cancel(0, o.order_id, False)
        tick = depth.tick_size
        if want_bid > 0 and not have_bid:
            hbt.submit_buy_order(0, next_id, want_bid * tick, qty, GTX, LIMIT, False)
            left[next_id] = qty
            next_id += np.uint64(1)
        if want_ask > 0 and not have_ask:
            hbt.submit_sell_order(0, next_id, want_ask * tick, qty, GTX, LIMIT, False)
            left[next_id] = qty
            next_id += np.uint64(1)
    return n


def run_touch_quoter(
    events: npt.NDArray[np.void],
    *,
    queue: str,
    qty: float,
    max_position: float,
    tick: float,
    lot: float,
    entry_ns: int,
    step_ns: int = 100_000_000,
) -> MakerResult:
    """S1 through hftbacktest; fills come back in the engine's form (prices in ticks)."""
    assert queue in HFT_QUEUE_MODELS, f"{queue=}"
    asset = (
        BacktestAsset()
        .data(events)
        .linear_asset(1.0)
        .constant_order_latency(entry_ns, entry_ns)
        .no_partial_fill_exchange()
        .trading_value_fee_model(0.0, 0.0)  # fees are charged in ``attribution``
        .tick_size(tick)
        .lot_size(lot)
    )
    asset = asset.risk_adverse_queue_model() if queue == "risk_adverse" else asset.power_prob_queue_model(3.0)
    hbt = HashMapMarketDepthBacktest([asset])
    fills = np.zeros((_FILLS_CAP, 4))
    n = int(_touch_quoter(hbt, qty, max_position, step_ns, fills))
    hbt.close()
    assert n < _FILLS_CAP, f"{n=}: raise _FILLS_CAP"
    f = fills[:n]
    return MakerResult(
        f"S1/hftbacktest_{queue}",
        ts=f[:, 0].astype(np.int64).tolist(),
        side=f[:, 1].astype(np.int64).tolist(),
        px=np.rint(f[:, 2] * PX_SCALE).astype(np.int64).tolist(),
        qty=f[:, 3].tolist(),
    )
