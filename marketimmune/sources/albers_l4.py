"""Albers et al. December 2025 L4 dataset -> Silver L2 rows, order events and matches.

Dataset: Albers, Cucuringu, Howison & Shestopaloff, *An Open Book*, Zenodo,
doi:10.5281/zenodo.18184441 (CC BY 4.0). It has two streams per coin and hour:

* **order statuses**: 54-byte records, time-ordered, ``ts`` = block time in ns,
  one record per lifecycle step (``open``, ``filled`` with the *remaining* size,
  ``canceled``, rejections, ...);
* **book diffs**: JSON lines (``new`` / ``update`` / ``remove``) for orders that
  actually rested. They carry no timestamps and are grouped by order, not by time.

Neither stream alone gives a timed book. Statuses log ``open`` for marketable
limit orders that fill on entry and never rest, so a book built from statuses
alone crosses; diffs know what rested but not when. :class:`AlbersBook` takes
*which* orders rest (and at what size) from the diffs and *when* every change
happened from the statuses. Archive I/O lives in ``marketimmune/cli/build_albers_silver.py``.
"""

from __future__ import annotations

import bisect
import calendar
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
from isal import isal_zlib

from marketimmune.labels.markout import BPS
from marketimmune.lake.tables import L2_DEPTH
from marketimmune.sources.hyperliquid_node_fills import MatchFill

SOURCE = "albers-l4 doi:10.5281/zenodo.18184441"
STATUS_DTYPE = np.dtype(
    [
        ("ts", "<u8"),
        ("userId", "<u4"),
        ("isBuilder", "?"),
        ("statusId", "<u1"),
        ("isAsk", "?"),
        ("limitPx", "<u4"),
        ("sz", "<u4"),
        ("oid", "<u8"),
        ("timestampDiff", "<u4"),
        ("triggerCondition", "<i4"),
        ("triggered", "?"),
        ("isTrigger", "?"),
        ("hasChildren", "?"),
        ("isPositionTpsl", "?"),
        ("reduceOnly", "?"),
        ("orderTypeId", "<u1"),
        ("tifId", "<u1"),
        ("triggerPx", "<u4"),
        ("origSz", "<u4"),
    ]
)
STATUS_LABELS = (
    "badAloPxRejected",
    "open",
    "canceled",
    "perpMarginRejected",
    "iocCancelRejected",
    "filled",
    "minTradeNtlRejected",
    "reduceOnlyCanceled",
    "reduceOnlyRejected",
    "triggered",
    "scheduledCancel",
    "siblingFilledCanceled",
    "selfTradeCanceled",
    "marginCanceled",
    "vaultWithdrawalCanceled",
    "perpMaxPositionRejected",
    "liquidatedCanceled",
    "oracleRejected",
)
TIF_LABELS = ("Alo", "Gtc", "Ioc", "null", "FrontendMarket", "LiquidationMarket")
OPEN = STATUS_LABELS.index("open")
FILLED = STATUS_LABELS.index("filled")
TRIGGERED = STATUS_LABELS.index("triggered")
IOC_CANCEL_REJECTED = STATUS_LABELS.index("iocCancelRejected")
TIF_NULL = TIF_LABELS.index("null")
LIQUIDATION_MARKET = TIF_LABELS.index("LiquidationMarket")
# Statuses that take a resting order off the book (``filled`` does when size hits 0).
REMOVING = np.array(
    [
        STATUS_LABELS.index(name)
        for name in (
            "canceled",
            "reduceOnlyCanceled",
            "scheduledCancel",
            "siblingFilledCanceled",
            "selfTradeCanceled",
            "marginCanceled",
            "vaultWithdrawalCanceled",
            "liquidatedCanceled",
        )
    ],
    dtype=np.uint8,
)
PX_DECIMALS = 7  # prices are held as integer ticks of 1e-7
_PX_SCALE = float(10**PX_DECIMALS)
_VALUE_MASK = 0x1FFFFFFF
_POW10 = np.array([10.0**k for k in range(8)])
# What a status does to the book in ``replay_hour`` (0: nothing).
_ADD, _TRIGGER, _FILL, _FILL_OUT, _REMOVE = 1, 2, 3, 4, 5  # the last two take an order off
_CHUNK = 1 << 20  # compressed bytes inflated per step: ~9 MB of JSON stays in cache for the regex

