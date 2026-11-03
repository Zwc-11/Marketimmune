"""Node fills (``pull_node_fills``) against the Albers Silver fills, trade by trade.

    python -m marketimmune.cli.reconcile_node_fills --coins SOL,ETH --dates 20251201..20251231 --out eval/node_fills_reconciliation.json

Each trade is keyed by its maker and taker order ids; Albers has no trade id. For every date:
trades in both, and how many of those differ in price, size, time, taker side or the liquidation
flag; trades in only one source; and the windows of node-only trades (separated by more than a
minute), with the Silver L2 rows inside each. A trade at 23:59:59 can sit under adjacent dates in
the two sources, so a one-sided trade within a second of midnight is counted as a boundary trade.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.priority.fills import pair_legs
from marketimmune.utils import DAY_MS, parse_date_spec, parse_symbol_spec

KEY = ["maker_oid", "taker_oid"]
COMPARED = ("px", "sz", "taker_side", "liquidation")
RUN_GAP_MS = 60_000
BOUNDARY_MS = 1_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="SOL,ETH")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--out", type=Path, default=Path("eval/node_fills_reconciliation.json"))
    return parser.parse_args(argv)


def node_trades(legs: pl.DataFrame) -> pl.DataFrame:
    """One row per trade from a day of node legs (taker and maker joined on the trade id)."""
    return pair_legs(legs).select(*KEY, pl.col("time_ms").alias("ts_ms"), *COMPARED)


def albers_trades(silver: pl.DataFrame) -> pl.DataFrame:
    return silver.select(*(pl.col(k).cast(pl.UInt64) for k in KEY), "ts_ms", *COMPARED)


def runs(ts_ms: npt.NDArray[np.int64], gap_ms: int = RUN_GAP_MS) -> list[tuple[int, int, int]]:
    """``(first, last, count)`` of each run of sorted times separated by more than ``gap_ms``."""
    if ts_ms.size == 0:
        return []
    t = np.sort(ts_ms)
    parts = np.split(t, np.flatnonzero(np.diff(t) > gap_ms) + 1)
    return [(int(p[0]), int(p[-1]), int(p.size)) for p in parts]


def reconcile_day(node: pl.DataFrame, albers: pl.DataFrame, l2_ts_ms: npt.NDArray[np.int64], day_start_ms: int) -> dict[str, Any]:
    both = node.join(albers, on=KEY, how="inner", suffix="_a")
    only_node = node.join(albers, on=KEY, how="anti")
    only_albers = albers.join(node, on=KEY, how="anti")

    def boundary(frame: pl.DataFrame) -> int:
        t = frame["ts_ms"]
        return int(((t < day_start_ms + BOUNDARY_MS) | (t >= day_start_ms + DAY_MS - BOUNDARY_MS)).sum())

    windows = []
    for first, last, count in runs(only_node["ts_ms"].to_numpy()):
        if boundary(only_node.filter(pl.col("ts_ms").is_between(first, last))) == count:
            continue  # filed under the next or previous date by Albers
        a = albers["ts_ms"].to_numpy()
        before, after = a[a < first], a[a > last]
        windows.append(
            {
                "first_ms": first,
                "last_ms": last,
                "trades": count,
                "albers_stops_ms": int(before.max()) if before.size else None,
                "albers_resumes_ms": int(after.min()) if after.size else None,
                "l2_rows_inside": int(((l2_ts_ms >= first) & (l2_ts_ms <= last)).sum()),
            }
        )
    return {
        "node": node.height,
        "albers": albers.height,
        "matched": both.height,
        "differ": {c: int((both[c] != both[f"{c}_a"]).sum()) for c in ("ts_ms", *COMPARED)},
        "node_only": only_node.height,
        "albers_only": only_albers.height,
        "boundary": {"node_only": boundary(only_node), "albers_only": boundary(only_albers)},
        "node_only_liquidations": int(only_node["liquidation"].sum()),
        "windows": windows,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    out: dict[str, Any] = {"dates": args.dates, "coins": {}}
    for coin in parse_symbol_spec(args.coins):
        days = {}
        for date in parse_date_spec(args.dates):
            node = node_trades(pl.read_parquet(args.node_dir / coin / f"{coin}-{date}.parquet"))
            albers = albers_trades(pl.read_parquet(layout.silver_fills_path(coin, date)))
            l2 = pl.read_parquet(layout.silver_l2_book_path(coin, date), columns=["ts_ms"])["ts_ms"].to_numpy()
            start = int(np.datetime64(f"{date[:4]}-{date[4:6]}-{date[6:]}", "ms").astype(np.int64))
            days[date] = reconcile_day(node, albers, l2, start)
        total = {k: sum(d[k] for d in days.values()) for k in ("node", "albers", "matched", "node_only", "albers_only")}
        total["differ"] = {c: sum(d["differ"][c] for d in days.values()) for c in ("ts_ms", *COMPARED)}
        total["boundary"] = {s: sum(d["boundary"][s] for d in days.values()) for s in ("node_only", "albers_only")}
        total["node_only_share"] = total["node_only"] / total["node"] if total["node"] else 0.0
        total["windows"] = sum(len(d["windows"]) for d in days.values())
        total["window_trades"] = sum(w["trades"] for d in days.values() for w in d["windows"])
        out["coins"][coin] = {"total": total, "days": days}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    out = run(parse_args(argv))
    for coin, r in out["coins"].items():
        t = r["total"]
        print(
            f"{coin}: {t['matched']:,} of {t['albers']:,} Albers trades matched; differ {t['differ']}; "
            f"node-only {t['node_only']:,} ({t['node_only_share']:.2%}) in {t['windows']} windows; boundary {t['boundary']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
