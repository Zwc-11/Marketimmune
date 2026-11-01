"""Gold training rows from node fills alone, for dates with no order book (the 2026 A1 ladder).

    python -m marketimmune.cli.build_node_gold --coin SOL --dates 20260425..20261031
    python -m marketimmune.cli.build_node_gold --coin SOL --dates 20260425..20261031 --stage wallet

Pre-registration: ``docs/preregistration/a1-speed-bids-2026.md``.

**Stage ``day``** (the default) writes one Gold partition per date, one row per match, from the
maker's side:

- **Mid:** the trade-implied mid (``priority.fees``), also stored as ``l2_mid`` /
  ``l2_microprice`` so the trainers can read the rows.
- **Labels:** the maker's markout at 1, 10 and 60 s from the last mid strictly before the fill's
  block (``markout_bps_<h>``) and from the fill price (``markout_px_bps_<h>``);
  ``toxic_<h> = markout < -1 bp``. A label whose pre-fill or horizon mid is more than 30 s old is
  dropped, as in Gold.
- **Features:**
  - the trade state, fee pressure and forced flow (``features.trade_state``);
  - the CEX gap columns on the trade-implied mid (Binance read 300 ms late).
- **Fill's own fee:** stored as ``taker_fee_prio_bps`` for analysis. It is not a feature: a maker
  cannot see it before the fill.

The previous date's last 10 minutes and the next date's first 2 minutes are read for the windows
and the 60 s label. A date with no Binance file is skipped and reported. Each partition gets a
``.leakage.json``: sampled fills recomputed from earlier blocks only, and the CEX columns with
later trades and mids deleted.

**Stage ``wallet``** adds the taker-wallet scores over every written date at once, since a
wallet's history crosses dates, and checks them by brute force.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pyarrow.parquet as pq
from numpy.typing import NDArray

from marketimmune.features.cex_gap import DEFAULT_LATENCY_MS, cex_gap_features, verify_cex_gap_no_lookahead
from marketimmune.features.trade_state import (
    FEE_COLUMNS,
    FEE_PLACEBO_COLUMNS,
    FORCED_COLUMNS,
    TRADE_STATE_COLUMNS,
    block_table,
    trade_features,
    verify_trade_features_no_lookahead,
)
from marketimmune.features.wallet_toxicity import DEFAULT_PRIOR_WEIGHT, verify_wallet_scores_no_lookahead, wallet_toxicity_from_codes
from marketimmune.lake.tables import HyperliquidLakeLayout, leakage_report_path
from marketimmune.logger import init_logger
from marketimmune.priority.fees import hype_usd, with_fee_bps
from marketimmune.priority.fills import execution_order, pair_legs
from marketimmune.sim.data import binance_days
from marketimmune.utils import DAY_MS, day_start_ms, parse_date_spec, shift_date

logger = init_logger(__name__)

HORIZONS_S = (1.0, 10.0, 60.0)
TOXIC_BPS = 1.0
MAX_MID_LAG_MS = 30_000.0
PREV_TAIL_MS = 10 * 60_000
NEXT_HEAD_MS = 2 * 60_000
WALLET_HORIZONS = ("1s", "10s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20260425..20261031")
    parser.add_argument("--stage", choices=["day", "wallet"], default="day")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--candles-dir", type=Path, default=Path("data/bronze/hyperliquid/candles"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--cex-latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    parser.add_argument("--skip-existing", action="store_true", help="day stage: leave dates already written")
    return parser.parse_args(argv)


def _legs(node_dir: Path, coin: str, date: str) -> pl.DataFrame | None:
    path = node_dir / coin / f"{coin}-{date}.parquet"
    return pl.read_parquet(path) if path.exists() else None


def load_legs(node_dir: Path, coin: str, date: str) -> pl.DataFrame:
    """The date's legs with the previous date's last minutes and the next date's first."""
    start = day_start_ms(date)
    day = _legs(node_dir, coin, date)
    assert day is not None, f"no node fills for {coin} {date}"
    parts = [day]
    prev, nxt = _legs(node_dir, coin, shift_date(date, -1)), _legs(node_dir, coin, shift_date(date, 1))
    if prev is not None:
        parts.insert(0, prev.filter(pl.col("time_ms") >= start - PREV_TAIL_MS))
    if nxt is not None:
        parts.append(nxt.filter(pl.col("time_ms") < start + DAY_MS + NEXT_HEAD_MS))
    return pl.concat(parts)