L2_COLUMNS = (
    "coin",
    "ts_ms",
    "bid_px",
    "bid_sz",
    "bid_n",
    "ask_px",
    "ask_sz",
    "ask_n",
    "mid",
    "spread_bps",
    "microprice",
    "top_imbalance",
    *(f"{side}_{name}_{i}" for side in ("bid", "ask") for i in range(1, L2_DEPTH + 1) for name in ("px", "sz", "n")),
    "ts_ns",
)
_INT_COLUMNS = {"ts_ms", "ts_ns", "bid_n", "ask_n"} | {f"{side}_n_{i}" for side in ("bid", "ask") for i in range(1, L2_DEPTH + 1)}
# The archive-snapshot Silver L2 columns plus ``ts_ns``.
L2_SCHEMA = pa.schema(
    [(name, pa.string() if name == "coin" else pa.int64() if name in _INT_COLUMNS else pa.float64()) for name in L2_COLUMNS],
    metadata={"source": SOURCE},
)
EVENT_SCHEMA = pa.schema(
    [
        ("coin", pa.string()),
        ("ts_ns", pa.int64()),
        ("ts_ms", pa.int64()),
        ("kind", pa.string()),
        ("oid", pa.int64()),
        ("user_id", pa.int64()),
        ("user", pa.string()),
        ("is_ask", pa.bool_()),
        ("limit_px", pa.float64()),
        ("sz", pa.float64()),
        ("orig_sz", pa.float64()),
        ("tif", pa.string()),
        ("opposite_best_px", pa.float64()),
        ("marketable_at_block_start", pa.bool_()),
    ],
    metadata={"source": SOURCE},
)

# ``(oids, resting sizes)``; :func:`merge_rested` makes the oids sorted and unique.
Rested = tuple[npt.NDArray[np.uint64], npt.NDArray[np.float64]]
Level = tuple[int, float, int]  # (ticks, size, order count)
Top = tuple[tuple[Level, ...], tuple[Level, ...]]
L2Row = list[Any]  # values in ``L2_COLUMNS`` order


def decode_fixed(encoded: npt.ArrayLike) -> npt.NDArray[np.float64]:
    """Albers fixed point: bits 31-29 = decimals, bits 28-0 = integer value."""
    e = np.asarray(encoded, dtype=np.int64)
    out: npt.NDArray[np.float64] = (e & _VALUE_MASK) / _POW10[e >> 29]
    return out


def fixed_to_ticks(encoded: npt.ArrayLike) -> npt.NDArray[np.int64]:
    """Exact integer price in units of ``10**-PX_DECIMALS`` (no float keys in the book)."""
    e = np.asarray(encoded, dtype=np.int64)
    scale = (10 ** (PX_DECIMALS - (e >> 29))).astype(np.int64)
    return (e & _VALUE_MASK) * scale


def read_users_csv(lines: Iterable[str]) -> dict[int, str]:
    """``mapdir/users.csv`` (``<address>,<id>`` per line) -> ``id -> address``."""
    out: dict[int, str] = {}
    for line in lines:
        address, _, uid = line.strip().rpartition(",")
        if address:
            out[int(uid)] = address
    return out


def gunzip(data: bytes) -> bytes:
    """One gzip member through python-isal (2-3x faster than zlib, same bytes)."""
    out: bytes = isal_zlib.decompress(data, 16 + isal_zlib.MAX_WBITS)
    return out


def read_status_records(raw: bytes) -> npt.NDArray[np.void]:
    """Decompressed bytes of one ``<coin>_<HH>.data.gz`` member -> structured array."""
    assert len(raw) % STATUS_DTYPE.itemsize == 0, f"{len(raw)=} is not a whole number of 54-byte records"
    return np.frombuffer(raw, dtype=STATUS_DTYPE)


