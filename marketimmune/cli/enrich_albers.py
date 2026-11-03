"""Add rungs L2 and L3 to a month of Gold training rows (Albers December 2025).

    python -m marketimmune.cli.enrich_albers --coin SOL --dates 20251201..20251231

Runs after ``build_albers_gold`` and ``forced_forecast`` and rewrites each date's Gold training
partition with:

* L2: ``taker_tox_1s``, ``taker_tox_10s``, ``taker_log_n`` (shrunk taker-wallet scores; a
  wallet's history runs across the whole month, so all dates are scored together);
* L3a: lost-race counts and notional per side over 250 ms / 1 s / 5 s;
* L3b: forced-liquidation notional per side over 1 s / 5 s / 60 s, and the forced-flow forecast
  ``fc_*`` from ``gold/hyperliquid/forced``. Dates without a hazard-scaled grid (the first two,
  which only fit the prior and the scale) get NaN forecast columns.

Each family gets its own no-look-ahead check, folded into the date's ``.leakage.json``; the
trainer reports ``leakage_safe`` only if all pass.
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
import pyarrow.compute as pc
import pyarrow.parquet as pq

from marketimmune.cli.forced_forecast import forced_grid_path
from marketimmune.features.forced_flow_features import GRID_INPUTS, forecast_features, verify_forecast_features_no_lookahead
from marketimmune.features.order_events import order_event_features, verify_order_event_features_no_lookahead
from marketimmune.features.wallet_toxicity import DEFAULT_PRIOR_WEIGHT, verify_wallet_scores_no_lookahead, wallet_toxicity_features
from marketimmune.lake.tables import HyperliquidLakeLayout, leakage_report_path
from marketimmune.logger import init_logger
from marketimmune.utils import parse_date_spec, shift_date, split_csv

logger = init_logger(__name__)
EVENT_COLUMNS = ("ts_ms", "kind", "is_ask", "sz", "orig_sz", "opposite_best_px", "marketable_at_block_start")
PREV_DAY_EVENTS_MS = 5 * 60 * 1000  # the longest event window is 60 s


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--wallet-horizons", default="1s,10s")
    parser.add_argument("--prior-weight", type=float, default=DEFAULT_PRIOR_WEIGHT)
    return parser.parse_args(argv)


def _read(path: Path, columns: tuple[str, ...], *, scaled_only: bool = False) -> pa.Table | None:
    """A day's table (for a forecast grid, only its hazard-scaled rows), or None if missing."""
    if not path.exists():
        return None
    if not scaled_only:
        return pq.read_table(path, columns=list(columns))
    # a grid written before the hazard scale existed is 20 to 30 times too large
    table = pq.read_table(path, columns=[*columns, "hazard_scaled"])
    return table.filter(pc.equal(table["hazard_scaled"], True)).select(list(columns))


def _tail(events: pa.Table | None) -> pa.Table | None:
    """The previous day's last minutes of events."""
    if events is None or not events.num_rows:
        return events
    ts = events["ts_ms"].to_numpy()
    return events.filter(pa.array(ts >= ts.max() - PREV_DAY_EVENTS_MS))


def _arrays(tables: list[pa.Table | None], columns: tuple[str, ...]) -> dict[str, npt.NDArray[Any]]:
    present = [t for t in tables if t is not None]
    if not present:
        return {c: np.zeros(0) for c in columns}
    table = pa.concat_tables(present)
    return {c: table[c].to_numpy(zero_copy_only=False) for c in columns}


