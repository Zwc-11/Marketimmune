"""Tests for forecaster v2 (node fills + Hydromancer snapshots)."""

from __future__ import annotations

import json
import math
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl

from marketimmune.cli import forced_v2
from marketimmune.forced.positions import WalletState
from marketimmune.utils import parse_date_spec

DATES = list(parse_date_spec("20251215..20251219"))
SNAP_DATE, SNAP_K = "20251216", 100


def _write_lake(tmp_path: Path) -> list[str]:
    """Five days of SOL trades every 200 s: two makers, six takers, and each day one wallet
    that opens a long and is market-liquidated 2.5% lower. A snapshot on Dec 16 at trade 100
    lists every open position."""
    rng = np.random.default_rng(1)
    node, hydro, binance = tmp_path / "node" / "SOL", tmp_path / "hydro" / "SOL", tmp_path / "binance" / "SOLUSDT"
    for d in (node, hydro, binance):
        d.mkdir(parents=True)
    pos: dict[str, float] = {}
    entry: dict[str, float] = {}
    px, block = 100.0, 1_000
    for date in DATES:
        start = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC)
        rows: list[dict[str, Any]] = []

        def leg(user: str, side: str, sz: float, p: float, t: datetime, crossed: bool, liq: str | None = None) -> None:
            s0 = pos.get(user, 0.0)
            new = s0 + (sz if side == "B" else -sz)
            if abs(s0) < 1e-12 or (s0 > 0) != (new > 0):
                entry[user] = p
            elif abs(new) > abs(s0):
                entry[user] = (entry[user] * abs(s0) + p * sz) / abs(new)
            rows.append({
                "coin": "SOL", "block_number": block, "block_time": t, "time_ms": int(t.timestamp() * 1000), "tid": block, "oid": block * 2 + crossed,
                "user": user, "side": side, "px": p, "sz": sz, "start_position": s0, "crossed": crossed, "liquidated_user": liq,
                "liquidation_mark_px": p if liq else None, "liquidation_method": "market" if liq else None,
            })  # fmt: skip
            pos[user] = new

        for k in range(420):
            t = start + timedelta(seconds=60 + 200 * k)
            px = round(px * math.exp(rng.normal(0, 0.002)), 2)
            taker, maker = f"t{rng.integers(0, 6)}", f"m{rng.integers(0, 2)}"
            side = "B" if rng.random() < 0.5 else "A"
            if k == 30:  # the day's liquidated wallet opens
                taker, side = f"L{date}", "B"
            if k == 60:
                lw = f"L{date}"
                p = round(entry[lw] * 0.975, 2)
                leg(lw, "A", 5.0, p, t, True, lw)
                leg(maker, "B", 5.0, p, t, False, lw)
            else:
                sz = 5.0 if k == 30 else 1.0
                leg(taker, side, sz, px, t, True)
                leg(maker, "A" if side == "B" else "B", sz, px, t, False)
            if date == SNAP_DATE and k == SNAP_K:
                users = [u for u, s in pos.items() if abs(s) > 1e-12]
                sizes = np.array([pos[u] for u in users])
                liq = [entry[u] * (1 - 0.05 * np.sign(s)) if i % 3 else math.nan for i, (u, s) in enumerate(zip(users, sizes, strict=True))]
                pd.DataFrame({
                    "user": users, "size": sizes, "notional": np.abs(sizes) * px, "entry_price": [entry[u] for u in users],
                    "liquidation_price": liq, "leverage_type": ["isolated" if i % 2 else "cross" for i in range(len(users))],
                    "leverage": 10, "account_value": np.abs(sizes) * px / 10, "snapshot_block": block, "snapshot_ts_ms": int(t.timestamp() * 1000),
                }).to_parquet(hydro / f"SOL-{date}.parquet")  # fmt: skip
            block += 1
        pl.DataFrame(rows, infer_schema_length=None).write_parquet(node / f"SOL-{date}.parquet")
    for date in ("20251214", *DATES):
        day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=UTC)
        ms = [int((day + timedelta(seconds=s)).timestamp() * 1000) for s in range(0, 86_400, 300)]
        csv = "".join(f"{i},{100 + 0.01 * (i % 7):.2f},1,{i},{i},{m},false\n" for i, m in enumerate(ms))
        with zipfile.ZipFile(binance / f"SOLUSDT-aggTrades-{date[:4]}-{date[4:6]}-{date[6:]}.zip", "w") as zf:
            zf.writestr("x.csv", csv)
    return [
        "--coin", "SOL", "--dates", f"{DATES[0]}..{DATES[-1]}", "--grid-s", "600", "--node-dir", str(tmp_path / "node"),
        "--hydro-dir", str(tmp_path / "hydro"), "--binance-dir", str(tmp_path / "binance"), "--out-dir", str(tmp_path / "out"),
    ]  # fmt: skip


