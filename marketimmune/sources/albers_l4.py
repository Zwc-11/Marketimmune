"""Albers et al. December 2025 L4 dataset -> Silver L2 rows (v3 Phase 0 on SOL).

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
happened from the statuses. Everything here is pure; archive I/O lives in
``marketimmune/cli/build_albers_silver.py``.
"""

from __future__ import annotations

import bisect
import calendar
import importlib
import json
import re
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.lake.tables import L2_DEPTH
from marketimmune.sources.hyperliquid_l2_archive import BPS, BookSnapshot, L2Level
from marketimmune.sources.hyperliquid_node_fills import MatchFill


def _fast_zlib() -> ModuleType:
    """python-isal's zlib when installed (``pip install .[fast]``): it inflates gzip
    2-3x faster with byte-for-byte the same output. Otherwise the standard zlib."""
    try:
        return importlib.import_module("isal.isal_zlib")
    except ImportError:  # pragma: no cover - optional speedup
        return zlib


_zlib = _fast_zlib()


STATUS_DTYPE = np.dtype([
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
])
STATUS_LABELS = (
    "badAloPxRejected", "open", "canceled", "perpMarginRejected", "iocCancelRejected",
    "filled", "minTradeNtlRejected", "reduceOnlyCanceled", "reduceOnlyRejected", "triggered",
    "scheduledCancel", "siblingFilledCanceled", "selfTradeCanceled", "marginCanceled",
    "vaultWithdrawalCanceled", "perpMaxPositionRejected", "liquidatedCanceled", "oracleRejected",
)
TIF_LABELS = ("Alo", "Gtc", "Ioc", "null", "FrontendMarket", "LiquidationMarket")
OPEN = STATUS_LABELS.index("open")
FILLED = STATUS_LABELS.index("filled")
TRIGGERED = STATUS_LABELS.index("triggered")
TIF_NULL = TIF_LABELS.index("null")
LIQUIDATION_MARKET = TIF_LABELS.index("LiquidationMarket")
IOC_CANCEL_REJECTED = STATUS_LABELS.index("iocCancelRejected")
# Statuses that take a resting order off the book (``filled`` does when size hits 0).
REMOVING = frozenset(
    STATUS_LABELS.index(name)
    for name in (
        "canceled", "reduceOnlyCanceled", "scheduledCancel", "siblingFilledCanceled",
        "selfTradeCanceled", "marginCanceled", "vaultWithdrawalCanceled", "liquidatedCanceled",
    )
)
_REMOVING_IDS = np.array(sorted(REMOVING), dtype=np.uint8)
# What a record does to the book in ``replay_hour`` (0: nothing).
_ADD, _TRIGGER, _FILL, _REMOVE = 1, 2, 3, 4
PX_DECIMALS = 7  # prices are held as integer ticks of 1e-7
_VALUE_MASK = 0x1FFFFFFF
_POW10 = np.array([10.0**k for k in range(8)])


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


def ticks_to_px(ticks: int) -> float:
    return float(ticks) / float(10**PX_DECIMALS)


def read_users_csv(lines: Iterable[str]) -> dict[int, str]:
    """``mapdir/users.csv`` (``<address>,<id>`` per line) -> ``id -> address``."""
    out: dict[int, str] = {}
    for line in lines:
        address, _, uid = line.strip().rpartition(",")
        if address:
            out[int(uid)] = address
    return out


def gunzip(data: bytes) -> bytes:
    """``gzip.decompress`` through python-isal when it is installed (2-3x faster)."""
    out: bytes = _zlib.decompress(data, 16 + _zlib.MAX_WBITS)
    return out


def read_status_records(raw: bytes) -> npt.NDArray[np.void]:
    """Decompressed bytes of one ``<coin>_<HH>.data.gz`` member -> structured array."""
    if len(raw) % STATUS_DTYPE.itemsize:
        raise ValueError(f"{len(raw)} bytes is not a whole number of 54-byte records")
    return np.frombuffer(raw, dtype=STATUS_DTYPE)