def rested_orders_gz(compressed: bytes, coin: str) -> Rested:
    """Oid and resting size of every ``new`` book diff of ``coin`` in one gzipped
    hourly ``ex<H>.gz`` member, in file order.

    The member holds every coin's diffs (about 1.6 GB of JSON per hour). Lines are
    written with a fixed key order (``user, oid, coin, side, px, raw_book_diff``),
    so one regex reads them without ``json.loads``; the first chunk asserts that
    order. The resting size can be below the submitted size when a limit order
    filled part of itself on entry and rested the remainder.
    """
    symbol = coin.upper().encode()
    pattern = re.compile(
        rb'"oid":(\d++),"coin":"' + re.escape(symbol) + rb'","side":"[AB]","px":"[^"]*+","raw_book_diff":\{"new":\{"sz":"([^"]++)"\}\}'
    )
    found: list[tuple[bytes, bytes]] = []
    inflater = isal_zlib.decompressobj(16 + isal_zlib.MAX_WBITS)
    tail = b""
    for start in range(0, len(compressed), _CHUNK):
        chunk = inflater.decompress(compressed[start : start + _CHUNK])
        if start == 0:
            n_any, n_ordered = chunk.count(b'"coin":"' + symbol + b'"'), chunk.count(b',"coin":"' + symbol + b'","side":"')
            assert n_any == n_ordered, f"{coin}: {n_any - n_ordered} diff lines break the key order"
        first, last = chunk.find(b"\n") + 1, chunk.rfind(b"\n") + 1
        if first == 0:  # no line ends in this chunk
            tail += chunk
            continue
        found += pattern.findall(tail + chunk[:first])
        found += pattern.findall(chunk, first, last)
        tail = chunk[last:]
    found += pattern.findall(tail + inflater.flush())
    if not found:
        return np.zeros(0, dtype=np.uint64), np.zeros(0)
    oids, sizes = zip(*found, strict=True)
    # NOTE: numpy parses the byte strings exactly as int() and float() would.
    return np.array(oids, dtype=np.bytes_).astype(np.uint64), np.array(sizes, dtype=np.bytes_).astype(np.float64)


def drop_replayed(records: npt.NDArray[np.void], max_ts: int | None) -> npt.NDArray[np.void]:
    """Statuses in time order, without the archive's replays.

    The December status files sometimes jump back minutes in time and repeat a window
    (2025-12-09 12:41:50 back to 12:39:44; 12-15, 12-18, 12-21 and 12-30 too). Every
    record behind the newest timestamp seen so far (``max_ts`` carries it across hours)
    is an exact copy of an earlier one, so it is dropped; so are exact copies at the seam.
    Replaying them re-opened cancelled orders and crossed the book for hours.
    """
    ts = records["ts"].astype(np.int64)
    if ts.size == 0 or (bool(np.all(ts[1:] >= ts[:-1])) and (max_ts is None or int(ts[0]) >= max_ts)):
        return records
    before = np.maximum.accumulate(np.concatenate(([-1 if max_ts is None else max_ts], ts[:-1])))
    kept = records[ts >= before]
    _, first = np.unique(kept.view(np.dtype((np.void, kept.dtype.itemsize))), return_index=True)
    return kept[np.sort(first)]


def merge_rested(*parts: Rested) -> Rested:
    """Sorted unique oids with their resting size; a later part (or line) wins."""
    oids = np.concatenate([o for o, _ in parts])[::-1]
    sizes = np.concatenate([s for _, s in parts])[::-1]
    keys, first = np.unique(oids, return_index=True)
    return keys, sizes[first]


@dataclass(slots=True)
class _Side:
    prices: list[int] = field(default_factory=list)  # ascending ticks
    levels: dict[int, list[float]] = field(default_factory=dict)  # ticks -> [sz, n]

    def top(self, *, descending: bool) -> tuple[Level, ...]:
        out = []
        for px in self.prices[-L2_DEPTH:][::-1] if descending else self.prices[:L2_DEPTH]:
            sz, n = self.levels[px]
            out.append((px, max(round(sz, 9), 0.0), int(n)))
        return tuple(out)