def match_rows(legs: pl.DataFrame, hype: pl.DataFrame) -> pl.DataFrame:
    """One row per match: the maker's side, the taker's fee and the block's time in ms."""
    pairs = with_fee_bps(pair_legs(legs), hype)
    return pairs.with_columns((pl.col("block_time").dt.epoch("ns") / 1e6).alias("t_ms")).sort(execution_order("taker_oid", "taker_side"))


def labels(
    t_ms: NDArray[np.float64], px: NDArray[np.float64], sigma: NDArray[np.float64], block: NDArray[np.int64], blocks: pl.DataFrame
) -> dict[str, NDArray[np.float64]]:
    """Markouts from the last mid strictly before the fill's block, and from the fill price."""
    bn = blocks["block_number"].to_numpy().astype(np.int64)
    bt = blocks["t_ms"].to_numpy().astype(np.float64)
    mid = blocks["mid"].to_numpy().astype(np.float64)
    pre = np.searchsorted(bn, block, side="left") - 1
    ok_pre = pre >= 0
    mid_pre = np.where(ok_pre, mid[np.maximum(pre, 0)], np.nan)
    stale_pre = ~ok_pre | (t_ms - np.where(ok_pre, bt[np.maximum(pre, 0)], -np.inf) > MAX_MID_LAG_MS)
    out: dict[str, NDArray[np.float64]] = {"mid_before": mid_pre}
    for h in HORIZONS_S:
        tag = f"{h:g}s"
        j = np.searchsorted(bt, t_ms + h * 1000.0, side="right") - 1
        mid_h = mid[np.maximum(j, 0)]
        bad = stale_pre | (j < 0) | (t_ms + h * 1000.0 - bt[np.maximum(j, 0)] > MAX_MID_LAG_MS)
        adv = np.where(bad, np.nan, sigma * (mid_h - mid_pre) / mid_pre * 1e4)
        out[f"markout_bps_{tag}"] = adv
        out[f"markout_px_bps_{tag}"] = np.where(bad, np.nan, sigma * (mid_h - px) / mid_pre * 1e4)
        out[f"toxic_{tag}"] = np.where(np.isnan(adv), np.nan, (adv < -TOXIC_BPS).astype(np.float64))
    return out