def rested_orders(lines: Iterable[str], coin: str) -> dict[int, float]:
    """``oid -> resting size`` for every ``new`` book diff of ``coin``.

    The resting size can be below the submitted size when a limit order filled
    part of itself on entry and rested the remainder.
    """
    symbol = coin.upper()
    needle = f'"{symbol}"'  # cheap prefilter; the parsed coin is checked below
    out: dict[int, float] = {}
    for line in lines:
        if needle not in line or '"new"' not in line:
            continue
        record = json.loads(line)
        if record.get("coin") != symbol:
            continue
        diff = record.get("raw_book_diff")
        if isinstance(diff, Mapping) and isinstance(diff.get("new"), Mapping):
            out[int(record["oid"])] = float(diff["new"]["sz"])
    return out


_CHUNK = 1 << 24


def rested_orders_gz(compressed: bytes, coin: str) -> dict[int, float]:
    """:func:`rested_orders` for one gzipped hourly ``ex<H>.gz`` member, ~2x faster.

    The member holds every coin's diffs (about 1.6 GB of JSON per hour). Lines are
    written with a fixed key order (``user, oid, coin, side, px, raw_book_diff``),
    so one regex reads the oid and resting size of each ``new`` diff of ``coin``
    without ``json.loads``; on 2025-12-01 hour 0 the result equals
    :func:`rested_orders` for all 1,028,827 SOL diffs. A chunk where a ``coin``
    line breaks that order is parsed with :func:`rested_orders` instead.
    """
    symbol = re.escape(coin.upper().encode())
    pattern = re.compile(
        rb'"oid":(\d+),"coin":"' + symbol
        + rb'","side":"[AB]","px":"[^"]*","raw_book_diff":\{"new":\{"sz":"([^"]+)"\}\}'
    )
    any_order = b'"coin":"' + coin.upper().encode() + b'"'
    in_order = b',"coin":"' + coin.upper().encode() + b'","side":"'
    out: dict[int, float] = {}

    def scan(buf: bytes, lo: int, hi: int) -> None:
        if buf.count(any_order, lo, hi) == buf.count(in_order, lo, hi):
            out.update((int(oid), float(sz)) for oid, sz in pattern.findall(buf, lo, hi))
        else:  # a line of this coin breaks the key order: parse the chunk as JSON
            out.update(rested_orders(buf[lo:hi].decode().splitlines(), coin))

    inflater = _zlib.decompressobj(16 + _zlib.MAX_WBITS)
    tail = b""
    for start in range(0, len(compressed), _CHUNK):
        chunk = inflater.decompress(compressed[start : start + _CHUNK])
        first = chunk.find(b"\n") + 1
        last = chunk.rfind(b"\n") + 1
        if first == 0:  # no line ends in this chunk
            tail += chunk
            continue
        head = tail + chunk[:first]
        scan(head, 0, len(head))
        scan(chunk, first, last)
        tail = chunk[last:]
    tail += inflater.flush()
    scan(tail, 0, len(tail))
    return out


@dataclass
class _Side:
    prices: list[int] = field(default_factory=list)  # ascending ticks
    levels: dict[int, list[float]] = field(default_factory=dict)  # ticks -> [sz, n]

    def add(self, px: int, sz: float) -> None:
        level = self.levels.get(px)
        if level is None:
            self.levels[px] = [sz, 1.0]
            bisect.insort(self.prices, px)
        else:
            level[0] += sz
            level[1] += 1.0

    def change(self, px: int, delta: float) -> None:
        self.levels[px][0] += delta

    def drop(self, px: int, sz: float) -> None:
        level = self.levels[px]
        level[1] -= 1.0
        if level[1] <= 0.0:
            del self.levels[px]
            del self.prices[bisect.bisect_left(self.prices, px)]
        else:
            level[0] -= sz

    def top(self, depth: int, *, descending: bool) -> tuple[tuple[int, float, int], ...]:
        picks = self.prices[-depth:][::-1] if descending else self.prices[:depth]
        return tuple(
            (px, max(round(self.levels[px][0], 9), 0.0), int(self.levels[px][1])) for px in picks
        )


