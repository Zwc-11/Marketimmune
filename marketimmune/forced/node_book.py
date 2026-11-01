"""Forced-flow inputs from node fills and Hydromancer snapshots (forecaster v2, exploratory).

v1 (``cli.forced_forecast``) reads the Albers rebuild (Silver positions, L2 mids and order
events), so it exists only for December 2025, and gives every position the margin-free
liquidation prior. v2 reads node fills (``pull_node_fills``), so it runs on any day with fills,
and takes liquidation prices from Hydromancer snapshots (one per UTC date; Oct 8-12 and
Dec 15-31 2025), which list every open position with its exact liquidation price:

- **positions:** each leg's ``start_position`` is the wallet's exact size before it, so the book
  rolls with ``forced.positions.roll_positions``. At a snapshot the book is replaced by the
  snapshot's positions; wallets missing from it are flat.
- **liquidation price:** the snapshot's while the wallet has not traded since (NaN in the
  snapshot means none: the account cannot be liquidated through this coin alone). After it
  trades, the account is rolled (``Account``): the snapshot's account value, size and
  liquidation price fix the maintenance margin the account needs for everything else; equity
  then moves with this coin's price at each fill, and the liquidation price is re-solved for the
  new size. What the account holds in other coins is taken as constant (their profit and loss,
  margin and funding are not seen), so cross-margin prices drift between snapshots. Wallets not
  in the snapshot get the margin-free prior.
- **mid:** the trade-implied mid (``priority.fees.trade_mids``).
- **forced flow:** market liquidations, the liquidated wallet's own crossing fills
  (``liquidation_method == "market"``). Backstop liquidations hand the position to the
  liquidator off the book: they change positions but are not flow into the book.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
import polars as pl

from marketimmune.forced.margin_tiers import maintenance_terms

FloatArray = npt.NDArray[np.float64]
LEG_COLUMNS = [
    "coin",
    "block_number",
    "block_time",
    "time_ms",
    "tid",
    "oid",
    "user",
    "side",
    "px",
    "sz",
    "start_position",
    "crossed",
    "liquidated_user",
    "liquidation_mark_px",
    "liquidation_method",
]
SNAPSHOT_COLUMNS = [
    "user",
    "size",
    "notional",
    "entry_price",
    "liquidation_price",
    "leverage_type",
    "leverage",
    "account_value",
    "snapshot_block",
    "snapshot_ts_ms",
]
CROSSED = 1e-12  # a short whose account is already below maintenance: it triggers at any price


def read_legs(node_dir: Path, coin: str, date: str) -> pl.DataFrame | None:
    path = node_dir / coin / f"{coin}-{date}.parquet"
    if not path.exists():
        return None
    return pl.read_parquet(path, columns=LEG_COLUMNS)


def read_snapshot(hydro_dir: Path, coin: str, date: str) -> pd.DataFrame | None:
    path = hydro_dir / coin / f"{coin}-{date}.parquet"
    if not path.exists():
        return None
    snap = pd.read_parquet(path, columns=SNAPSHOT_COLUMNS)
    assert snap["snapshot_block"].nunique() == 1, f"{path}: more than one snapshot"
    return snap[snap["size"] != 0.0].reset_index(drop=True)


def chain_rank(start: npt.NDArray[np.int64], end: npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
    """Execution order of one wallet's fills within one block, from their sizes in units of
    1e-8: each fill starts where the previous one ended. The first is the fill whose start no
    other fill ends at; ties and cycles (a position that returns to a size it held) keep the
    file order for whatever cannot be chained."""
    n = start.size
    ends = set(end.tolist())
    heads = [i for i in range(n) if int(start[i]) not in ends]
    by_start: dict[int, list[int]] = {}
    for i in range(n):
        by_start.setdefault(int(start[i]), []).append(i)
    used = np.zeros(n, dtype=bool)
    order: list[int] = []
    cur = heads[0] if len(heads) == 1 else -1
    while cur >= 0:
        used[cur] = True
        order.append(cur)
        nxt = [i for i in by_start.get(int(end[cur]), []) if not used[i]]
        cur = nxt[0] if nxt else -1
    order += [i for i in range(n) if not used[i]]
    rank = np.empty(n, dtype=np.int64)
    rank[np.asarray(order, dtype=np.int64)] = np.arange(n)
    return rank


def execution_order(legs: pl.DataFrame) -> pl.DataFrame:
    """Legs with each wallet's fills in execution order. The node lists a block's fills by
    match, and a wallet with several orders filled in one block can appear out of order
    (its ``start_position`` chain breaks inside the block); those blocks are re-chained."""
    signed = pl.when(pl.col("side") == "B").then(pl.col("sz")).otherwise(-pl.col("sz"))
    d = legs.with_row_index("_file").with_columns(
        (pl.col("start_position") * 1e8).round().cast(pl.Int64).alias("_s"),
        ((pl.col("start_position") + signed) * 1e8).round().cast(pl.Int64).alias("_e"),
        pl.len().over("block_number", "user").alias("_n"),
    )
    multi = d.filter(pl.col("_n") > 1).sort("user", "block_number", "_file")
    rank = np.zeros(multi.height, dtype=np.int64)
    if multi.height:
        s, e = multi["_s"].to_numpy(), multi["_e"].to_numpy()
        key = multi.select(pl.struct("user", "block_number").rank("dense")).to_series().to_numpy()
        bounds = np.flatnonzero(np.r_[True, key[1:] != key[:-1], True])
        for a, b in zip(bounds[:-1], bounds[1:], strict=True):
            if not np.array_equal(s[a + 1 : b], e[a : b - 1]):  # already chained in file order
                rank[a:b] = chain_rank(s[a:b], e[a:b])
            else:
                rank[a:b] = np.arange(b - a)
    ranked = pl.concat(
        [
            d.filter(pl.col("_n") == 1).with_columns(pl.lit(0, dtype=pl.Int64).alias("_rank")),
            multi.with_columns(pl.Series("_rank", rank)),
        ]
    )
    return ranked.sort("block_number", "user", "_rank").drop("_file", "_s", "_e", "_n", "_rank")


def wallet_events(legs: pl.DataFrame) -> pd.DataFrame:
    """One row per leg, each wallet's fills in execution order (``execution_order``), for
    ``roll_positions``. ``forced`` marks a market liquidation of the leg's own wallet."""
    own = (pl.col("user") == pl.col("liquidated_user")).fill_null(False)
    out = execution_order(legs).select(
        pl.col("time_ms").alias("ts_ms"),
        pl.col("block_number"),
        pl.col("user").alias("wallet"),
        pl.col("start_position").alias("start_pos"),
        pl.when(pl.col("side") == "B").then(pl.col("sz")).otherwise(-pl.col("sz")).alias("delta"),
        pl.col("px"),
        (own & pl.col("crossed") & (pl.col("liquidation_method") == "market")).fill_null(False).alias("forced"),
    )
    return out.to_pandas()


