"""Priority fees on fills in bps of notional, fee bands, and mids implied by trades.

``priorityGas`` on a taker leg is the burned fee in HYPE (wei precision, 1e-8). An order's fee is
split across its fills in proportion to size, and the fee was converted to HYPE at the spot mark
when the order filled (docs: priority fees), so the rate is ``priorityGas * HYPE_USD / notional``.
HYPE's USD price comes from the ``info`` endpoint's candles (``cli.pull_candles``): the hourly
candle around the fill where the endpoint still serves it, else the 4-hour one.

From April 2026 there is no rebuilt order book for these coins, so markouts use a mid implied by
trades: after each block, the last price a taker bought at (the ask side) and the last price a
taker sold at (the bid side), carried forward. ``cli.validate_trade_mids`` measures how close
markouts on that mid come to Gold's, which use the rebuilt book, on December 2025.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import polars as pl

from marketimmune.priority.fills import markouts, pair_legs

FEE_EDGES_BPS = (2.0, 4.0, 8.0)
BANDS = ("0", "0-2", "2-4", "4-8", "8+")
HORIZONS_S = (1.0, 10.0, 60.0)  # as Gold, where cli.validate_trade_mids checks them
TS = pl.Datetime("ns", "UTC")


def hype_usd(candles_dir: Path, coin: str = "HYPE") -> pl.DataFrame:
    """``(t, hype_usd)``: each candle's open time and its (open + close) / 2, hourly where the
    hourly file covers, 4-hourly before that."""
    frames = []
    first_hourly = None
    for interval in ("1h", "4h"):
        path = candles_dir / f"{coin}-{interval}.parquet"
        if not path.exists():
            continue
        c = pl.read_parquet(path)
        if interval == "1h":
            first_hourly = c["t"].min()
        elif first_hourly is not None:
            c = c.filter(pl.col("t") < first_hourly)
        frames.append(c.select(pl.from_epoch("t", time_unit="ms").cast(TS).alias("t"), ((pl.col("o") + pl.col("c")) / 2).alias("hype_usd")))
    assert frames, f"no {coin} candles in {candles_dir}; run marketimmune.cli.pull_candles"
    return pl.concat(frames).sort("t")


def fee_band(fee_bps: pl.Expr) -> pl.Expr:
    lo, mid, hi = FEE_EDGES_BPS
    return (
        pl.when(fee_bps <= 0)
        .then(pl.lit("0"))
        .when(fee_bps <= lo)
        .then(pl.lit("0-2"))
        .when(fee_bps <= mid)
        .then(pl.lit("2-4"))
        .when(fee_bps <= hi)
        .then(pl.lit("4-8"))
        .otherwise(pl.lit("8+"))
    )


def with_fee_bps(pairs: pl.DataFrame, hype: pl.DataFrame) -> pl.DataFrame:
    """Add ``hype_usd``, ``notional``, ``fee_bps`` (0 without a fee) and ``band`` to paired fills."""
    out = (
        pairs.with_columns(pl.col("block_time").cast(TS))
        .sort("block_time")
        .join_asof(hype, left_on="block_time", right_on="t", strategy="backward", check_sortedness=False)
        .drop("t")
    )
    notional = pl.col("px") * pl.col("sz")
    fee = pl.col("priority_gas").fill_null(0.0) * pl.col("hype_usd") / notional * 1e4
    return out.with_columns(notional=notional, fee_bps=fee).with_columns(band=fee_band(pl.col("fee_bps")))


def trade_mids(legs: pl.DataFrame) -> pl.DataFrame:
    """``(coin, t, mid)`` after each block with a trade: the mean of the last taker-buy price and
    the last taker-sell price so far; while they cross (one side stale), the block's last price."""
    takers = legs.filter(pl.col("crossed")).sort("block_number", "tid")
    per_block = takers.group_by("coin", "block_number", maintain_order=True).agg(
        pl.col("block_time").first().cast(TS).alias("t"),
        pl.col("px").filter(pl.col("side") == "B").last().alias("ask"),
        pl.col("px").filter(pl.col("side") == "A").last().alias("bid"),
        pl.col("px").last().alias("last"),
    )
    filled = per_block.with_columns(pl.col("ask", "bid").forward_fill().over("coin"))
    mid = pl.when(pl.col("bid") <= pl.col("ask")).then((pl.col("bid") + pl.col("ask")) / 2).otherwise(pl.col("last"))
    return filled.select("coin", "t", mid.alias("mid")).sort("t")


def fill_markouts(legs: pl.DataFrame, hype: pl.DataFrame | None, horizons_s: Iterable[float] = HORIZONS_S) -> pl.DataFrame:
    """One row per trade with its taker's fee (when ``hype`` is given) and the maker's markouts
    (``hs_bps``, ``mo_<h>s``, ``adv_<h>s``) on the trade-implied mid."""
    pairs = pair_legs(legs)
    if hype is not None:
        pairs = with_fee_bps(pairs, hype)
    return markouts(pairs.with_columns(pl.col("block_time").cast(TS)), trade_mids(legs), horizons_s)


def band_stats(trades: pl.DataFrame, horizons_s: Iterable[float] = HORIZONS_S) -> pl.DataFrame:
    """Per fee band: fills, notional, and sums of the half-spread and of each horizon's markout
    and adverse move, plain and notional-weighted (sums, so days add up)."""
    cols = ["hs_bps", *(f"{k}_{h:g}s" for h in horizons_s for k in ("mo", "adv"))]
    ok = trades.filter(pl.all_horizontal(pl.col(c).is_not_null() for c in cols))
    return (
        ok.group_by("band")
        .agg(
            pl.len().alias("fills"),
            pl.col("notional").sum(),
            pl.col("fee_bps").sum().alias("fee_bps_sum"),
            *(pl.col(c).sum().alias(f"{c}_sum") for c in cols),
            *((pl.col(c) * pl.col("notional")).sum().alias(f"{c}_nsum") for c in cols),
        )
        .sort("band")
    )