@dataclass(slots=True)
class ReplayStats:
    """Per-hour counts that say whether the rebuilt book can be trusted."""

    records: int = 0
    blocks: int = 0
    rows: int = 0
    opens_rested: int = 0
    opens_not_resting: int = 0
    trigger_opens_deferred: int = 0
    triggers_rested: int = 0
    triggers_marketable: int = 0
    replayed_dropped: int = 0
    resting_fills: int = 0
    fills_at_touch: int = 0
    fills_in_top_depth: int = 0
    crossed_blocks: int = 0
    one_sided_blocks: int = 0
    liquidation_fills: int = 0
    ioc_unfilled: int = 0
    ioc_unfilled_marketable: int = 0
    resting_orders_end: int = 0

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["fill_at_touch_share"] = self.fills_at_touch / self.resting_fills if self.resting_fills else None
        out["crossed_share"] = self.crossed_blocks / self.blocks if self.blocks else None
        return out


class AlbersBook:
    """Order-by-order book for one coin, carried across hours."""

    def __init__(self, coin: str, users: Mapping[int, str]) -> None:
        self.coin = coin.upper()
        self.users = users  # userId -> wallet address, for order events
        self.orders: dict[int, tuple[bool, int, float]] = {}  # oid -> (is_ask, ticks, sz)
        self.bids = _Side()
        self.asks = _Side()
        self._last_top: Top | None = None
        # False only while the top ``L2_DEPTH`` levels are known to equal the last
        # top that was computed, so a block that left them alone skips ``top()``.
        self._dirty = True

    def reset(self) -> None:
        """Forget every resting order.

        Used after a gap in the data (the archives miss 2025-12-12 17:40:43 to
        18:16:01 UTC): orders that left the book during the gap left no status, so
        keeping them would cross the book for the rest of the month. The book then
        rebuilds from new orders, like the start of a run.
        """
        self.orders.clear()
        self.bids = _Side()
        self.asks = _Side()
        self._last_top = None
        self._dirty = True

    def replay_hour(self, records: npt.NDArray[np.void], rested: Rested, stats: ReplayStats) -> tuple[list[L2Row], pa.Table]:
        """Apply one hour of statuses; return a Silver L2 row per block whose top
        ``L2_DEPTH`` levels changed, and the hour's order events.

        ``rested`` (from :func:`merge_rested`) must hold the ``new`` diffs of this
        hour *and the next one*: the two streams cut hours on slightly different
        clocks. ``stats`` accumulates the validation counts.

        An order event is a forced-liquidation fill (``kind = "liquidation"``) or
        an IOC whose remainder was cancelled (``kind = "ioc_unfilled"``). Each
        records the opposite best at the start of the block, so an unfilled IOC
        whose limit crossed it (``marketable_at_block_start``) is a race lost
        inside the block: the quote it aimed at was cancelled or taken first. That
        is the fee-free analogue of v3's missed-race feature.

        Only records that can change the book or make an event run through the
        Python loop; rejections, opens that never rested and statuses of orders the
        book never held are counted with NumPy. A block with none of the former
        leaves the book as it was, so it is counted without being replayed.
        """
        n = int(records.size)
        if n == 0:
            return [], EVENT_SCHEMA.empty_table()
        stats.records += n
        ts = records["ts"].astype(np.int64)
        status, tif, oids = records["statusId"], records["tifId"], records["oid"]
        new_block = np.concatenate(([True], ts[1:] != ts[:-1]))
        block_ts = ts[new_block].tolist()
        block_of = np.cumsum(new_block) - 1

        keys, sizes = rested
        pos = np.searchsorted(keys, oids)
        inside = pos < keys.size
        in_rested = np.zeros(n, dtype=bool)
        in_rested[inside] = keys[pos[inside]] == oids[inside]
        held = in_rested | np.isin(oids, np.fromiter(self.orders, dtype=np.uint64, count=len(self.orders)))
        is_open = status == OPEN
        deferred = is_open & (records["isTrigger"] | (tif == TIF_NULL))
        opens = is_open & ~deferred
        filled = status == FILLED
        liquidation = filled & (tif == LIQUIDATION_MARKET)
        stats.trigger_opens_deferred += int(np.count_nonzero(deferred))
        stats.opens_not_resting += int(np.count_nonzero(opens & ~in_rested))
        stats.opens_rested += int(np.count_nonzero(opens & in_rested))
        stats.liquidation_fills += int(np.count_nonzero(liquidation))

        code = np.zeros(n, dtype=np.int8)
        code[opens & in_rested] = _ADD
        code[(status == TRIGGERED) & in_rested] = _TRIGGER
        code[filled & held] = _FILL
        code[np.isin(status, REMOVING) & held] = _REMOVE
        wants_event = (status == IOC_CANCEL_REJECTED) | liquidation
        idx = np.flatnonzero((code != 0) | wants_event)
        kinds = code[idx]
        sub_sz = decode_fixed(records["sz"][idx])
        kinds[(kinds == _FILL) & (sub_sz <= 0.0)] = _FILL_OUT
        rest_sz = np.zeros(idx.size)
        hit = in_rested[idx]
        rest_sz[hit] = sizes[pos[idx[hit]]]

        rows: list[L2Row] = []
        raised: list[tuple[int, int | None, bool]] = []  # (position in idx, opposite best, marketable)
        orders = self.orders
        bp, bl, ap, al = self.bids.prices, self.bids.levels, self.asks.prices, self.asks.levels
        depth = L2_DEPTH
        insort, bisect_left = bisect.insort, bisect.bisect_left
        dirty = self._dirty
        cur = -1
        bid0 = ask0 = None
        # The book updates below are inlined (about 2M an hour), each with the check
        # of whether it touched the top ``depth`` levels of its side.
        for j, (block, kind, o, is_new_ask, px, sz, rsz, event) in enumerate(
            zip(
                block_of[idx].tolist(),
                kinds.tolist(),
                oids[idx].tolist(),
                records["isAsk"][idx].tolist(),
                fixed_to_ticks(records["limitPx"][idx]).tolist(),
                sub_sz.tolist(),
                rest_sz.tolist(),
                wants_event[idx].tolist(),
                strict=True,
            )
        ):
            if block != cur:
                self._dirty = dirty
                self._close_blocks(max(cur, 0), block, block_ts, rows, stats)
                dirty = self._dirty
                cur = block
                bid0 = bp[-1] if bp else None
                ask0 = ap[0] if ap else None
            if event:
                opposite = bid0 if is_new_ask else ask0
                raised.append((j, opposite, opposite is not None and (px <= opposite if is_new_ask else px >= opposite)))
            # A re-opened oid takes its old entry off first, then rests again below.
            if kind >= _FILL_OUT or (kind == _ADD and o in orders):
                entry = orders.pop(o, None)
                if entry is None:
                    continue
                is_ask, opx, osz = entry
                prices, levels = (ap, al) if is_ask else (bp, bl)
                if kind == _FILL_OUT:  # a resting order filled to zero
                    stats.resting_fills += 1
                    stats.fills_at_touch += int(opx == (prices[0] if is_ask else prices[-1]))
                    stats.fills_in_top_depth += int(opx in (prices[:depth] if is_ask else prices[-depth:]))
                if not dirty and (len(prices) <= depth or (opx <= prices[depth - 1] if is_ask else opx >= prices[-depth])):
                    dirty = True
                level = levels[opx]
                level[1] -= 1.0
                if level[1] <= 0.0:
                    del levels[opx]
                    del prices[bisect_left(prices, opx)]
                else:
                    level[0] -= osz
                if kind != _ADD:
                    continue
            if kind == _FILL:  # partial fill: shrink in place
                entry = orders.get(o)
                if entry is None:
                    continue
                is_ask, opx, old = entry
                prices, levels = (ap, al) if is_ask else (bp, bl)
                # Checked at the event, not the block start: post-only orders
                # placed earlier in the same block can be hit at a better price.
                stats.resting_fills += 1
                stats.fills_at_touch += int(opx == (prices[0] if is_ask else prices[-1]))
                stats.fills_in_top_depth += int(opx in (prices[:depth] if is_ask else prices[-depth:]))
                orders[o] = (is_ask, opx, sz)
                levels[opx][0] += sz - old
                if not dirty and (len(prices) <= depth or (opx <= prices[depth - 1] if is_ask else opx >= prices[-depth])):
                    dirty = True
            elif kind == _ADD or (kind == _TRIGGER and o not in orders):
                if kind == _TRIGGER:
                    # NOTE: a trigger order has a ``new`` diff from its placement whether or not it
                    # ever rests. Fired at a limit through the opposite best it trades as a taker
                    # (2025-12-19 04:11: a buy stop at 131.61 with the market at 121.86 crossed the
                    # book for 28 hours), so it rests only if it would not cross.
                    if (bool(bp) and px <= bp[-1]) if is_new_ask else (bool(ap) and px >= ap[0]):
                        stats.triggers_marketable += 1
                        continue
                    stats.triggers_rested += 1
                orders[o] = (is_new_ask, px, rsz)
                prices, levels = (ap, al) if is_new_ask else (bp, bl)
                existing = levels.get(px)
                if existing is None:
                    levels[px] = [rsz, 1.0]
                    insort(prices, px)
                else:
                    existing[0] += rsz
                    existing[1] += 1.0
                if not dirty and (len(prices) <= depth or (px <= prices[depth - 1] if is_new_ask else px >= prices[-depth])):
                    dirty = True
        self._dirty = dirty
        self._close_blocks(max(cur, 0), len(block_ts), block_ts, rows, stats)
        stats.rows += len(rows)
        stats.resting_orders_end = len(orders)
        return rows, self._events(records, idx, raised, ts, stats)

    def _close_blocks(self, first: int, end: int, block_ts: list[int], rows: list[L2Row], stats: ReplayStats) -> None:
        """End blocks ``first..end-1``, during which the book did not change after
        ``first``: the first may emit a row, the rest repeat its classification."""
        if end <= first:
            return
        count = end - first
        stats.blocks += count
        bp, ap = self.bids.prices, self.asks.prices
        if not bp or not ap:
            stats.one_sided_blocks += count
            return
        if bp[-1] >= ap[0]:
            stats.crossed_blocks += count
        if not self._dirty:
            return  # the top levels equal the last computed top, so no new row
        self._dirty = False
        top = (self.bids.top(descending=True), self.asks.top(descending=False))
        if top == self._last_top:
            return
        self._last_top = top
        rows.append(_l2_row(self.coin, top, block_ts[first]))

    def _events(
        self,
        records: npt.NDArray[np.void],
        idx: npt.NDArray[np.intp],
        raised: list[tuple[int, int | None, bool]],
        ts: npt.NDArray[np.int64],
        stats: ReplayStats,
    ) -> pa.Table:
        at = idx[[j for j, _, _ in raised]]
        unfilled = records["statusId"][at] == IOC_CANCEL_REJECTED
        marketable = np.array([m for _, _, m in raised], dtype=bool)
        stats.ioc_unfilled += int(np.count_nonzero(unfilled))
        stats.ioc_unfilled_marketable += int(np.count_nonzero(unfilled & marketable))
        user_id = records["userId"][at].astype(np.int64)
        columns = {
            "coin": [self.coin] * at.size,
            "ts_ns": ts[at],
            "ts_ms": ts[at] // 1_000_000,
            "kind": np.where(unfilled, "ioc_unfilled", "liquidation"),
            "oid": records["oid"][at].astype(np.int64),
            "user_id": user_id,
            "user": [self.users[u] for u in user_id.tolist()],
            "is_ask": records["isAsk"][at],
            "limit_px": fixed_to_ticks(records["limitPx"][at]) / _PX_SCALE,
            "sz": decode_fixed(records["sz"][at]),
            "orig_sz": decode_fixed(records["origSz"][at]),
            "tif": np.array(TIF_LABELS)[records["tifId"][at]],
            "opposite_best_px": [None if o is None else o / _PX_SCALE for _, o, _ in raised],
            "marketable_at_block_start": marketable,
        }
        return pa.Table.from_pydict(columns, schema=EVENT_SCHEMA)