def market_liquidations(legs: pl.DataFrame) -> tuple[FloatArray, npt.NDArray[np.bool_], FloatArray]:
    """Forced flow into the book: time, whether the liquidation order sells (it rests on the ask
    side of the order and hits bids, ``forced_forecast``'s convention), and USD notional."""
    m = legs.filter((pl.col("user") == pl.col("liquidated_user")) & pl.col("crossed") & (pl.col("liquidation_method") == "market"))
    return (
        m["time_ms"].to_numpy().astype(np.float64),
        (m["side"] == "A").to_numpy(),
        (m["px"] * m["sz"]).to_numpy().astype(np.float64),
    )


def liquidation_events(legs: pl.DataFrame) -> pl.DataFrame:
    """Every liquidated wallet's first leg per block, both methods: time, wallet, size before,
    the mark at liquidation, method, and the wallet's liquidated notional in that block."""
    own = legs.filter(pl.col("user") == pl.col("liquidated_user"))
    return (
        own.group_by("block_number", "user", maintain_order=True)
        .agg(
            pl.col("time_ms").first(),
            pl.col("start_position").first(),
            pl.col("liquidation_mark_px").first().alias("mark"),
            pl.col("liquidation_method").first().alias("method"),
            (pl.col("px") * pl.col("sz")).sum().alias("usd"),
        )
        .sort("block_number")
    )


