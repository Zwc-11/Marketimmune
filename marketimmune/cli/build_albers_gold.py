"""Silver (Albers rebuild) -> Gold markout labels and Gold training rows, per date.

    python -m marketimmune.cli.build_albers_gold --coin SOL --dates 20251201..20251231

Needs the Silver L2 days from ``build_albers_silver.py`` and the Silver fills
from ``build_albers_fills.py``. Labels use the pre-fill mid (fix L2) at 1/10/60 s;
mids from the next date are read too, so fills near midnight keep their 60 s
label. Training rows go through the same join and no-look-ahead check as
``rebuild_hyperliquid_training_rows.py`` (a ``.leakage.json`` per date).

When the Binance ``aggTrades`` zips are present (``make download-binance``),
the L1 CEX-gap columns are added to the training rows and get
their own no-look-ahead check, folded into the same ``.leakage.json``.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.cli.rebuild_training_rows import rebuild_training_rows
from marketimmune.features.cex_gap import (
    DEFAULT_LATENCY_MS,
    PriceSeries,
    cex_gap_features,
    read_binance_aggtrades_zip,
    verify_cex_gap_no_lookahead,
)
from marketimmune.labels.markout import MarkoutConfig
from marketimmune.lake.gold import build_markout_gold_rows_from_mids
from marketimmune.lake.tables import (
    HyperliquidLakeLayout,
    leakage_report_path,
    read_parquet_records,
    write_gold_markout,
)
from marketimmune.sources.hyperliquid_node_fills import MatchFill

NEXT_DAY_SPAN_MS = 5 * 60 * 1000  # longest horizon is 60 s; keep a margin
PREV_DAY_SPAN_MS = 30 * 60 * 1000  # the CEX gap looks back to the last HL mid change


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument(
        "--binance-dir",
        type=Path,
        default=Path("data/bronze/binance/aggTrades"),
    )
    parser.add_argument("--binance-symbol", default=None, help="default <COIN>USDT")
    parser.add_argument("--cex-latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    return parser.parse_args(argv)


def _shift(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def load_mids(
    layout: HyperliquidLakeLayout, coin: str, date: str, *, prev_tail_ms: float = 0.0
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Mids for ``date`` plus the first minutes of the next date (and, if asked, the
    last ``prev_tail_ms`` of the previous date), sorted by time."""
    ts_parts, mid_parts = [], []
    spans: list[tuple[str, float | None]] = (
        [(_shift(date, -1), -prev_tail_ms)] if prev_tail_ms > 0 else []
    )
    spans += [(date, None), (_shift(date, 1), NEXT_DAY_SPAN_MS)]
    for day, cap in spans:
        path = layout.silver_l2_book_path(coin, day)
        if not path.exists():
            continue
        table = pq.read_table(path, columns=["ts_ms", "mid"])
        ts = table["ts_ms"].to_numpy().astype(np.float64)
        mid = table["mid"].to_numpy().astype(np.float64)
        if cap is not None and ts.size:
            keep = ts < ts[0] + cap if cap > 0 else ts >= ts[-1] + cap
            ts, mid = ts[keep], mid[keep]
        ts_parts.append(ts)
        mid_parts.append(mid)
    if not ts_parts:
        return np.zeros(0), np.zeros(0)
    ts_all, mid_all = np.concatenate(ts_parts), np.concatenate(mid_parts)
    order = np.argsort(ts_all, kind="stable")
    return ts_all[order], mid_all[order]


def add_cex_features(
    args: argparse.Namespace, layout: HyperliquidLakeLayout, coin: str, date: str
) -> dict[str, Any]:
    """Append the L1 columns to the date's Gold training rows; check them for look-ahead."""
    symbol = args.binance_symbol or f"{coin}USDT"
    zips = [
        args.binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip"
        for d in (_shift(date, -1), date)
    ]
    if not zips[1].exists():
        return {"added": False, "reason": f"missing {zips[1].name}"}
    cex = PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])
    hl_ts, hl_mid = load_mids(layout, coin, date, prev_tail_ms=PREV_DAY_SPAN_MS)
    path = layout.gold_training_path(coin, date)
    table = pq.read_table(path)
    fill_ts = table["ts_ms"].to_numpy().astype(np.float64)
    side = table["maker_side"].to_numpy().astype(np.float64)
    features = cex_gap_features(fill_ts, side, hl_ts, hl_mid, cex, latency_ms=args.cex_latency_ms)
    for name, values in features.items():
        if name in table.column_names:
            table = table.drop_columns([name])
        table = table.append_column(name, pa.array(values))
    pq.write_table(table, path, compression="zstd")
    check = verify_cex_gap_no_lookahead(
        fill_ts, side, hl_ts, hl_mid, cex, latency_ms=args.cex_latency_ms
    )
    sidecar = leakage_report_path(layout, coin, date)
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    report["join_passed"] = report.get("join_passed", report["passed"])
    report["cex"] = check
    report["passed"] = bool(report["join_passed"]) and check["passed"]
    sidecar.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    nan_share = float(np.mean(np.isnan(features["cex_gap_bps"]))) if fill_ts.size else 0.0
    return {"added": True, "leakage_passed": check["passed"], "nan_share": nan_share}


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    config = MarkoutConfig(horizons_s=(1.0, 10.0, 60.0))
    summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        fills_path = layout.silver_fills_path(coin, date)
        mid_ts_ms, mid_px = load_mids(layout, coin, date)
        if not fills_path.exists() or mid_ts_ms.size == 0:
            print(json.dumps({"date": date, "skipped": "missing Silver fills or L2"}), flush=True)
            continue
        matches = [MatchFill.from_record(r) for r in read_parquet_records(fills_path)]
        rows = build_markout_gold_rows_from_mids(
            matches, mid_ts_ms / 1000.0, mid_px, config, coin=coin
        )
        if not rows:
            print(json.dumps({"date": date, "skipped": "no labelled fills"}), flush=True)
            continue
        write_gold_markout(layout, coin=coin, date=date, rows=rows)
        result = rebuild_training_rows(lake_root=args.lake_root, coin=coin, date=date)
        cex = add_cex_features(args, layout, coin, date) if result["training_rows"] else {}
        summary = {
            "date": date,
            "fills": len(matches),
            "gold_rows": len(rows),
            "toxic_10s_rate": float(np.mean([r.toxic.get("10s", False) for r in rows])),
            "training_rows": result["training_rows"],
            "leakage_check": result["leakage_check"],
            "cex": cex,
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    return summaries


def main(argv: list[str] | None = None) -> int:
    build(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