@dataclass
class ReplayStats:
    """Per-hour counts that say whether the rebuilt book can be trusted."""

    records: int = 0
    blocks: int = 0
    rows: int = 0
    opens_rested: int = 0
    opens_not_resting: int = 0
    trigger_opens_deferred: int = 0
    triggers_rested: int = 0
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
        out: dict[str, Any] = dict(self.__dict__)
        out["fill_at_touch_share"] = (
            self.fills_at_touch / self.resting_fills if self.resting_fills else None
        )
        out["crossed_share"] = self.crossed_blocks / self.blocks if self.blocks else None
        return out


class AlbersBook:
    """Order-by-order book for one coin, carried across hours."""

    def __init__(self, coin: str, depth: int = L2_DEPTH) -> None:
        self.coin = coin.upper()
        self.depth = depth
        self.orders: dict[int, tuple[bool, int, float]] = {}  # oid -> (is_ask, ticks, sz)
        self.bids = _Side()
        self.asks = _Side()
        self._last_top: tuple[Any, ...] | None = None
        # False only while the top ``depth`` levels are known to equal the last
        # top that was computed, so a block that left them alone skips ``top()``.
        self._dirty = True

    def _side(self, is_ask: bool) -> _Side:
        return self.asks if is_ask else self.bids

    def add(self, oid: int, is_ask: bool, px: int, sz: float) -> None:
        self._dirty = True
        if oid in self.orders:
            self.remove(oid)
        self.orders[oid] = (is_ask, px, sz)
        self._side(is_ask).add(px, sz)

    def set_size(self, oid: int, sz: float) -> None:
        self._dirty = True
        is_ask, px, old = self.orders[oid]
        self.orders[oid] = (is_ask, px, sz)
        self._side(is_ask).change(px, sz - old)

    def remove(self, oid: int) -> None:
        self._dirty = True
        entry = self.orders.pop(oid, None)
        if entry is not None:
            is_ask, px, sz = entry
            self._side(is_ask).drop(px, sz)

    def best(self) -> tuple[int | None, int | None]:
        bid = self.bids.prices[-1] if self.bids.prices else None
        ask = self.asks.prices[0] if self.asks.prices else None
        return bid, ask

    def snapshot(self, ts_ms: int) -> BookSnapshot:
        def levels(top: tuple[tuple[int, float, int], ...]) -> tuple[L2Level, ...]:
            return tuple(L2Level(px=ticks_to_px(px), sz=sz, n=n) for px, sz, n in top)

        return BookSnapshot(
            ts_ms=ts_ms,
            coin=self.coin,
            bids=levels(self.bids.top(self.depth, descending=True)),
            asks=levels(self.asks.top(self.depth, descending=False)),
        )

    def replay_hour(
        self,
        records: npt.NDArray[np.void],
        rested: Mapping[int, float],
        stats: ReplayStats | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], ReplayStats]:
        """Apply one hour of statuses; return a Silver L2 row per block whose top
        ``depth`` levels changed, plus validation counts.

        ``rested`` must hold the ``new`` diffs of this hour *and the next one*: the
        two streams cut hours on slightly different clocks.

        When ``events`` is a list, one row is appended per forced-liquidation fill
        (``kind = "liquidation"``) and per IOC whose remainder was cancelled
        (``kind = "ioc_unfilled"``). Each row records the opposite best at the
        start of the block, so an unfilled IOC whose limit crossed it
        (``marketable_at_block_start``) is a race lost inside the block: the
        quote it aimed at was cancelled or taken first. That is the fee-free
        analogue of v3's missed-race feature.

        Only records that can change the book or produce an event run through the
        Python loop; rejections, opens that never rested and statuses of orders the
        book never held are counted with NumPy. A block with none of the former
        leaves the book as it was, so it is counted without being replayed.
        """
        stats = stats or ReplayStats()
        rows: list[dict[str, Any]] = []
        n = int(records.size)
        if n == 0:
            return rows, stats
        stats.records += n
        ts = records["ts"].astype(np.int64)
        status = records["statusId"]
        tif = records["tifId"]
        oids = records["oid"]
        new_block = np.concatenate(([True], ts[1:] != ts[:-1]))
        block_ts = ts[new_block].tolist()
        block_of = np.cumsum(new_block) - 1

        is_open = status == OPEN
        deferred = is_open & (records["isTrigger"] | (tif == TIF_NULL))
        opens = is_open & ~deferred
        in_rested = np.isin(oids, np.fromiter(rested, dtype=np.uint64, count=len(rested)))
        book_oids = np.fromiter(self.orders, dtype=np.uint64, count=len(self.orders))
        held = in_rested | np.isin(oids, book_oids)
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
        code[np.isin(status, _REMOVING_IDS) & held] = _REMOVE
        wants_event = (status == IOC_CANCEL_REJECTED) | liquidation
        active = (code != 0) | wants_event if events is not None else code != 0
        idx = np.flatnonzero(active)
        kinds = code[idx].tolist()
        event_flags = wants_event[idx].tolist() if events is not None else [False] * idx.size
        sub_oid = oids[idx].tolist()
        sub_ask = records["isAsk"][idx].tolist()
        sub_px = fixed_to_ticks(records["limitPx"][idx]).tolist()
        sub_sz = decode_fixed(records["sz"][idx]).tolist()
        sub_block = block_of[idx].tolist()

        bids, asks, depth, orders = self.bids, self.asks, self.depth, self.orders
        bp, bl, ap, al = bids.prices, bids.levels, asks.prices, asks.levels
        insort, bisect_left = bisect.insort, bisect.bisect_left
        raised: list[tuple[int, int | None, bool]] = []  # (position in idx, opposite, marketable)
        dirty = self._dirty
        cur = -1
        bid0 = ask0 = None
        # The book updates below are AlbersBook.add / set_size / remove inlined
        # (about 2M calls an hour), plus the check of whether a change touched the
        # top ``depth`` levels of its side.
        for j, block in enumerate(sub_block):
            if block != cur:
                self._dirty = dirty
                if cur >= 0:
                    self._close_blocks(cur, cur + 1, block_ts, rows, stats)
                self._close_blocks(cur + 1, block, block_ts, rows, stats)  # idle blocks
                dirty = self._dirty
                cur = block
                bid0 = bp[-1] if bp else None
                ask0 = ap[0] if ap else None
            o = sub_oid[j]
            if event_flags[j]:
                ask = sub_ask[j]
                opposite = bid0 if ask else ask0
                marketable = opposite is not None and (
                    sub_px[j] <= opposite if ask else sub_px[j] >= opposite
                )
                raised.append((j, opposite, marketable))
            kind = kinds[j]
            if kind == _REMOVE or (kind == _FILL and sub_sz[j] <= 0.0):
                entry = orders.pop(o, None)
                if entry is None:
                    continue
                is_ask, px, sz = entry
                if kind == _FILL:  # a resting order filled to zero
                    stats.resting_fills += 1
                    stats.fills_at_touch += int(px == (ap[0] if is_ask else bp[-1]))
                    stats.fills_in_top_depth += int(px in (ap[:depth] if is_ask else bp[-depth:]))
                prices, levels = (ap, al) if is_ask else (bp, bl)
                if not dirty and (
                    len(prices) <= depth
                    or (px <= prices[depth - 1] if is_ask else px >= prices[-depth])
                ):
                    dirty = True
                level = levels[px]
                level[1] -= 1.0
                if level[1] <= 0.0:
                    del levels[px]
                    del prices[bisect_left(prices, px)]
                else:
                    level[0] -= sz
            elif kind == _FILL:  # partial fill: shrink in place
                entry = orders.get(o)
                if entry is None:
                    continue
                is_ask, px, old = entry
                prices, levels = (ap, al) if is_ask else (bp, bl)
                # Checked at the event, not the block start: post-only orders
                # placed earlier in the same block can be hit at a better price.
                stats.resting_fills += 1
                stats.fills_at_touch += int(px == (prices[0] if is_ask else prices[-1]))
                stats.fills_in_top_depth += int(px in (prices[:depth] if is_ask else prices[-depth:]))
                sz = sub_sz[j]
                orders[o] = (is_ask, px, sz)
                levels[px][0] += sz - old
                if not dirty and (
                    len(prices) <= depth
                    or (px <= prices[depth - 1] if is_ask else px >= prices[-depth])
                ):
                    dirty = True
            elif kind == _ADD or (kind == _TRIGGER and o not in orders):
                if kind == _TRIGGER:
                    stats.triggers_rested += 1
                elif o in orders:  # re-opened oid: replace the old entry
                    self.remove(o)
                    dirty = True
                is_ask, px, sz = sub_ask[j], sub_px[j], rested[o]
                orders[o] = (is_ask, px, sz)
                prices, levels = (ap, al) if is_ask else (bp, bl)
                existing = levels.get(px)
                if existing is None:
                    levels[px] = [sz, 1.0]
                    insort(prices, px)
                else:
                    existing[0] += sz
                    existing[1] += 1.0
                if not dirty and (
                    len(prices) <= depth
                    or (px <= prices[depth - 1] if is_ask else px >= prices[-depth])
                ):
                    dirty = True
        self._dirty = dirty
        if cur >= 0:
            self._close_blocks(cur, cur + 1, block_ts, rows, stats)
        self._close_blocks(cur + 1, len(block_ts), block_ts, rows, stats)
        if events is not None and raised:
            self._append_events(records, idx, raised, ts, events, stats)
        stats.rows += len(rows)
        stats.resting_orders_end = len(orders)
        return rows, stats

    def _close_blocks(
        self,
        first: int,
        end: int,
        block_ts: list[int],
        rows: list[dict[str, Any]],
        stats: ReplayStats,
    ) -> None:
        """End blocks ``first..end-1``, during which the book did not change after
        ``first``: the first may emit a row, the rest repeat its classification."""
        if end <= first:
            return
        count = end - first
        stats.blocks += count
        bid, ask = self.best()
        if bid is None or ask is None:
            stats.one_sided_blocks += count
            return
        if bid >= ask:
            stats.crossed_blocks += count
        if not self._dirty:
            return  # the top levels equal the last computed top, so no new row
        self._dirty = False
        top = (
            self.bids.top(self.depth, descending=True),
            self.asks.top(self.depth, descending=False),
        )
        if top == self._last_top:
            return
        self._last_top = top
        rows.append(_l2_row(self.coin, top, block_ts[first]))

    def _append_events(
        self,
        records: npt.NDArray[np.void],
        idx: npt.NDArray[np.intp],
        raised: list[tuple[int, int | None, bool]],
        ts: npt.NDArray[np.int64],
        events: list[dict[str, Any]],
        stats: ReplayStats,
    ) -> None:
        at = idx[[j for j, _, _ in raised]]
        status = records["statusId"][at].tolist()
        ts_ns = ts[at].tolist()
        oid = records["oid"][at].tolist()
        user = records["userId"][at].tolist()
        is_ask = records["isAsk"][at].tolist()
        px = fixed_to_ticks(records["limitPx"][at]).tolist()
        sz = decode_fixed(records["sz"][at]).tolist()
        orig = decode_fixed(records["origSz"][at]).tolist()
        tif = records["tifId"][at].tolist()
        for k, (_, opposite, marketable) in enumerate(raised):
            unfilled = status[k] == IOC_CANCEL_REJECTED
            if unfilled:
                stats.ioc_unfilled += 1
                stats.ioc_unfilled_marketable += int(marketable)
            events.append({
                "coin": self.coin,
                "ts_ns": ts_ns[k],
                "ts_ms": ts_ns[k] // 1_000_000,
                "kind": "ioc_unfilled" if unfilled else "liquidation",
                "oid": oid[k],
                "user_id": user[k],
                "is_ask": is_ask[k],
                "limit_px": ticks_to_px(px[k]),
                "sz": sz[k],
                "orig_sz": orig[k],
                "tif": TIF_LABELS[tif[k]] if tif[k] < len(TIF_LABELS) else str(tif[k]),
                "opposite_best_px": None if opposite is None else ticks_to_px(opposite),
                "marketable_at_block_start": marketable,
            })


