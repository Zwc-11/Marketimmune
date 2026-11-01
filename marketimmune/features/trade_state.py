"""Features from trades alone: market state, fee pressure (plan A.3) and realised forced flow.

For coins and dates with no order book (2026: no L4 archive), the state rung is built from the
tape. Everything for a fill in block ``b`` reads blocks strictly before ``b`` only.

* **Trade state** (``TRADE_STATE_COLUMNS``), over time windows ``[t_b - w, t_b)``:
  - the spread of the trade-implied quotes (last taker-buy price minus last taker-sell price);
  - taker flow imbalance toward the maker;
  - log taker notional and trade count;
  - realised volatility of the trade-implied mid;
  - time since the last trade.
* **Fee pressure** (``FEE_COLUMNS``, plan A.3), over blocks ``b - k`` to ``b - 1``, on the side
  that hits the maker (sellers for a maker on the bid):
  - FP, the notional-weighted mean fee;
  - FC, the count of fee-paying takers;
  - FM, the largest fee;
  - the priced-taker share;
  - FP same side minus FP opposite.

  ``FEE_PLACEBO_COLUMNS`` are the same four for the *opposite* side.
* **Realised forced flow** over 60 s, same and opposite side (the regime columns
  ``compare_rungs`` reads).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt
import polars as pl

from marketimmune.priority.fills import execution_order

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]

TIME_WINDOWS_MS = (1_000, 5_000, 10_000)
COUNT_WINDOWS_MS = (1_000, 10_000)
VOL_WINDOWS_MS = (10_000, 60_000)
FEE_WINDOWS_BLOCKS = (3, 10, 30)
FORCED_WINDOW_MS = 60_000

TRADE_STATE_COLUMNS = (
    "tm_spread_bps",
    *(f"flow_maker_{w}ms" for w in TIME_WINDOWS_MS),
    *(f"log_taker_usd_{w}ms" for w in TIME_WINDOWS_MS),
    *(f"log_trades_{w}ms" for w in COUNT_WINDOWS_MS),
    *(f"tm_vol_{w}ms_bps" for w in VOL_WINDOWS_MS),
    "log_ms_since_trade",
)
_FEE_STATS = ("fp", "fc", "fm", "share")
FEE_COLUMNS = (*(f"{s}_same_{k}b" for k in FEE_WINDOWS_BLOCKS for s in _FEE_STATS), *(f"fp_imb_{k}b" for k in FEE_WINDOWS_BLOCKS))
FEE_PLACEBO_COLUMNS = tuple(f"{s}_opp_{k}b" for k in FEE_WINDOWS_BLOCKS for s in _FEE_STATS)
FORCED_COLUMNS = (f"forced_same_notional_{FORCED_WINDOW_MS}ms", f"forced_opp_notional_{FORCED_WINDOW_MS}ms")
SIDES = ("bid", "ask")  # the resting side a taker hits: sellers hit bids, buyers hit asks


def block_table(trades: pl.DataFrame) -> pl.DataFrame:
    """One row per block with a trade, in block order. ``trades``: one row per match with
    ``block_number``, ``taker_oid``, ``t_ms`` (block time, ms, float), ``px``, ``notional``,
    ``taker_side`` ("B" buys, "A" sells), ``fee_bps`` (0 without a fee) and ``liquidation``.
    "Last" prices are in execution order (``priority.fills.execution_order``).

    Per side hit (``bid``: by sellers; ``ask``: by buyers): notional, fee-weighted notional,
    fee-paying count and notional, largest fee, and forced notional."""
    hit = pl.when(pl.col("taker_side") == "A").then(pl.lit("bid")).otherwise(pl.lit("ask"))
    t = trades.sort(execution_order("taker_oid", "taker_side")).with_columns(hit.alias("hit"))
    aggs = [
        pl.col("t_ms").first(),
        pl.len().alias("n"),
        pl.col("px").filter(pl.col("taker_side") == "B").last().alias("ask_px"),
        pl.col("px").filter(pl.col("taker_side") == "A").last().alias("bid_px"),
        pl.col("px").last().alias("last_px"),
    ]
    for side in SIDES:
        on = pl.col("hit") == side
        aggs += [
            pl.col("notional").filter(on).sum().alias(f"usd_{side}"),
            (pl.col("notional") * pl.col("fee_bps")).filter(on).sum().alias(f"fee_usd_{side}"),
            (pl.col("fee_bps") > 0).filter(on).sum().cast(pl.Float64).alias(f"n_fee_{side}"),
            pl.col("notional").filter(on & (pl.col("fee_bps") > 0)).sum().alias(f"priced_usd_{side}"),
            pl.col("fee_bps").filter(on).max().fill_null(0.0).alias(f"max_fee_{side}"),
            pl.col("notional").filter(on & pl.col("liquidation")).sum().alias(f"forced_usd_{side}"),
        ]
    b = t.group_by("block_number", maintain_order=True).agg(aggs)
    b = b.with_columns(pl.col("ask_px", "bid_px").forward_fill())
    mid = pl.when(pl.col("bid_px") <= pl.col("ask_px")).then((pl.col("bid_px") + pl.col("ask_px")) / 2).otherwise(pl.col("last_px"))
    spread = pl.when(pl.col("bid_px") <= pl.col("ask_px")).then(pl.col("ask_px") - pl.col("bid_px")).otherwise(0.0)
    return b.with_columns(mid.alias("mid"), spread.alias("spread"))


def _prefix(x: FloatArray) -> FloatArray:
    return np.concatenate(([0.0], np.cumsum(x)))


def _col(blocks: pl.DataFrame, name: str) -> FloatArray:
    return blocks[name].to_numpy().astype(np.float64)


def trade_features(
    fill_block: npt.ArrayLike, fill_t_ms: npt.ArrayLike, maker_side: npt.ArrayLike, blocks: pl.DataFrame
) -> dict[str, FloatArray]:
    """Trade state, fee pressure and forced flow for fills in blocks ``fill_block`` at block times
    ``fill_t_ms`` (ms) on ``maker_side`` (+1 the maker bought), from ``block_table`` rows."""
    fb = np.asarray(fill_block, dtype=np.int64)
    ft = np.asarray(fill_t_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    bn = blocks["block_number"].to_numpy().astype(np.int64)
    bt = _col(blocks, "t_ms")
    hi = np.searchsorted(bn, fb, side="left")  # blocks strictly before the fill's block
    prev = hi - 1
    ok = prev >= 0
    out: dict[str, FloatArray] = {}

    mid, spread = _col(blocks, "mid"), _col(blocks, "spread")
    last_mid = np.where(ok, mid[np.maximum(prev, 0)], np.nan)
    out["tm_spread_bps"] = np.where(ok, spread[np.maximum(prev, 0)], np.nan) / last_mid * 1e4

    buy, sell = _col(blocks, "usd_ask"), _col(blocks, "usd_bid")
    p_buy, p_sell, p_n = _prefix(buy), _prefix(sell), _prefix(_col(blocks, "n"))
    for w in TIME_WINDOWS_MS:
        lo = np.minimum(np.searchsorted(bt, ft - w, side="left"), hi)
        b_, s_ = p_buy[hi] - p_buy[lo], p_sell[hi] - p_sell[lo]
        tot = b_ + s_
        out[f"flow_maker_{w}ms"] = side * np.divide(b_ - s_, tot, out=np.zeros_like(tot), where=tot > 0)
        out[f"log_taker_usd_{w}ms"] = np.log1p(tot)
        if w in COUNT_WINDOWS_MS:
            out[f"log_trades_{w}ms"] = np.log1p(p_n[hi] - p_n[lo])
    r2 = np.zeros(mid.size)
    r2[1:] = np.log(mid[1:] / mid[:-1]) ** 2
    p_r2 = _prefix(np.nan_to_num(r2))
    for w in VOL_WINDOWS_MS:
        lo = np.minimum(np.searchsorted(bt, ft - w, side="left"), hi)
        lo1 = np.minimum(lo + 1, hi)  # a return needs its starting block inside the window
        out[f"tm_vol_{w}ms_bps"] = np.sqrt(p_r2[hi] - p_r2[lo1]) * 1e4
    out["log_ms_since_trade"] = np.where(ok, np.log1p(ft - bt[np.maximum(prev, 0)]), np.nan)

    same_is_bid = side > 0  # a maker on the bid is hit by sellers
    stats = {s: {k: _col(blocks, f"{k}_{s}") for k in ("usd", "fee_usd", "n_fee", "priced_usd", "max_fee")} for s in SIDES}
    prefixes = {s: {k: _prefix(v) for k, v in d.items() if k != "max_fee"} for s, d in stats.items()}
    for k in FEE_WINDOWS_BLOCKS:
        lo = np.searchsorted(bn, fb - k, side="left")
        per_side: dict[str, dict[str, FloatArray]] = {}
        for s in SIDES:
            p = prefixes[s]
            usd = p["usd"][hi] - p["usd"][lo]
            fee = p["fee_usd"][hi] - p["fee_usd"][lo]
            priced = p["priced_usd"][hi] - p["priced_usd"][lo]
            fm: npt.NDArray[np.float64] = np.zeros(fb.size)
            mx = stats[s]["max_fee"]
            for j in range(1, k + 1):  # at most k blocks in the window
                idx = hi - j
                inside = idx >= lo
                fm = np.where(inside, np.maximum(fm, mx[np.maximum(idx, 0)]), fm)
            per_side[s] = {
                "fp": np.divide(fee, usd, out=np.zeros_like(usd), where=usd > 0),
                "fc": p["n_fee"][hi] - p["n_fee"][lo],
                "fm": fm,
                "share": np.divide(priced, usd, out=np.zeros_like(usd), where=usd > 0),
            }
        for stat in _FEE_STATS:
            out[f"{stat}_same_{k}b"] = np.where(same_is_bid, per_side["bid"][stat], per_side["ask"][stat])
            out[f"{stat}_opp_{k}b"] = np.where(same_is_bid, per_side["ask"][stat], per_side["bid"][stat])
        out[f"fp_imb_{k}b"] = out[f"fp_same_{k}b"] - out[f"fp_opp_{k}b"]

    f_bid, f_ask = _prefix(_col(blocks, "forced_usd_bid")), _prefix(_col(blocks, "forced_usd_ask"))
    lo = np.minimum(np.searchsorted(bt, ft - FORCED_WINDOW_MS, side="left"), hi)
    fbid, fask = f_bid[hi] - f_bid[lo], f_ask[hi] - f_ask[lo]
    out[FORCED_COLUMNS[0]] = np.where(same_is_bid, fbid, fask)
    out[FORCED_COLUMNS[1]] = np.where(same_is_bid, fask, fbid)
    return out


def verify_trade_features_no_lookahead(
    fill_block: npt.ArrayLike,
    fill_t_ms: npt.ArrayLike,
    maker_side: npt.ArrayLike,
    trades: pl.DataFrame,
    columns: Sequence[str],
    *,
    sample: int = 200,
    rebuild: int = 20,
    seed: int = 0,
) -> dict[str, object]:
    """Recompute sampled fills' features with every block at or after the fill's own removed;
    any difference means a feature read that block or a later one.

    For ``sample`` fills the block table is cut; for the first ``rebuild`` of them it is also
    rebuilt from the earlier blocks' trades, which checks ``block_table`` itself (slower)."""
    fb = np.asarray(fill_block, dtype=np.int64)
    ft = np.asarray(fill_t_ms, dtype=np.float64)
    side = np.asarray(maker_side, dtype=np.float64)
    ordered = trades.sort(execution_order("taker_oid", "taker_side"))
    blocks = block_table(ordered)
    full = trade_features(fb, ft, side, blocks)
    rng = np.random.default_rng(seed)
    picks = np.sort(rng.choice(fb.size, size=min(sample, fb.size), replace=False)) if fb.size else np.zeros(0, dtype=np.int64)
    bn = blocks["block_number"].to_numpy()
    tn = ordered["block_number"].to_numpy()
    mismatched, worst, checked = 0, 0.0, 0
    for n, i in enumerate(picks.tolist()):
        cut_blocks = blocks.head(int(np.searchsorted(bn, fb[i], side="left")))
        if cut_blocks.is_empty():
            continue
        tables = [cut_blocks]
        if n < rebuild:
            tables.append(block_table(ordered.head(int(np.searchsorted(tn, fb[i], side="left")))))
        for table in tables:
            cut = trade_features(fb[i : i + 1], ft[i : i + 1], side[i : i + 1], table)
            diffs = [_diff(full[c][i], cut[c][0]) for c in columns]
            worst = max(worst, *diffs)
            mismatched += int(max(diffs) > 1e-9)
            checked += 1
    return {"passed": checked > 0 and mismatched == 0, "n_checked": checked, "n_mismatched": mismatched, "max_abs_diff": worst}


def _diff(a: float, b: float) -> float:
    if np.isnan(a) and np.isnan(b):
        return 0.0
    if np.isnan(a) or np.isnan(b):
        return float("inf")
    return float(abs(a - b) / max(1.0, abs(b)))