@dataclass(slots=True)
class Account:
    """One wallet's margin account as far as this coin can see it. ``equity`` is the account
    value marked at ``mark`` with the current ``size``; ``other_mm`` is what the account needs
    for maintenance besides this coin's position, net of the equity the other positions add."""

    size: float
    equity: float
    mark: float
    other_mm: float
    isolated: bool = False
    leverage: float = 0.0


def solve_liquidation_price(coin: str, size: float, equity: float, mark: float, other_mm: float) -> float:
    """Price ``p`` where ``equity + size * (p - mark)`` equals the maintenance margin
    ``rate * |size| * p - deduction + other_mm`` (tier at the current notional): ``inf`` when there
    is none (flat, or a long that cannot reach it above zero), ``CROSSED`` for a short already
    under water."""
    if size == 0.0:
        return math.inf
    rate, deduction = maintenance_terms(coin, abs(size) * mark)
    p = (other_mm - deduction - equity + size * mark) / (size - rate * abs(size))
    if p > 0.0:
        return p
    return math.inf if size > 0 else CROSSED


def account_from_snapshot(
    coin: str, size: float, notional: float, liq: float, account_value: float, isolated: bool = False, leverage: float = 0.0
) -> Account:
    """The account at the snapshot, marked at ``notional / |size|`` and fitted so the solved
    liquidation price is the snapshot's. Cross: equity is the account value and ``other_mm``
    absorbs the rest. Isolated: the position's own margin is the equity that liquidates it at
    the snapshot's price, and ``other_mm`` is 0. With no liquidation price in the snapshot, the
    account value and ``other_mm = 0``."""
    mark = abs(notional / size)
    equity, other_mm = account_value, 0.0
    if math.isfinite(liq) and liq > 0.0:
        rate, deduction = maintenance_terms(coin, abs(size) * mark)
        needed = rate * abs(size) * liq - deduction - size * (liq - mark)  # equity at mark that liquidates at liq
        if isolated:
            equity = needed
        else:
            other_mm = account_value - needed
    return Account(size=size, equity=equity, mark=mark, other_mm=other_mm, isolated=isolated, leverage=leverage)


def roll_accounts(coin: str, events: pd.DataFrame, accounts: dict[str, Account]) -> FloatArray:
    """Each fill's liquidation price after it for wallets with an account (NaN for the rest),
    updating ``accounts``: equity gains the held size times the move since the last mark (the
    fill's ``start_pos``, the exact size), then the size changes at the fill price. An isolated
    position brings its own margin: adding posts ``|added| * px / leverage`` more, reducing
    keeps the remaining share of it."""
    out = np.full(len(events), np.nan)
    columns = (events[c].tolist() for c in ("wallet", "start_pos", "delta", "px"))
    for i, (w, s0, d, px) in enumerate(zip(*columns, strict=True)):
        a = accounts.get(w)
        if a is None:
            continue
        a.equity += s0 * (px - a.mark)
        a.mark = px
        new = s0 + d
        if a.isolated and a.leverage > 0.0:
            if abs(new) > abs(s0) or (s0 != 0.0 and (new > 0) != (s0 > 0)):  # adds, or flips
                kept = 1.0 if (s0 == 0.0 or (new > 0) == (s0 > 0)) else 0.0
                a.equity = a.equity * kept + (abs(new) - kept * abs(s0)) * px / a.leverage
            elif s0 != 0.0:
                a.equity *= abs(new) / abs(s0)
        a.size = new
        out[i] = solve_liquidation_price(coin, a.size, a.equity, a.mark, a.other_mm)
    return out
