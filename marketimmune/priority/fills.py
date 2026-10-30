"""``node_fills_by_block``: parse, dedupe legs, pair maker and taker, markouts.

Each line is one block: ``{"local_time", "block_time", "block_number",
"events": [[user, fill], ...]}``. Every match appears twice, once per side;
``crossed`` is true on the taker's leg. ``priorityGas`` (when present) is the
taker's priority fee on that fill.

CLI (runs on local bronze files):

    python -m marketimmune.cli.find_first_priority_day first-priority --coin BTC \
        data/bronze/node_fills_by_block
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
    "builder_fee": pl.Float64,
    "priority_gas": pl.Float64,
}


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


def rows(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """One dict per ``[user, fill]`` event."""
    for line in lines:
        if not line.strip():
            continue
        blk = json.loads(line)
        for user, f in blk.get("events", []):
            yield {
                "block_number": blk.get("block_number"),
                "block_time": blk.get("block_time"),
                "local_time": blk.get("local_time"),
                "user": user,
                "coin": f["coin"],
                "px": float(f["px"]),
                "sz": float(f["sz"]),
                "side": f["side"],
                "time_ms": f.get("time"),
                "start_position": _f(f.get("startPosition")),
                "dir": f.get("dir"),
                "closed_pnl": _f(f.get("closedPnl")),
                "hash": f.get("hash"),
                "oid": f.get("oid"),
                "crossed": f.get("crossed"),
                "fee": _f(f.get("fee")),
                "fee_token": f.get("feeToken"),
                "tid": f.get("tid"),
                "cloid": f.get("cloid"),
                "twap_id": f.get("twapId"),
                "liquidation": f.get("liquidation") is not None,
                "builder_fee": _f(f.get("builderFee")),
                "priority_gas": _f(f.get("priorityGas")),
            }


def parse(lines: Iterable[str]) -> pl.DataFrame:
    df = pl.DataFrame(list(rows(lines)), schema=FILL_SCHEMA)
    return df.with_columns(
        pl.col("block_time").str.to_datetime(time_unit="ns", time_zone="UTC", strict=False),
        pl.col("local_time").str.to_datetime(time_unit="ns", time_zone="UTC", strict=False),
    )


def read_lz4(path: Path) -> pl.DataFrame:
    import lz4.frame

    with lz4.frame.open(path, "rt") as fh:
        return parse(fh)


def dedupe_legs(df: pl.DataFrame) -> pl.DataFrame:
    """One row per match: the taker's leg (``crossed = true``)."""
    return df.filter(pl.col("crossed")).unique(subset=["coin", "tid"], keep="first", maintain_order=True)


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
            (pl.col(t) + pl.duration(milliseconds=round(h * 1000), time_unit="ns"))
            .dt.cast_time_unit("ns")
            .alias("_t_h")
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
            (sigma * (pl.col(f"mid_{tag}") - pl.col("mid_pre")) / pl.col("mid_pre") * 1e4).alias(
                f"adv_{tag}"
            ),
        )
    return out.drop("_t_pre").sort(t)


def first_priority_day(days: Iterable[tuple[date, pl.DataFrame]], coin: str) -> date | None:
    """First day with a ``priorityGas > 0`` fill on ``coin`` (days in order)."""
    for d, df in days:
        hit = df.filter((pl.col("coin") == coin) & (pl.col("priority_gas").fill_null(0) > 0)).height
        if hit:
            return d
    return None


def _iter_local_days(root: Path) -> Iterator[tuple[date, pl.DataFrame]]:
    for day_dir in sorted(p for p in root.rglob("*") if p.is_dir() and p.name.isdigit() and len(p.name) == 8):
        files = sorted(f for f in day_dir.iterdir() if f.is_file())
        if files:
            yield datetime.strptime(day_dir.name, "%Y%m%d").date(), pl.concat([read_lz4(f) for f in files])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m marketimmune.cli.find_first_priority_day")
    sub = ap.add_subparsers(dest="cmd", required=True)
    fp = sub.add_parser("first-priority", help="first day priorityGas > 0 appears for a coin")
    fp.add_argument("root", type=Path)
    fp.add_argument("--coin", default="BTC")
    args = ap.parse_args(argv)
    if args.cmd == "first-priority":
        d = first_priority_day(_iter_local_days(args.root), args.coin)
        print(d.isoformat() if d else f"no priorityGas > 0 on {args.coin} in {args.root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
