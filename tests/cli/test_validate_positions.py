from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest

from marketimmune.cli.validate_positions import compare_snapshot, distance_notional, forced_vs_snapshots


def _hydro(rows: list[tuple[str, float, float, float | None]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["user", "hm_size", "hm_entry", "hm_liq"])


def test_distance_buckets() -> None:
    out = distance_notional(np.array([0.005, 0.03, 0.5]), np.array([1.0, 1.0, 2.0]))
    assert out["0%-1%"] == 0.25 and out["2%-5%"] == 0.25 and out[">20%"] == 0.5 and sum(out.values()) == pytest.approx(1.0)


def test_compare_snapshot_counts_matches_and_prices() -> None:
    book = pd.DataFrame({"wallet": ["a", "b", "c", "z"], "size": [10.0, -5.0, 2.0, 0.0], "entry": [100.0, 102.0, np.nan, np.nan]})
    hydro = _hydro([("a", 10.0, 100.0, 88.0), ("b", -5.0, 102.03, 150.0), ("c", 3.0, 101.0, 80.0), ("d", 1.0, 100.0, 50.0)])
    deltas = np.array([0.01, 0.02, 0.03])  # the prior: 2% for a position not yet underwater
    r = compare_snapshot(book, hydro, deltas, mark=100.0, coin="SOL")
    assert (r["exact"], r["size_mismatch"], r["hydromancer_only_never_seen"], r["book_only"]) == (2, 1, 1, 0)
    assert r["exact_notional_share"] == pytest.approx(15 / 19) and r["hydromancer_only_never_seen_notional_share"] == pytest.approx(1 / 19)
    assert r["entry"]["known"] == 2 and r["entry"]["within_1bp"] == 0.5  # b is 3 bp off
    liq = r["liquidation"]
    # prior: a long at 100 -> 98; b short at 102 (excursion 0) -> 104.04; Hydromancer 88 and 150
    assert liq["positions"] == 2 and liq["abs_error_prior_pct_of_mark"]["p50"] == pytest.approx((10 + 45.96) / 2)
    assert liq["notional_by_distance_prior"]["2%-5%"] == pytest.approx(1.0)
    hm = liq["notional_by_distance_hydromancer"]
    assert hm["10%-20%"] == pytest.approx(10 / 15) and hm[">20%"] == pytest.approx(5 / 15)


def test_forced_fills_against_the_latest_snapshot(tmp_path: Path) -> None:
    node = tmp_path / "SOL"
    node.mkdir()
    pl.DataFrame(
        {
            "time_ms": [2_000, 2_000, 5_000], "user": ["a", "m", "b"], "liquidated_user": ["a", "a", "b"], "crossed": [True, False, True],
            "liquidation_mark_px": [89.1, 89.1, 151.5], "liquidation_method": ["market", "market", "backstop"], "start_position": [10.0, 0.0, -5.0],
        }
    ).write_parquet(node / "SOL-20251215.parquet")  # fmt: skip
    snaps = {1_000: _hydro([("a", 10.0, 100.0, 90.0), ("b", -5.0, 102.0, 150.0)])}
    r = forced_vs_snapshots(tmp_path, "SOL", ["20251215"], snaps)
    assert r["events"] == 2 and r["with_snapshot_liq"] == 2
    assert r["market"]["overshoot"]["p50"] == pytest.approx(0.01) and r["backstop"]["overshoot"]["p50"] == pytest.approx(0.01)