def _merge_sidecar(path: Path, updates: dict[str, Any]) -> bool:
    report = json.loads(path.read_text(encoding="utf-8"))
    report.setdefault("join_passed", report["passed"])
    report.update(updates)
    report["passed"] = bool(report["join_passed"]) and all(
        bool(report[k]["passed"]) for k in ("cex", "wallet", "order_events", "forecast") if k in report
    )
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return bool(report["passed"])


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    horizons = split_csv(args.wallet_horizons)
    dates = [d for d in parse_date_spec(args.dates) if layout.gold_training_path(coin, d).exists()]
    if not dates:
        logger.info("no Gold training partitions for %s", args.dates)
        return []
    t0 = time.perf_counter()

    # L2 over the whole month at once: a wallet's history crosses days.
    cols = ["ts_ms", "taker_user", *(f"markout_bps_{h}" for h in horizons)]
    tables = [pq.read_table(layout.gold_training_path(coin, d), columns=cols) for d in dates]
    offsets = np.cumsum([0, *(t.num_rows for t in tables)])
    month = pa.concat_tables(tables)
    ts = month["ts_ms"].to_numpy().astype(np.float64)
    taker = month["taker_user"].to_numpy(zero_copy_only=False)
    markouts = {h: month[f"markout_bps_{h}"].to_numpy(zero_copy_only=False).astype(np.float64) for h in horizons}
    wallet = wallet_toxicity_features(ts, taker, markouts, prior_weight=args.prior_weight)
    checks = {
        h: verify_wallet_scores_no_lookahead(ts, taker, markouts[h], float(h[:-1]) * 1000.0, prior_weight=args.prior_weight)
        for h in horizons
    }
    wallet_check = {"passed": all(c["passed"] for c in checks.values()), **checks}
    logger.info(
        json.dumps(
            {"wallet_rows": int(ts.size), "wallet_check_passed": wallet_check["passed"], "elapsed_s": round(time.perf_counter() - t0, 1)}
        )
    )

    summaries: list[dict[str, Any]] = []
    prev_events: pa.Table | None = None  # each day's events serve as the next day's tail
    prev_grid: pa.Table | None = None
    for k, date in enumerate(dates):
        prev = shift_date(date, -1)
        if k == 0 or dates[k - 1] != prev:
            prev_events = _read(layout.silver_order_events_path(coin, prev), EVENT_COLUMNS)
            prev_grid = _read(forced_grid_path(args.lake_root, coin, prev), GRID_INPUTS, scaled_only=True)
        day_events = _read(layout.silver_order_events_path(coin, date), EVENT_COLUMNS)
        day_grid = _read(forced_grid_path(args.lake_root, coin, date), GRID_INPUTS, scaled_only=True)
        events = _arrays([_tail(prev_events), day_events], EVENT_COLUMNS)
        grid = _arrays([prev_grid, day_grid], GRID_INPUTS)
        prev_events, prev_grid = day_events, day_grid

        path = layout.gold_training_path(coin, date)
        table = pq.read_table(path)
        fill_ts = table["ts_ms"].to_numpy().astype(np.float64)
        side = table["maker_side"].to_numpy().astype(np.float64)
        rows = slice(int(offsets[k]), int(offsets[k + 1]))
        new = (
            {name: values[rows] for name, values in wallet.items()}
            | order_event_features(fill_ts, side, events)
            | forecast_features(fill_ts, side, grid)
        )
        table = table.drop_columns([c for c in new if c in table.column_names])
        for name, values in new.items():
            table = table.append_column(name, pa.array(values))
        pq.write_table(table, path, compression="zstd")
        event_check = verify_order_event_features_no_lookahead(fill_ts, side, events)
        forecast_check = verify_forecast_features_no_lookahead(fill_ts, side, grid)
        passed = _merge_sidecar(
            leakage_report_path(layout, coin, date), {"wallet": wallet_check, "order_events": event_check, "forecast": forecast_check}
        )
        summary = {
            "date": date,
            "rows": table.num_rows,
            "events": int(events["ts_ms"].size),
            "rows_with_forecast": forecast_check["rows_with_forecast"],
            "leakage_passed": passed,
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }
        summaries.append(summary)
        logger.info(json.dumps(summary))
    return summaries


def main(argv: list[str] | None = None) -> int:
    build(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
