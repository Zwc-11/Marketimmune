"""Silver (Albers rebuild) -> Gold markout labels and Gold training rows, per date.

    python -m marketimmune.cli.build_albers_gold --coin SOL --dates 20251201..20251231

Needs the Silver L2 days from ``build_albers_silver`` and the Silver fills from
``build_albers_fills``. Labels use the pre-fill mid (fix L2) at 1/10/60 s; mids from the
next date are read too, so fills near midnight keep their 60 s label. Training rows go
through the same join and no-look-ahead check as ``rebuild_training_rows`` (a
``.leakage.json`` per date). When the date's Binance ``aggTrades`` zip is present
(``make download-binance``), the L1 CEX-gap columns are added to the training rows and
get their own no-look-ahead check in the same ``.leakage.json``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

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
from marketimmune.lake.tables import HyperliquidLakeLayout, leakage_report_path, read_parquet_records, write_gold_markout
from marketimmune.logger import init_logger
from marketimmune.sources.hyperliquid_node_fills import MatchFill
from marketimmune.utils import parse_date_spec, shift_date

logger = init_logger(__name__)

NEXT_DAY_SPAN_MS = 5 * 60 * 1000  # longest horizon is 60 s; keep a margin
PREV_DAY_SPAN_MS = 30 * 60 * 1000  # the CEX gap looks back to the last HL mid change


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--cex-latency-ms", type=float, default=DEFAULT_LATENCY_MS)
    parser.add_argument(
        "--max-mid-lag-s", type=float, default=30.0, help="drop a label whose pre-fill or horizon mid is staler than this (data gaps)"
    )
    return parser.parse_args(argv)


def load_mids(
    layout: HyperliquidLakeLayout, coin: str, date: str, *, prev_tail_ms: float = 0.0
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """``(ts_ms, mid)`` for ``date`` plus the first minutes of the next date (and, when
    asked, the last ``prev_tail_ms`` of the previous date), in time order."""
    spans: list[tuple[str, float | None]] = [(shift_date(date, -1), -prev_tail_ms)] if prev_tail_ms > 0 else []
    spans += [(date, None), (shift_date(date, 1), NEXT_DAY_SPAN_MS)]
    ts_parts, mid_parts = [np.zeros(0)], [np.zeros(0)]
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
    ts_all = np.concatenate(ts_parts)
    assert np.all(ts_all[1:] >= ts_all[:-1]), f"{coin} {date}: Silver L2 mids out of time order"
    return ts_all, np.concatenate(mid_parts)


def add_cex_features(args: argparse.Namespace, layout: HyperliquidLakeLayout, coin: str, date: str) -> dict[str, Any]:
    """Append the L1 columns to the date's Gold training rows; check them for look-ahead."""
    symbol = f"{coin}USDT"
    zips = [args.binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip" for d in (shift_date(date, -1), date)]
    if not zips[1].exists():
        return {"added": False, "reason": f"missing {zips[1].name}"}
    cex = PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])
    hl_ts, hl_mid = load_mids(layout, coin, date, prev_tail_ms=PREV_DAY_SPAN_MS)
    path = layout.gold_training_path(coin, date)
    table = pq.read_table(path)
    fill_ts = table["ts_ms"].to_numpy().astype(np.float64)
    side = table["maker_side"].to_numpy().astype(np.float64)
    features = cex_gap_features(fill_ts, side, hl_ts, hl_mid, cex, latency_ms=args.cex_latency_ms)
    table = table.drop_columns([name for name in features if name in table.column_names])
    for name, values in features.items():
        table = table.append_column(name, pa.array(values))
    pq.write_table(table, path, compression="zstd")
    check = verify_cex_gap_no_lookahead(fill_ts, side, hl_ts, hl_mid, cex, latency_ms=args.cex_latency_ms)
    sidecar = leakage_report_path(layout, coin, date)
    report = json.loads(sidecar.read_text(encoding="utf-8"))
    report["join_passed"] = report["passed"]
    report["cex"] = check
    report["passed"] = bool(report["join_passed"]) and check["passed"]
    sidecar.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    nan_share = float(np.mean(np.isnan(features["cex_gap_bps"]))) if fill_ts.size else 0.0
    return {"added": True, "leakage_passed": check["passed"], "nan_share": nan_share}


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    # A label may not lean on a mid from across a gap in the data.
    config = MarkoutConfig(horizons_s=(1.0, 10.0, 60.0), max_mid_lag_s=args.max_mid_lag_s)
    summaries: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    for date in parse_date_spec(args.dates):
        fills_path = layout.silver_fills_path(coin, date)
        mid_ts_ms, mid_px = load_mids(layout, coin, date)
        if not fills_path.exists() or mid_ts_ms.size == 0:
            logger.info(f"{date}: skipped, missing Silver fills or L2")
            continue
        matches = [MatchFill.from_record(r) for r in read_parquet_records(fills_path)]
        rows = build_markout_gold_rows_from_mids(matches, mid_ts_ms / 1000.0, mid_px, config, coin=coin)
        if not rows:
            logger.info(f"{date}: skipped, no labelled fills")
            continue
        write_gold_markout(layout, coin=coin, date=date, rows=rows)
        result = rebuild_training_rows(lake_root=args.lake_root, coin=coin, date=date)
        summary = {
            "date": date,
            "fills": len(matches),
            "gold_rows": len(rows),
            "toxic_10s_rate": float(np.mean([r.toxic.get("10s", False) for r in rows])),
            "training_rows": result["training_rows"],
            "leakage_check": result["leakage_check"],
            "cex": add_cex_features(args, layout, coin, date) if result["training_rows"] else {},
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }
        summaries.append(summary)
        logger.info(json.dumps(summary))
    return summaries


def main(argv: list[str] | None = None) -> int:
    print(json.dumps(build(parse_args(argv)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