def _l2_row(coin: str, top: Top, ts_ns: int) -> L2Row:
    """The book's top levels as one row in ``L2_COLUMNS`` order (the arithmetic of
    ``silver_l2_book_record``)."""
    bids, asks = top
    (bid_t, bid_sz, bid_n), (ask_t, ask_sz, ask_n) = bids[0], asks[0]
    bid_px, ask_px = bid_t / _PX_SCALE, ask_t / _PX_SCALE
    mid = (bid_px + ask_px) / 2.0
    total = bid_sz + ask_sz
    assert total > 0.0, f"top-of-book size is zero at {ts_ns=}"
    row: L2Row = [
        coin,
        ts_ns // 1_000_000,
        bid_px,
        bid_sz,
        bid_n,
        ask_px,
        ask_sz,
        ask_n,
        mid,
        (ask_px - bid_px) / mid * BPS,
        (bid_px * ask_sz + ask_px * bid_sz) / total,
        (bid_sz - ask_sz) / total,
    ]
    for levels in top:
        for t, sz, cnt in levels:
            row += (t / _PX_SCALE, sz, cnt)
        row += (None, None, None) * (L2_DEPTH - len(levels))
    row.append(ts_ns)
    return row


def l2_table(rows: list[L2Row]) -> pa.Table:
    if not rows:
        return L2_SCHEMA.empty_table()
    return pa.Table.from_arrays(
        [pa.array(col, type=f.type) for col, f in zip(zip(*rows, strict=True), L2_SCHEMA, strict=True)], schema=L2_SCHEMA
    )