def test_runs_resumes_and_reports(tmp_path: Path) -> None:
    argv = _write_lake(tmp_path)
    assert forced_v2.main([*argv, "--max-days", "2"]) == 0
    state = forced_v2.load_state(forced_v2.state_path(tmp_path / "out", "SOL"))
    assert state.dates_done == DATES[:2] and state.v2_book is not None and state.sample
    assert forced_v2.main(argv) == 0  # resumes at Dec 17
    out = tmp_path / "out" / "SOL"
    # v1 from the second date; v2a and v2 from the snapshot, which is on the second date too
    for v in ("v1", "v2a", "v2"):
        assert sorted(p.name.split("-")[1][:8] for p in out.glob(f"SOL-*.{v}.parquet")) == DATES[1:]
    v2 = pd.read_parquet(out / f"SOL-{SNAP_DATE}.v2.parquet")
    snap_ms = pd.read_parquet(tmp_path / "hydro" / "SOL" / f"SOL-{SNAP_DATE}.parquet")["snapshot_ts_ms"].iloc[0]
    assert v2["ts_ms"].min() > snap_ms and v2["exact_share"].iloc[0] == 1.0
    assert (pd.read_parquet(out / f"SOL-{SNAP_DATE}.v1.parquet")["exact_share"] == 0.0).all()
    report = tmp_path / "r.json"
    assert forced_v2.main([*argv, "--report", str(report)]) == 0
    res = json.loads(report.read_text())
    assert {"v1", "v2a", "v2", "v1_on_v2_dates", "v2_vs_v1", "v2a_vs_v1", "v2_vs_v2a", "hazard_fit"} <= set(res)
    assert res["v2_vs_v1"]["common_dates"] == DATES[2:]


def test_grid_book_resets_and_expires_crossed_prices() -> None:
    rows = forced_v2._cat(
        [
            {"ts": np.array([100.0, 500.0, 500.0]), "wallet": np.array(["a", "a", "b"], dtype=object), "size": np.array([2.0, 3.0, -1.0]),
             "entry": np.array([100.0, 100.0, 100.0]), "liq_a": np.array([np.nan, 90.0, np.inf]), "liq_b": np.array([np.nan, 90.0, np.inf]),
             "kind": np.array([forced_v2.FILL, forced_v2.RESET, forced_v2.RESET], dtype=np.int8)},
        ]
    )  # fmt: skip
    gb = forced_v2.GridBook(forced_v2.BookRows({"a": WalletState(1.0, 100.0)}, {"a": 95.0}, {"a": 95.0}, rows))
    gb.advance_to(50.0, 99.0)
    book, total, exact = gb.book(99.0, "liq_b")
    assert book.size.tolist() == [1.0] and book.liq is not None and book.liq.tolist() == [95.0] and exact == 1.0 and total == 99.0
    gb.advance_to(200.0, 99.0)  # a traded: its price is the prior's until the snapshot
    assert math.isnan(gb.book(99.0, "liq_a")[0].liq[0])  # type: ignore[index]
    gb.advance_to(600.0, 89.0)  # after the reset; the mark is already past a's 90
    assert gb.book(89.0, "liq_b")[0].liq.tolist() == [90.0, math.inf]  # type: ignore[union-attr]
    gb.advance_to(610.0, 89.0)  # still past one step later and not liquidated: stale
    liq = gb.book(89.0, "liq_b")[0].liq
    assert liq is not None and math.isnan(liq[0]) and liq[1] == math.inf
    assert gb.expired_usd["liq_b"] == 3.0 * 89.0
