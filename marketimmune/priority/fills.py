"""``node_fills_by_block`` as polars frames for the priority-fee study: parse, pair legs, markouts.

Each line is one block: ``{"local_time", "block_time", "block_number", "events": [[user,
fill], ...]}``. Every match appears twice, once per side; ``crossed`` is true on the taker's
leg. ``priorityGas`` (when present) is the taker's priority fee on that fill. A forced fill
carries ``liquidation = {"liquidatedUser", "markPx", "method"}``; ``method`` is ``"market"``
(sent to the book) or ``"backstop"`` (taken over by the liquidator vault).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Iterator, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import lz4.frame
import polars as pl

FILL_SCHEMA: dict[str, Any] = {
    "block_number": pl.UInt64,
    "block_time": pl.String,
    "local_time": pl.String,
    "user": pl.String,
    "coin": pl.String,
    "px": pl.Float64,
    "sz": pl.Float64,
    "side": pl.String,
    "time_ms": pl.Int64,
    "start_position": pl.Float64,
    "dir": pl.String,
    "closed_pnl": pl.Float64,
    "hash": pl.String,
    "oid": pl.UInt64,
    "crossed": pl.Boolean,
    "fee": pl.Float64,
    "fee_token": pl.String,
    "tid": pl.UInt64,
    "cloid": pl.String,
    "twap_id": pl.Int64,
    "liquidation": pl.Boolean,
    "liquidated_user": pl.String,
    "liquidation_mark_px": pl.Float64,
    "liquidation_method": pl.String,
    "builder_fee": pl.Float64,
    "priority_gas": pl.Float64,
}


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def rows(lines: Iterable[str], coins: Collection[str] | None = None) -> Iterator[dict[str, Any]]:
    """One dict per ``[user, fill]`` event (only ``coins``' when given: a block holds every coin's
    fills, and a dict per leg is what costs memory)."""
    for line in lines:
        blk = json.loads(line)
        for user, f in blk["events"]:
            if coins is not None and f["coin"] not in coins:
                continue
            liq = f.get("liquidation") or {}
            yield {
                "block_number": blk["block_number"],
                "block_time": blk["block_time"],
                "local_time": blk["local_time"],
                "user": user,
                "coin": f["coin"],
                "px": float(f["px"]),
                "sz": float(f["sz"]),
                "side": f["side"],
                "time_ms": f["time"],
                "start_position": float(f["startPosition"]),
                "dir": f["dir"],
                "closed_pnl": float(f["closedPnl"]),
                "hash": f["hash"],
                "oid": f["oid"],
                "crossed": f["crossed"],
                "fee": float(f["fee"]),
                "fee_token": f["feeToken"],
                "tid": f["tid"],
                "cloid": f.get("cloid"),
                "twap_id": f.get("twapId"),
                "liquidation": f.get("liquidation") is not None,
                "liquidated_user": liq.get("liquidatedUser"),
                "liquidation_mark_px": _f(liq.get("markPx")),
                "liquidation_method": liq.get("method"),
                "builder_fee": _f(f.get("builderFee")),
                "priority_gas": _f(f.get("priorityGas")),
            }


def parse(lines: Iterable[str]) -> pl.DataFrame:
    return to_frame(list(rows(lines)))


def to_frame(records: Sequence[dict[str, Any]]) -> pl.DataFrame:
    """``rows`` output as a typed frame (times parsed to UTC nanoseconds)."""
    df = pl.DataFrame(records, schema=FILL_SCHEMA)
    return df.with_columns(
        pl.col("block_time").str.to_datetime(time_unit="ns", time_zone="UTC"),
        pl.col("local_time").str.to_datetime(time_unit="ns", time_zone="UTC"),
    )


def read_lz4(path: Path, contains: str = "") -> pl.DataFrame:
    """One hourly file; ``contains`` keeps only the block lines holding that text, a cheap pre-filter before JSON."""
    with lz4.frame.open(path, "rt") as fh:
        return parse(line for line in fh if contains in line)


def execution_order(oid: str = "oid", side: str = "side") -> list[pl.Expr]:
    """Sort keys that put a block's taker fills in execution order: by taker order id (orders
    are numbered as they execute), then along each order's sweep (buys up the book, sells down).
    The node lists a block's fills in neither order, and trade ids are not sequential. Checked
    on SOL 2025-12-01: re-chaining each wallet's fills on ``start_position`` gives non-decreasing
    taker oids in 98.8% of wallet-blocks with several taker orders, and the sweep order in
    99.97% of multi-fill buy orders and 99.99% of sells; the file order gives the sweep in ~70%."""
    sweep = pl.when(pl.col(side) == "B").then(pl.col("px")).otherwise(-pl.col("px"))
    return [pl.col("block_number"), pl.col(oid), sweep]


def pair_legs(df: pl.DataFrame) -> pl.DataFrame:
    """Join each match's taker and maker legs on (coin, tid)."""
    taker = df.filter(pl.col("crossed")).select(
        "coin",
        "tid",
        "block_number",
        "block_time",
        "time_ms",
        "px",
        "sz",
        pl.col("side").alias("taker_side"),
        pl.col("user").alias("taker"),
        pl.col("oid").alias("taker_oid"),
        pl.col("fee").alias("taker_fee"),
        "priority_gas",
        "liquidation",
        "twap_id",
    )
    maker = df.filter(~pl.col("crossed")).select(
        "coin",
        "tid",
        pl.col("user").alias("maker"),
        pl.col("oid").alias("maker_oid"),
        pl.col("fee").alias("maker_fee"),
    )
    out = taker.join(maker, on=["coin", "tid"], how="inner")
    # Maker side sigma: +1 if the maker bought (the taker sold, side "A").
    # priority_gas stays raw: whether it is the rate p (p/1e8 of notional, as in
    # an order's grouping.p) or the amount burned is a G0 probe question.
    return out.with_columns(
        maker_sigma=pl.when(pl.col("taker_side") == "A").then(1).otherwise(-1).cast(pl.Int8),
    )


