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
``scripts/build_albers_silver_l2.py``.
"""

from __future__ import annotations

import bisect
import calendar
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.ingest.hyperliquid_archive import BookSnapshot, L2Level
from marketimmune.ingest.hyperliquid_fills import MatchFill
from marketimmune.ingest.hyperliquid_lake import L2_DEPTH, silver_l2_book_record

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

    def _side(self, is_ask: bool) -> _Side:
        return self.asks if is_ask else self.bids

    def add(self, oid: int, is_ask: bool, px: int, sz: float) -> None:
        if oid in self.orders:
            self.remove(oid)
        self.orders[oid] = (is_ask, px, sz)
        self._side(is_ask).add(px, sz)

    def set_size(self, oid: int, sz: float) -> None:
        is_ask, px, old = self.orders[oid]
        self.orders[oid] = (is_ask, px, sz)
        self._side(is_ask).change(px, sz - old)

    def remove(self, oid: int) -> None:
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
        """
        stats = stats or ReplayStats()
        rows: list[dict[str, Any]] = []
        if records.size == 0:
            return rows, stats
        ts = records["ts"].astype(np.int64)
        cuts = np.flatnonzero(np.diff(ts)) + 1
        starts = np.concatenate(([0], cuts)).tolist()
        ends = np.concatenate((cuts, [ts.size])).tolist()
        status = records["statusId"].tolist()
        oid = records["oid"].tolist()
        is_ask = records["isAsk"].tolist()
        px = fixed_to_ticks(records["limitPx"]).tolist()
        sz = decode_fixed(records["sz"]).tolist()
        tif = records["tifId"].tolist()
        is_trigger = records["isTrigger"].tolist()
        ts_list = ts.tolist()
        user = records["userId"].tolist()
        orig = decode_fixed(records["origSz"]).tolist()
        stats.records += int(ts.size)
        for start, end in zip(starts, ends, strict=True):
            bid0, ask0 = self.best()
            for i in range(start, end):
                k = status[i]
                o = oid[i]
                if events is not None and (
                    k == IOC_CANCEL_REJECTED or (k == FILLED and tif[i] == LIQUIDATION_MARKET)
                ):
                    opposite = bid0 if is_ask[i] else ask0
                    marketable = opposite is not None and (
                        px[i] <= opposite if is_ask[i] else px[i] >= opposite
                    )
                    if k == IOC_CANCEL_REJECTED:
                        stats.ioc_unfilled += 1
                        stats.ioc_unfilled_marketable += int(marketable)
                    events.append({
                        "coin": self.coin,
                        "ts_ns": ts_list[i],
                        "ts_ms": ts_list[i] // 1_000_000,
                        "kind": "ioc_unfilled" if k == IOC_CANCEL_REJECTED else "liquidation",
                        "oid": o,
                        "user_id": user[i],
                        "is_ask": is_ask[i],
                        "limit_px": ticks_to_px(px[i]),
                        "sz": sz[i],
                        "orig_sz": orig[i],
                        "tif": TIF_LABELS[tif[i]] if tif[i] < len(TIF_LABELS) else str(tif[i]),
                        "opposite_best_px": None if opposite is None else ticks_to_px(opposite),
                        "marketable_at_block_start": marketable,
                    })
                if k == OPEN:
                    # A stop / take-profit logs ``open`` while it waits off-book; it
                    # can only rest once ``triggered``.
                    if is_trigger[i] or tif[i] == TIF_NULL:
                        stats.trigger_opens_deferred += 1
                        continue
                    rest = rested.get(o)
                    if rest is None:
                        stats.opens_not_resting += 1
                    else:
                        self.add(o, is_ask[i], px[i], rest)
                        stats.opens_rested += 1
                elif k == TRIGGERED:
                    rest = rested.get(o)
                    if rest is not None and o not in self.orders:
                        self.add(o, is_ask[i], px[i], rest)
                        stats.triggers_rested += 1
                elif k == FILLED:
                    if tif[i] == LIQUIDATION_MARKET:
                        stats.liquidation_fills += 1
                    entry = self.orders.get(o)
                    if entry is None:
                        continue
                    # Checked at the event, not the block start: post-only orders
                    # placed earlier in the same block can be hit at a better price.
                    stats.resting_fills += 1
                    side = self.asks if entry[0] else self.bids
                    touch = side.prices[0] if entry[0] else side.prices[-1]
                    near = side.prices[: self.depth] if entry[0] else side.prices[-self.depth :]
                    stats.fills_at_touch += int(entry[1] == touch)
                    stats.fills_in_top_depth += int(entry[1] in near)
                    if sz[i] > 0.0:
                        self.set_size(o, sz[i])
                    else:
                        self.remove(o)
                elif k in REMOVING:
                    self.remove(o)
            stats.blocks += 1
            bid, ask = self.best()
            if bid is None or ask is None:
                stats.one_sided_blocks += 1
                continue
            if bid >= ask:
                stats.crossed_blocks += 1
            top = (
                self.bids.top(self.depth, descending=True),
                self.asks.top(self.depth, descending=False),
            )
            if top == self._last_top:
                continue
            self._last_top = top
            ts_ns = ts_list[start]
            row = silver_l2_book_record(self.snapshot(ts_ns // 1_000_000))
            row["ts_ns"] = ts_ns
            rows.append(row)
        stats.rows += len(rows)
        stats.resting_orders_end = len(self.orders)
        return rows, stats


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


def _opt_float(value: object) -> float | None:
    return None if value is None or value == "" else float(str(value))
