"""Add rungs L2 and L3 to a month of Gold training rows (Albers December 2025).

    python -m marketimmune.cli.enrich_albers --coin SOL --dates 20251201..20251231

Runs after ``build_albers_gold`` and rewrites each date's Gold training partition
with:

* L2: ``taker_tox_1s``, ``taker_tox_10s``, ``taker_log_n`` (shrunk taker-wallet
  scores; history runs across the whole month, so all dates are scored together);
* L3a: lost-race counts and notional per side over 250 ms / 1 s / 5 s;
* L3b: forced-liquidation notional per side over 1 s / 5 s / 60 s, and the
  forced-flow forecast from the position book (``fc_*``, from
  ``gold/hyperliquid/forced``, written by ``forced_forecast``). Dates without a
  forecast grid (the first two, which only fit the prior and the hazard scale)
  get NaN forecast columns.

Each family gets its own no-look-ahead check, folded into the date's
``.leakage.json``; the trainer reports ``leakage_safe`` only if all pass.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.cli.forced_forecast import forced_grid_path
from marketimmune.features.forced_flow_features import (
    GRID_INPUTS,
    empty_grid,
    forecast_features,
    verify_forecast_features_no_lookahead,
)
from marketimmune.features.order_events import (
    order_event_features,
    verify_order_event_features_no_lookahead,
)
from marketimmune.features.wallet_toxicity import (
    DEFAULT_PRIOR_WEIGHT,
    verify_wallet_scores_no_lookahead,
    wallet_toxicity_features,
)
from marketimmune.lake.tables import HyperliquidLakeLayout, leakage_report_path

EVENT_COLUMNS = (
    "ts_ms", "kind", "is_ask", "sz", "orig_sz", "opposite_best_px", "marketable_at_block_start",
)
PREV_DAY_EVENTS_MS = 5 * 60 * 1000  # longest event window is 60 s


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--wallet-horizons", default="1s,10s")
    parser.add_argument("--prior-weight", type=float, default=DEFAULT_PRIOR_WEIGHT)
    return parser.parse_args(argv)


def _shift(date: str, days: int) -> str:
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def load_events(layout: HyperliquidLakeLayout, coin: str, date: str) -> dict[str, npt.NDArray[Any]]:
    """The date's order events plus the previous date's last minutes."""
    parts: list[pa.Table] = []
    for day, tail in ((_shift(date, -1), True), (date, False)):
        path = layout.silver_order_events_path(coin, day)
        if not path.exists():
            continue
        table = pq.read_table(path, columns=list(EVENT_COLUMNS))
        if tail and table.num_rows:
            ts = table["ts_ms"].to_numpy()
            table = table.filter(pa.array(ts >= ts.max() - PREV_DAY_EVENTS_MS))
        parts.append(table)
    if not parts:
        return {c: np.zeros(0) for c in EVENT_COLUMNS}
    table = pa.concat_tables(parts)
    return {c: table[c].to_numpy(zero_copy_only=False) for c in EVENT_COLUMNS}


def load_forecast_grid(lake_root: Path, coin: str, date: str) -> dict[str, npt.NDArray[Any]]:
    """The date's forecast grid plus the previous date's last rows (forecast columns
    only). A grid written before the hazard scale existed (the forecaster's second
    date) is unscaled, 20 to 30 times too large, and is skipped."""
    parts: list[pa.Table] = []
    for day in (_shift(date, -1), date):
        path = forced_grid_path(lake_root, coin, day)
        if path.exists():
            table = pq.read_table(path, columns=[*GRID_INPUTS, "hazard_scaled"])
            table = table.filter(pc.equal(table["hazard_scaled"], True))
            parts.append(table.select(list(GRID_INPUTS)))
    if not parts:
        return empty_grid()
    table = pa.concat_tables(parts)
    return {c: table[c].to_numpy(zero_copy_only=False) for c in GRID_INPUTS}


def _merge_sidecar(path: Path, updates: dict[str, Any]) -> bool:
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    report.setdefault("join_passed", report.get("passed", False))
    report.update(updates)
    parts = [report["join_passed"]]
    parts += [report[k]["passed"] for k in ("cex", "wallet", "order_events", "forecast")
              if k in report]
    report["passed"] = all(bool(p) for p in parts)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return bool(report["passed"])


def build(args: argparse.Namespace) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    layout = HyperliquidLakeLayout(args.lake_root)
    horizons = [h.strip() for h in args.wallet_horizons.split(",") if h.strip()]
    dates = [d for d in parse_date_spec(args.dates) if layout.gold_training_path(coin, d).exists()]
    if not dates:
        print(json.dumps({"skipped": "no Gold training partitions"}))
        return []
    t0 = time.perf_counter()

    # L2 over the whole month at once: a wallet's history crosses days.
    cols = ["ts_ms", "taker_user", *(f"markout_bps_{h}" for h in horizons)]
    tables = [pq.read_table(layout.gold_training_path(coin, d), columns=cols) for d in dates]
    sizes = [t.num_rows for t in tables]
    month = pa.concat_tables(tables)
    ts = month["ts_ms"].to_numpy().astype(np.float64)
    taker = month["taker_user"].to_pylist()
    markouts = {
        h: month[f"markout_bps_{h}"].to_numpy(zero_copy_only=False).astype(np.float64)
        for h in horizons
    }
    wallet = wallet_toxicity_features(ts, taker, markouts, prior_weight=args.prior_weight)
    wallet_checks = {
        h: verify_wallet_scores_no_lookahead(
            ts, taker, markouts[h], float(h[:-1]) * 1000.0, prior_weight=args.prior_weight
        )
        for h in horizons
    }
    wallet_check = {"passed": all(c["passed"] for c in wallet_checks.values()), **wallet_checks}
    print(json.dumps({"wallet_rows": int(ts.size), "wallet_check_passed": wallet_check["passed"],
                      "elapsed_s": round(time.perf_counter() - t0, 1)}), flush=True)

    summaries: list[dict[str, Any]] = []
    offsets = np.concatenate(([0], np.cumsum(sizes)))
    for k, date in enumerate(dates):
        path = layout.gold_training_path(coin, date)
        table = pq.read_table(path)
        rows = slice(int(offsets[k]), int(offsets[k + 1]))
        new: dict[str, npt.NDArray[Any]] = {name: values[rows] for name, values in wallet.items()}
        events = load_events(layout, coin, date)
        fill_ts = table["ts_ms"].to_numpy().astype(np.float64)
        side = table["maker_side"].to_numpy().astype(np.float64)
        new.update(order_event_features(fill_ts, side, events))
        event_check = verify_order_event_features_no_lookahead(fill_ts, side, events)
        grid = load_forecast_grid(args.lake_root, coin, date)
        new.update(forecast_features(fill_ts, side, grid))
        forecast_check = verify_forecast_features_no_lookahead(fill_ts, side, grid)
        for name, values in new.items():
            if name in table.column_names:
                table = table.drop_columns([name])
            table = table.append_column(name, pa.array(values))
        pq.write_table(table, path, compression="zstd")
        passed = _merge_sidecar(
            leakage_report_path(layout, coin, date),
            {"wallet": wallet_check, "order_events": event_check, "forecast": forecast_check},
        )
        summary = {
            "date": date,
            "rows": table.num_rows,
            "events": int(np.asarray(events["ts_ms"]).size),
            "rows_with_forecast": forecast_check["rows_with_forecast"],
            "leakage_passed": passed,
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
