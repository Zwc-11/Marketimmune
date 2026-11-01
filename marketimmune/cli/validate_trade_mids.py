"""How close markouts on the trade-implied mid come to Gold's, which use the rebuilt book.

    python -m marketimmune.cli.validate_trade_mids --coins SOL,ETH --dates 20251201..20251231 --out eval/trade_mid_validation.json

The priority-fee work (``cli.priority_fee_bands``) has no order book after December 2025, so it
measures markouts on a mid implied by trades (``priority.fees.trade_mids``). On December 2025
both exist. Each node trade is joined to its Gold row (taker order id, time, price, size) and the
two are compared:

- Gold ``markout_bps_<h>`` (move of the mid from before the fill) against ``adv_<h>s``;
- Gold ``markout_px_bps_<h>`` (from the fill price) against ``mo_<h>s``;
- and the mean of each by bucket of ``cex_gap_maker_bps``, a known driver of the markout.
  This shows whether conditional differences, which the fee-band table relies on, survive.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.priority.fees import fill_markouts
from marketimmune.utils import parse_date_spec, parse_symbol_spec

HORIZONS_S = (1.0, 10.0, 60.0)
GAP_EDGES_BPS = (-2.0, -0.5, 0.5, 2.0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="SOL,ETH")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--out", type=Path, default=Path("eval/trade_mid_validation.json"))
    return parser.parse_args(argv)


def joined_day(args: argparse.Namespace, coin: str, date: str) -> pl.DataFrame:
    trades = fill_markouts(pl.read_parquet(args.node_dir / coin / f"{coin}-{date}.parquet"), None, HORIZONS_S)
    gold_cols = ["ts_ms", "px", "sz", "oid", "cex_gap_maker_bps", *(f"markout{k}_bps_{h:g}s" for h in HORIZONS_S for k in ("", "_px"))]
    gold = pl.read_parquet(HyperliquidLakeLayout(args.lake_root).gold_training_path(coin, date), columns=gold_cols)
    gold = gold.unique(["oid", "ts_ms", "px", "sz"], keep="none")  # a key seen twice cannot be paired
    left = trades.select(
        pl.col("taker_oid").alias("oid"),
        pl.col("time_ms").alias("ts_ms"),
        "px",
        "sz",
        *(f"{k}_{h:g}s" for h in HORIZONS_S for k in ("adv", "mo")),
    ).unique(["oid", "ts_ms", "px", "sz"], keep="none")
    return left.join(gold.with_columns(pl.col("oid").cast(pl.UInt64)), on=["oid", "ts_ms", "px", "sz"], how="inner")


def compare(frame: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"trades": frame.height}
    for h in HORIZONS_S:
        for ours, gold in ((f"adv_{h:g}s", f"markout_bps_{h:g}s"), (f"mo_{h:g}s", f"markout_px_bps_{h:g}s")):
            f = frame.select(ours, gold).drop_nulls().filter(pl.col(ours).is_finite() & pl.col(gold).is_finite())
            a, b = f[ours].to_numpy(), f[gold].to_numpy()
            out[ours] = {
                "vs": gold,
                "n": int(a.size),
                "corr": float(np.corrcoef(a, b)[0, 1]),
                "mean_trade_mid": float(a.mean()),
                "mean_gold": float(b.mean()),
                "mean_abs_diff": float(np.abs(a - b).mean()),
            }
    edges = (-np.inf, *GAP_EDGES_BPS, np.inf)
    buckets = []
    gap = frame["cex_gap_maker_bps"].to_numpy()
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        m = (gap > lo) & (gap <= hi)
        sub = frame.filter(pl.Series(m))
        buckets.append(
            {
                "cex_gap_maker_bps": [lo if np.isfinite(lo) else None, hi if np.isfinite(hi) else None],
                "trades": sub.height,
                "adv_1s_trade_mid": float(sub["adv_1s"].mean()) if sub.height else None,  # type: ignore[arg-type]
                "adv_1s_gold": float(sub["markout_bps_1s"].mean()) if sub.height else None,  # type: ignore[arg-type]
            }
        )
    out["by_cex_gap"] = buckets
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result: dict[str, Any] = {"dates": args.dates, "coins": {}}
    for coin in parse_symbol_spec(args.coins):
        frame = pl.concat([joined_day(args, coin, d) for d in parse_date_spec(args.dates)])
        result["coins"][coin] = compare(frame)
        r = result["coins"][coin]
        print(
            f"{coin}: {r['trades']:,} trades; adv_1s corr {r['adv_1s']['corr']:.3f}, mean {r['adv_1s']['mean_trade_mid']:+.3f} vs Gold {r['adv_1s']['mean_gold']:+.3f}"
        )
        for b in (b for b in r["by_cex_gap"] if b["trades"]):
            print(
                f"   cex gap {b['cex_gap_maker_bps']}: {b['trades']:>8} trades, adv 1 s {b['adv_1s_trade_mid']:+.2f} vs Gold {b['adv_1s_gold']:+.2f}"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