def markouts(pairs: pl.DataFrame, mids: pl.DataFrame, horizons_s: Iterable[float]) -> pl.DataFrame:
    """Maker markout M(h) in bps for each fill (Lesson 1.3).

    ``mids`` has columns ``coin``, ``t`` (datetime ns) and ``mid``. The pre-fill
    mid is the last mid strictly before the block time; ``m_{t+h}`` is the last
    mid at or before ``t + h``. Columns added per horizon: ``mo_<h>s`` (total),
    ``hs_bps`` (half-spread earned) and ``adv_<h>s`` (adverse move).
    """
    t = "block_time"
    base = pairs.with_columns(pl.col(t).dt.cast_time_unit("ns")).sort(t)
    m = mids.with_columns(pl.col("t").dt.cast_time_unit("ns")).sort("t")
    pre = base.join_asof(
        m.rename({"t": "_t_pre", "mid": "mid_pre"}),
        left_on=t,
        right_on="_t_pre",
        by="coin",
        strategy="backward",
        allow_exact_matches=False,
        check_sortedness=False,  # sorted by time globally, hence within each coin
    )
    sigma = pl.col("maker_sigma").cast(pl.Float64)
    out = pre.with_columns(hs_bps=sigma * (pl.col("mid_pre") - pl.col("px")) / pl.col("mid_pre") * 1e4)
    for h in horizons_s:
        tag = f"{h:g}s"
        shifted = out.with_columns(
            (pl.col(t) + pl.duration(milliseconds=round(h * 1000), time_unit="ns")).dt.cast_time_unit("ns").alias("_t_h")
        )
        shifted = shifted.sort("_t_h").join_asof(
            m.rename({"t": "_t_m", "mid": f"mid_{tag}"}),
            left_on="_t_h",
            right_on="_t_m",
            by="coin",
            strategy="backward",
            check_sortedness=False,
        )
        out = shifted.drop("_t_h", "_t_m").with_columns(
            (sigma * (pl.col(f"mid_{tag}") - pl.col("px")) / pl.col("mid_pre") * 1e4).alias(f"mo_{tag}"),
            (sigma * (pl.col(f"mid_{tag}") - pl.col("mid_pre")) / pl.col("mid_pre") * 1e4).alias(f"adv_{tag}"),
        )
    return out.drop("_t_pre").sort(t)


def first_priority_day(days: Iterable[tuple[date, pl.DataFrame]], coin: str) -> date | None:
    """First day with a ``priorityGas > 0`` fill on ``coin`` (days in order)."""
    for d, df in days:
        hit = df.filter((pl.col("coin") == coin) & (pl.col("priority_gas").fill_null(0) > 0)).height
        if hit:
            return d
    return None


def local_days(root: Path, contains: str = "") -> Iterator[tuple[date, pl.DataFrame]]:
    """``(day, fills)`` for every ``YYYYMMDD`` directory under ``root``, in date order."""
    for day_dir in sorted(p for p in root.rglob("*") if p.is_dir() and p.name.isdigit() and len(p.name) == 8):
        files = sorted(f for f in day_dir.iterdir() if f.is_file())
        if files:
            yield datetime.strptime(day_dir.name, "%Y%m%d").date(), pl.concat([read_lz4(f, contains) for f in files])
