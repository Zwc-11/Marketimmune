"""Tests for the lost-race (L3a) and forced-flow (L3b) features."""

from __future__ import annotations

import numpy as np
import pytest

from marketimmune.features.order_events import (
    FORCED_FEATURE_COLUMNS,
    RACE_FEATURE_COLUMNS,
    order_event_features,
    verify_order_event_features_no_lookahead,
)


def _events() -> dict[str, np.ndarray]:
    # ts, kind, is_ask, sz (left), orig_sz, opposite best, marketable
    rows = [
        (900.0, "ioc_unfilled", True, 2.0, 2.0, 100.0, True),    # sell aimed at bids
        (950.0, "ioc_unfilled", True, 1.0, 1.0, 100.0, False),   # never marketable
        (980.0, "ioc_unfilled", False, 3.0, 3.0, 101.0, True),   # buy aimed at asks
        (1000.0, "ioc_unfilled", True, 5.0, 5.0, 100.0, True),   # fill's own block: excluded
        (400.0, "liquidation", True, 0.0, 4.0, 99.0, True),      # forced sell into bids
        (990.0, "liquidation", False, 1.0, 3.0, 102.0, True),    # forced buy, 2 filled
    ]
    names = ("ts_ms", "kind", "is_ask", "sz", "orig_sz", "opposite_best_px",
             "marketable_at_block_start")
    return {n: np.array([r[i] for r in rows], dtype=object if n == "kind" else None)
            for i, n in enumerate(names)}


def test_features_split_by_maker_side_and_exclude_the_fill_block() -> None:
    ev = _events()
    f = order_event_features([1000.0, 1000.0], [1.0, -1.0], ev)
    assert set(f) == set(RACE_FEATURE_COLUMNS) | set(FORCED_FEATURE_COLUMNS)
    # maker bid hit (+1): same side = sells aimed at bids
    assert f["race_lost_same_n_250ms"].tolist() == [1.0, 1.0]
    assert f["race_lost_same_notional_250ms"][0] == pytest.approx(200.0)
    assert f["race_lost_opp_notional_250ms"][0] == pytest.approx(303.0)
    assert f["race_lost_same_notional_250ms"][1] == pytest.approx(303.0)  # maker ask hit
    assert f["forced_same_notional_1000ms"].tolist() == pytest.approx([396.0, 204.0])
    assert f["forced_opp_notional_1000ms"].tolist() == pytest.approx([204.0, 396.0])
    early = order_event_features([300.0], [1.0], ev)
    assert all(v[0] == 0.0 for v in early.values())


def test_no_lookahead_check_passes() -> None:
    report = verify_order_event_features_no_lookahead(
        [500.0, 1000.0, 1200.0], [1.0, -1.0, 1.0], _events()
    )
    assert report["passed"] is True and report["n_checked"] == 3