def build_day(args: argparse.Namespace, hype: pl.DataFrame, coin: str, date: str) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    path = layout.gold_training_path(coin, date)
    if args.skip_existing and path.exists():
        return {"date": date, "skipped": "exists"}
    try:
        cex = binance_days(args.binance_dir, coin, date)
    except AssertionError:
        return {"date": date, "skipped": "no Binance file"}
    t0 = time.perf_counter()
    rows = match_rows(load_legs(args.node_dir, coin, date), hype)
    blocks = block_table(rows.select("block_number", "taker_oid", "t_ms", "px", "notional", "taker_side", "fee_bps", "liquidation"))
    start = day_start_ms(date)
    day = rows.filter((pl.col("time_ms") >= start) & (pl.col("time_ms") < start + DAY_MS))
    block = day["block_number"].to_numpy().astype(np.int64)
    t_ms = day["t_ms"].to_numpy()
    side = day["maker_sigma"].to_numpy().astype(np.float64)
    px = day["px"].to_numpy()
    feats = trade_features(block, t_ms, side, blocks)
    bt = blocks["t_ms"].to_numpy().astype(np.float64)
    mids = blocks["mid"].to_numpy().astype(np.float64)
    cexf = cex_gap_features(t_ms, side, bt, mids, cex, latency_ms=args.cex_latency_ms)
    lab = labels(t_ms, px, side, block, blocks)
    frame = day.select(
        pl.lit(coin).alias("coin"),
        pl.col("time_ms").alias("ts_ms"),
        "block_number",
        "px",
        "sz",
        pl.col("maker_sigma").cast(pl.Float64).alias("maker_side"),
        pl.col("taker_oid").cast(pl.Int64).alias("oid"),
        pl.col("tid").cast(pl.Int64),
        pl.col("taker").alias("taker_user"),
        pl.col("maker").alias("maker_user"),
        "liquidation",
        pl.col("fee_bps").alias("taker_fee_prio_bps"),
    ).with_columns(
        pl.Series("l2_mid", lab["mid_before"]),
        pl.Series("l2_microprice", lab["mid_before"]),
        pl.Series("feature_ts_ms", t_ms),
        *(pl.Series(k, v) for k, v in lab.items() if k != "mid_before"),
        pl.Series("mid_before", lab["mid_before"]),
        *(pl.Series(k, v) for k, v in feats.items()),
        *(pl.Series(k, v) for k, v in cexf.items()),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    frame.write_parquet(tmp, compression="zstd")
    tmp.replace(path)
    trade_check = verify_trade_features_no_lookahead(
        block, t_ms, side, rows.select("block_number", "taker_oid", "t_ms", "px", "notional", "taker_side", "fee_bps", "liquidation"),
        (*TRADE_STATE_COLUMNS, *FEE_COLUMNS, *FEE_PLACEBO_COLUMNS, *FORCED_COLUMNS),
    )  # fmt: skip
    cex_check = verify_cex_gap_no_lookahead(t_ms, side, bt, mids, cex, latency_ms=args.cex_latency_ms)
    report = {"passed": bool(trade_check["passed"] and cex_check["passed"]), "join_passed": True, "trade": trade_check, "cex": cex_check}
    leakage_report_path(layout, coin, date).write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return {
        "date": date,
        "rows": frame.height,
        "labelled_10s": float(np.mean(~np.isnan(lab["markout_bps_10s"]))) if frame.height else 0.0,
        "leakage_passed": report["passed"],
        "elapsed_s": round(time.perf_counter() - t0, 1),
    }


def add_wallet_scores(args: argparse.Namespace, coin: str, dates: list[str]) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    present = [d for d in dates if layout.gold_training_path(coin, d).exists()]
    assert present, f"no Gold partitions for {coin}"
    cols = ["ts_ms", "taker_user", *(f"markout_bps_{h}" for h in WALLET_HORIZONS)]
    month = pl.concat(
        [
            pl.read_parquet(layout.gold_training_path(coin, d), columns=cols).with_columns(pl.lit(i).alias("_part"))
            for i, d in enumerate(present)
        ]
    )
    codes = month.select(pl.col("taker_user").rank("dense").cast(pl.Int64) - 1)["taker_user"].to_numpy()
    ts = month["ts_ms"].to_numpy().astype(np.float64)
    markouts = {h: month[f"markout_bps_{h}"].to_numpy().astype(np.float64) for h in WALLET_HORIZONS}
    wallet = wallet_toxicity_from_codes(ts, codes, markouts, prior_weight=DEFAULT_PRIOR_WEIGHT)
    checks = {
        h: verify_wallet_scores_no_lookahead(ts, codes, markouts[h], float(h[:-1]) * 1000.0, prior_weight=DEFAULT_PRIOR_WEIGHT)
        for h in WALLET_HORIZONS
    }
    passed = all(c["passed"] for c in checks.values())
    parts = month["_part"].to_numpy()
    for i, d in enumerate(present):
        path = layout.gold_training_path(coin, d)
        table = pq.read_table(path)
        rows = parts == i
        table = table.drop_columns([c for c in wallet if c in table.column_names])
        for name, values in wallet.items():
            table = table.append_column(name, pl.Series(values[rows]).to_arrow())
        tmp = path.with_suffix(".part")
        pq.write_table(table, tmp, compression="zstd")
        tmp.replace(path)
        sidecar = leakage_report_path(layout, coin, d)
        report = json.loads(sidecar.read_text(encoding="utf-8"))
        report["wallet"] = {"passed": passed, **checks}
        report["passed"] = bool(report["trade"]["passed"] and report["cex"]["passed"] and passed)
        sidecar.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return {"dates": len(present), "rows": int(ts.size), "wallet_check_passed": passed}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    coin = args.coin.upper()
    dates = list(parse_date_spec(args.dates))
    if args.stage == "wallet":
        logger.info(json.dumps(add_wallet_scores(args, coin, dates)))
        return 0
    hype = hype_usd(args.candles_dir)
    for date in dates:
        logger.info(json.dumps(build_day(args, hype, coin, date)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