def _l2_row(coin: str, top: tuple[Any, ...], ts_ns: int) -> dict[str, Any]:
    """``silver_l2_book_record`` of the book's top levels plus ``ts_ns``, without
    building a :class:`BookSnapshot` (same keys, order and arithmetic)."""
    bids, asks = top
    (bid_t, bid_sz, bid_n), (ask_t, ask_sz, ask_n) = bids[0], asks[0]
    bid_px, ask_px = ticks_to_px(bid_t), ticks_to_px(ask_t)
    mid = (bid_px + ask_px) / 2.0
    total = bid_sz + ask_sz
    if total <= 0.0:
        raise ValueError("top-of-book size is zero")
    row: dict[str, Any] = {
        "coin": coin,
        "ts_ms": ts_ns // 1_000_000,
        "bid_px": bid_px,
        "bid_sz": bid_sz,
        "bid_n": bid_n,
        "ask_px": ask_px,
        "ask_sz": ask_sz,
        "ask_n": ask_n,
        "mid": mid,
        "spread_bps": (ask_px - bid_px) / mid * BPS,
        "microprice": (bid_px * ask_sz + ask_px * bid_sz) / total,
        "top_imbalance": (bid_sz - ask_sz) / total,
    }
    for name, levels in (("bid", bids), ("ask", asks)):
        for i in range(L2_DEPTH):
            if i < len(levels):
                t, sz, cnt = levels[i]
                row[f"{name}_px_{i + 1}"] = ticks_to_px(t)
                row[f"{name}_sz_{i + 1}"] = sz
                row[f"{name}_n_{i + 1}"] = cnt
            else:
                row[f"{name}_px_{i + 1}"] = None
                row[f"{name}_sz_{i + 1}"] = None
                row[f"{name}_n_{i + 1}"] = None
    row["ts_ns"] = ts_ns
    return row


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


