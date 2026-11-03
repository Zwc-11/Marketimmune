"""Quote-time models: the fill-time columns are gone, and the features served on L2 rows are the
ones Gold gives a fill at the same time."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from marketimmune.cli import quote_signals
from marketimmune.cli.forced_forecast import forced_grid_path
from marketimmune.features.cex_gap import PriceSeries
from marketimmune.features.forced_flow_features import GRID_INPUTS
from marketimmune.features.training_rows import FEATURE_SETS, HYPERLIQUID_OFI_COLUMNS, build_hyperliquid_training_rows
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.models.quantile_ladder import LgbParams
from marketimmune.sim.signals import (
    FILL_TIME_COLUMNS,
    DayInputs,
    fit_quantiles,
    l2_row_features,
    load_day_inputs,
    predict_quantiles,
    quote_columns,
    quote_features,
    quote_signals_path,
)
from marketimmune.utils import day_start_ms, parse_date_spec, shift_date

FloatArray = npt.NDArray[np.float64]
L2_COLUMNS = ("l2_spread_bps", "l2_microprice_offset_bps", "l2_top_imbalance", *HYPERLIQUID_OFI_COLUMNS)


def _book(n: int, seed: int, t0_ms: float = 1_000.0) -> tuple[FloatArray, dict[str, FloatArray]]:
    """Random top-of-book rows, one block time repeated (a block split across hourly files) and
    one 40 s gap (a Silver book reset)."""
    rng = np.random.default_rng(seed)
    step = rng.integers(50, 400, n).astype(np.float64)
    step[0], step[n // 3] = 0.0, 40_000.0
    ts = t0_ms + np.cumsum(step)
    ts[n // 2] = ts[n // 2 - 1]
    bid = 100.0 + np.round(np.cumsum(rng.normal(0, 0.01, n)), 2)
    ask = bid + 0.01 * rng.integers(1, 3, n)
    book = {"bid_px": bid, "bid_sz": rng.uniform(1, 9, n), "ask_px": ask, "ask_sz": rng.uniform(1, 9, n)}
    book["mid"] = (bid + ask) / 2
    book["spread_bps"] = (ask - bid) / book["mid"] * 1e4
    book["microprice"] = (bid * book["ask_sz"] + ask * book["bid_sz"]) / (book["bid_sz"] + book["ask_sz"])
    book["top_imbalance"] = (book["bid_sz"] - book["ask_sz"]) / (book["bid_sz"] + book["ask_sz"])
    return ts, book


def _inputs(ts: FloatArray, book: dict[str, FloatArray]) -> DayInputs:
    empty = np.zeros(0)
    return DayInputs(
        l2_ts_ms=ts,
        l2_ts_ns=np.rint(ts * 1e6).astype(np.int64),
        l2=l2_row_features(ts, book),
        mid_ts_ms=empty,
        mid=empty,
        cex=PriceSeries(empty, empty),
        events={},
        grid={},
    )


def test_quote_columns_drop_only_the_fill_time_columns() -> None:
    s2, s3 = quote_columns("s2"), quote_columns("s3")
    assert s2 == tuple(c for c in FEATURE_SETS["l1_book"] if c != "sz")  # every rung-L2 column is a wallet score
    assert set(FEATURE_SETS["l3_book"]) - set(s3) == set(FILL_TIME_COLUMNS)
    assert s3[: len(s2)] == s2 and not set(s3) & set(FILL_TIME_COLUMNS)


def test_l2_features_match_golds_join() -> None:
    ts, book = _book(300, seed=1)
    rows = [{"coin": "SOL", "ts_ms": float(t), **{k: float(v[i]) for k, v in book.items()}} for i, t in enumerate(ts)]
    fills = np.sort(np.r_[ts[0] - 50, ts[0], ts[1:6], np.random.default_rng(2).uniform(ts[0], ts[-1] + 100, 500)])
    gold = build_hyperliquid_training_rows([{"coin": "SOL", "ts_ms": float(t)} for t in fills], rows)
    t = np.array([g["ts_ms"] for g in gold])
    assert t.size == fills.size - 2  # a fill at or before the first row gets no Gold row
    served = quote_features(_inputs(ts, book), t, 1.0, L2_COLUMNS)
    expected = {
        "l2_spread_bps": [g["l2_spread_bps"] for g in gold],
        "l2_microprice_offset_bps": [(g["l2_microprice"] - g["l2_mid"]) / g["l2_mid"] * 1e4 for g in gold],
        "l2_top_imbalance": [g["l2_top_imbalance"] for g in gold],
        **{c: [g[c] for g in gold] for c in HYPERLIQUID_OFI_COLUMNS},
    }
    for k, c in enumerate(L2_COLUMNS):
        np.testing.assert_array_equal(served[:, k], expected[c], err_msg=c)
    assert np.isnan(quote_features(_inputs(ts, book), [ts[0]], 1.0, L2_COLUMNS)).all()  # nothing strictly before


def test_quote_rows_read_each_blocks_own_row() -> None:
    ts, book = _book(50, seed=3)
    inputs = _inputs(ts, book)
    ts_ns, t_ms = inputs.quote_rows()
    assert ts_ns.size == ts.size - 1 and np.all(np.diff(ts_ns) > 0)  # the repeated block keeps its last row
    last = np.append(ts[1:] != ts[:-1], True)
    served = quote_features(inputs, t_ms, -1.0, ("maker_side", "l2_ofi_event"))
    np.testing.assert_array_equal(served[:, 1], inputs.l2["l2_ofi_event"][last])
    assert np.all(served[:, 0] == -1.0)


def test_predicted_quantiles_are_sorted_and_missing_features_unscored() -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(size=(600, 3)).astype(np.float32)
    y = 2.0 * x[:, 0] + rng.normal(size=600)
    boosters = fit_quantiles(x, y, seed=1, params=LgbParams(n_estimators=20, min_child_samples=20))
    x_new = x[:10].copy()
    x_new[3, 1] = np.nan
    q = predict_quantiles(boosters, x_new)
    assert np.isnan(q[3]).all() and np.isfinite(np.delete(q, 3, axis=0)).all()
    assert np.all(np.diff(np.delete(q, 3, axis=0), axis=1) >= 0)


# ---- the CLI on a nine-day lake ------------------------------------------------------------------

DATES = parse_date_spec("20251201..20251209")


def _write_lake(root: Path, binance: Path) -> None:
    """Silver L2, order events, a forecast grid and Binance trades for each date; Gold rows whose
    features come from ``quote_features`` (the real-data agreement is checked on every run)."""
    layout = HyperliquidLakeLayout(root)
    rng = np.random.default_rng(5)
    s3 = quote_columns("s3")
    binance_dir = binance / "SOLUSDT"
    binance_dir.mkdir(parents=True)
    for k, date in enumerate([shift_date(DATES[0], -1), *DATES]):
        t0 = float(day_start_ms(date))
        trades = np.sort(rng.uniform(t0, t0 + 300_000, 2_000)).astype(np.int64)  # the book spans the first minutes
        px = 100.0 + np.cumsum(rng.normal(0, 0.02, trades.size))
        csv = "".join(f"{i},{p:.4f},1,{i},{i},{t},false\n" for i, (t, p) in enumerate(zip(trades, px, strict=True)))
        with zipfile.ZipFile(binance_dir / f"SOLUSDT-aggTrades-{date[:4]}-{date[4:6]}-{date[6:]}.zip", "w") as zf:
            zf.writestr("x.csv", csv)
        if k == 0:
            continue
        ts, book = _book(400, seed=10 + k, t0_ms=t0 + 1_000.0)
        ts_ns = np.rint(ts * 1e6).astype(np.int64) + 123  # sub-ms block times, as Silver's ts_ns
        path = layout.silver_l2_book_path("SOL", date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"coin": ["SOL"] * ts.size, "ts_ms": ts.astype(np.int64), "ts_ns": ts_ns, **book}), path)
        ev_ts = np.sort(rng.uniform(t0, t0 + 300_000, 300))
        events = {
            "ts_ms": ev_ts,
            "kind": rng.choice(["ioc_unfilled", "liquidation", "other"], ev_ts.size),
            "is_ask": rng.random(ev_ts.size) < 0.5,
            "sz": rng.uniform(0, 5, ev_ts.size),
            "orig_sz": rng.uniform(5, 10, ev_ts.size),
            "opposite_best_px": np.full(ev_ts.size, 100.0),
            "marketable_at_block_start": rng.random(ev_ts.size) < 0.7,
        }
        path = layout.silver_order_events_path("SOL", date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(events), path)
        grid_ts = np.arange(t0, t0 + 86_400_000, 10_000.0)
        grid = {c: rng.random(grid_ts.size) for c in GRID_INPUTS if c != "ts_ms"}
        path = forced_grid_path(root, "SOL", date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"ts_ms": grid_ts, **grid, "hazard_scaled": np.ones(grid_ts.size, dtype=bool)}), path)

    for date in DATES:
        inputs = load_day_inputs(root, binance, "SOL", date)
        fills = np.sort(rng.uniform(inputs.l2_ts_ms[1], inputs.l2_ts_ms[-1], 200))
        side = np.where(rng.random(fills.size) < 0.5, 1.0, -1.0)
        x = quote_features(inputs, fills, side, s3)
        j = np.searchsorted(inputs.l2_ts_ms, fills, side="left") - 1
        table: dict[str, npt.NDArray[Any]] = {c: x[:, k] for k, c in enumerate(s3) if c not in ("maker_side", "l2_microprice_offset_bps")}
        book_mid = pq.read_table(layout.silver_l2_book_path("SOL", date), columns=["mid", "microprice"])
        table["l2_mid"] = book_mid["mid"].to_numpy()[j]
        table["l2_microprice"] = book_mid["microprice"].to_numpy()[j]
        table |= {
            "ts_ms": fills,
            "maker_side": side,
            "sz": np.ones(fills.size),
            "markout_bps_1s": -3.0 * x[:, s3.index("l2_ofi_1s")] + rng.normal(size=fills.size),
        }
        table["toxic_1s"] = table["markout_bps_1s"] < -2.0
        path = layout.gold_training_path("SOL", date)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(table), path)


def test_cli_writes_signals_for_the_test_days(tmp_path: Path) -> None:
    root, binance, out = tmp_path / "lake", tmp_path / "binance", tmp_path / "signals"
    _write_lake(root, binance)
    report_path = tmp_path / "report.json"
    argv = ["--coin", "SOL", "--dates", "20251201..20251209", "--lake-root", str(root), "--binance-dir", str(binance)]
    argv += ["--out-dir", str(out), "--report", str(report_path), "--n-estimators", "5"]
    assert quote_signals.main(argv) == 0
    report = json.loads(report_path.read_text())
    assert [d["date"] for d in report["days"]] == ["20251208", "20251209"]  # 7 training days first
    assert all(d["gold_check"]["passed"] for d in report["days"])
    for name in ("s2", "s3"):
        model = report["models"][name]
        assert [f["fold_id"] for f in model["folds"]] == [1, 2] and model["rows_tested"] == 400
        assert "sz" in model["dropped_fill_time_columns"] and "sz" not in model["feature_columns"]
    table = pq.read_table(quote_signals_path(out, "SOL", "20251208"))
    inputs = load_day_inputs(root, binance, "SOL", "20251208")
    np.testing.assert_array_equal(table["ts_ns"].to_numpy(), inputs.quote_rows()[0])
    q = np.column_stack([table[f"s3_q{p}_bid"].to_numpy() for p in (10, 50, 90)])
    scored = ~np.isnan(q[:, 0])
    assert scored.mean() > 0.9 and np.all(np.diff(q[scored], axis=1) >= 0)
    # one day on its own gets the same fold, seed and signals as in the full run
    one = tmp_path / "one"
    assert (
        quote_signals.main(
            [*argv[:-6], "--out-dir", str(one), "--report", str(tmp_path / "one.json"), "--n-estimators", "5", "--score-dates", "20251209"]
        )
        == 0
    )
    assert not quote_signals_path(one, "SOL", "20251208").exists()
    assert pq.read_table(quote_signals_path(one, "SOL", "20251209")).equals(pq.read_table(quote_signals_path(out, "SOL", "20251209")))
    # and one model per run adds up to both
    split = tmp_path / "split"
    for name in ("s3", "s2"):
        quote_signals.main(
            [*argv[:-6], "--out-dir", str(split), "--report", str(tmp_path / f"{name}.json"), "--n-estimators", "5", "--models", name]
        )
    both = pq.read_table(quote_signals_path(out, "SOL", "20251208"))
    assert pq.read_table(quote_signals_path(split, "SOL", "20251208")).select(both.column_names).equals(both)


def test_cli_stops_when_gold_disagrees(tmp_path: Path) -> None:
    root, binance = tmp_path / "lake", tmp_path / "binance"
    _write_lake(root, binance)
    path = HyperliquidLakeLayout(root).gold_training_path("SOL", "20251208")
    table = pq.read_table(path)
    table = table.set_column(table.column_names.index("l2_ofi_1s"), "l2_ofi_1s", pa.array(table["l2_ofi_1s"].to_numpy() + 1.0))
    pq.write_table(table, path)
    argv = ["--coin", "SOL", "--dates", "20251201..20251209", "--lake-root", str(root), "--binance-dir", str(binance)]
    with pytest.raises(SystemExit, match="l2_ofi_1s"):
        quote_signals.main([*argv, "--out-dir", str(tmp_path / "s"), "--report", str(tmp_path / "r.json"), "--n-estimators", "5"])