@lru_cache(maxsize=1 << 16)
def _epoch_seconds(stamp: str) -> int:
    date, _, clock = stamp.partition("T")
    y, mo, d = (int(x) for x in date.split("-"))
    h, mi, sec = (int(x) for x in clock.split(":"))
    return calendar.timegm((y, mo, d, h, mi, sec, 0, 0, 0))


def iso_to_ns(text: str) -> int:
    """``2025-12-01T00:00:01.388469225`` (UTC, up to 9 fraction digits) -> epoch ns."""
    whole, _, frac = text.rstrip("Z").partition(".")
    return _epoch_seconds(whole) * 1_000_000_000 + int((frac + "000000000")[:9])


def match_from_albers_trade(trade: Mapping[str, Any], liquidation_oids: set[int]) -> MatchFill:
    """One Albers trade -> :class:`MatchFill`.

    ``side`` is the aggressor (``B`` = taker bought) and ``side_info`` is
    ``[buyer, seller]``; on SOL hour 2025-12-01 00, 94% of trades have the side
    opposite the aggressor in that hour's ``new`` book diffs (the rest rested
    before the hour). The trade carries no fees and no ``tid``; ``liquidation``
    comes from the taker oid being a ``LiquidationMarket`` order.
    """
    buyer, seller = trade["side_info"]
    taker_bought = trade["side"] == "B"
    taker, maker = (buyer, seller) if taker_bought else (seller, buyer)
    return MatchFill(
        coin=str(trade["coin"]),
        ts_ms=iso_to_ns(str(trade["time"])) // 1_000_000,
        px=float(trade["px"]),
        sz=float(trade["sz"]),
        taker_side="B" if taker_bought else "A",
        trade_hash=trade.get("hash"),
        maker_user=maker.get("user"),
        taker_user=taker.get("user"),
        maker_oid=int(maker["oid"]) if maker.get("oid") is not None else None,
        taker_oid=int(taker["oid"]) if taker.get("oid") is not None else None,
        maker_start_position=_opt_float(maker.get("start_pos")),
        taker_start_position=_opt_float(taker.get("start_pos")),
        liquidation=taker.get("oid") in liquidation_oids,
        n_legs=2,
    )


def albers_trades_member_to_matches(data: bytes, coin: str, liquidation_oids: set[int]) -> list[MatchFill]:
    """Matches for ``coin`` from one decompressed hourly trades member (all coins,
    JSON lines). Finds ``coin``'s lines with ``bytes.find`` instead of walking every
    line in Python, then parses only those."""
    symbol = coin.upper()
    needle = f'"{symbol}"'.encode()
    out: list[MatchFill] = []
    pos = data.find(needle)
    while pos != -1:
        start = data.rfind(b"\n", 0, pos) + 1
        end = data.find(b"\n", pos)
        if end == -1:
            end = len(data)
        trade = json.loads(data[start:end])
        if trade["coin"] == symbol:
            out.append(match_from_albers_trade(trade, liquidation_oids))
        pos = data.find(needle, end)
    return out


def _opt_float(value: object) -> float | None:
    return None if value is None or value == "" else float(str(value))