def match_from_albers_trade(
    trade: Mapping[str, Any],
    liquidation_oids: frozenset[int] | set[int] = frozenset(),
) -> MatchFill:
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


def albers_trades_to_matches(
    lines: Iterable[str],
    coin: str,
    liquidation_oids: frozenset[int] | set[int] = frozenset(),
) -> list[MatchFill]:
    """Matches for ``coin`` from one hourly trades member (all coins, JSON lines)."""
    symbol = coin.upper()
    needle = f'"{symbol}"'
    out: list[MatchFill] = []
    for line in lines:
        if needle not in line:
            continue
        trade = json.loads(line)
        if trade.get("coin") == symbol:
            out.append(match_from_albers_trade(trade, liquidation_oids))
    return out


def albers_trades_member_to_matches(
    data: bytes,
    coin: str,
    liquidation_oids: frozenset[int] | set[int] = frozenset(),
) -> list[MatchFill]:
    """:func:`albers_trades_to_matches` for one decompressed hourly member.

    Finds ``coin``'s lines with ``bytes.find`` instead of walking every line of
    every coin in Python, then parses only those.
    """
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
        if trade.get("coin") == symbol:
            out.append(match_from_albers_trade(trade, liquidation_oids))
        pos = data.find(needle, end)
    return out


def _opt_float(value: object) -> float | None:
    return None if value is None or value == "" else float(str(value))
