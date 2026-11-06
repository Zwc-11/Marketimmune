"""Point-in-time feature join for Gold training rows, and the feature sets (ladder rungs).

Each fill gets the latest L2 book row (and asset context) strictly before it, plus order-flow
imbalance (OFI) over 1/5/10 s windows ending at that book row. Inputs and outputs are row
dicts (the lake writers' format); the work is column-wise: OFI windows are prefix-sum
differences located with ``searchsorted``, and the as-of join is one ``searchsorted`` per coin.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from marketimmune.features.cex_gap import CEX_FEATURE_COLUMNS
from marketimmune.features.forced_flow_features import FORECAST_FEATURE_COLUMNS
from marketimmune.features.order_events import FORCED_FEATURE_COLUMNS, RACE_FEATURE_COLUMNS
from marketimmune.features.trade_state import FEE_COLUMNS, FEE_PLACEBO_COLUMNS, TRADE_STATE_COLUMNS
from marketimmune.features.wallet_toxicity import WALLET_FEATURE_COLUMNS
from marketimmune.labels.leakage import LookaheadReport, check_no_lookahead

L2_FEATURES = (
    "mid",
    "spread_bps",
    "microprice",
    "top_imbalance",
    "ofi_event",
    "ofi_1s",
    "ofi_5s",
    "ofi_10s",
)
ASSET_FEATURES = ("basis_bps", "funding", "open_interest", "premium")
HYPERLIQUID_OFI_COLUMNS = ("l2_ofi_event", "l2_ofi_1s", "l2_ofi_5s", "l2_ofi_10s")
HYPERLIQUID_MARKOUT_FEATURE_COLUMNS = (
    "sz",
    "maker_side",
    "fee_bps",
    "l2_spread_bps",
    "l2_microprice_offset_bps",
    "l2_top_imbalance",
    *HYPERLIQUID_OFI_COLUMNS,
    "fill_vs_mid_bps",
    "asset_basis_bps",
    "asset_funding",
    "asset_open_interest",
    "asset_premium",
)
# v3 rung L0: v2's features with the fixes applied. ``fill_vs_mid_bps`` is gone
# (fix L2: with the label anchored at the pre-fill mid it only restated the
# half-spread), and the fee is the maker's own, written to Gold (fix B1), which
# the maker knows before it quotes. ``HYPERLIQUID_MARKOUT_FEATURE_COLUMNS`` stays
# as the v2 list the deployed web model and the dashboard scorer were built on.
MARKOUT_L0_FEATURE_COLUMNS = (
    "sz",
    "maker_side",
    "maker_fee_bps",
    "l2_spread_bps",
    "l2_microprice_offset_bps",
    "l2_top_imbalance",
    *HYPERLIQUID_OFI_COLUMNS,
    "asset_basis_bps",
    "asset_funding",
    "asset_open_interest",
    "asset_premium",
)
# L0 for sources with no asset contexts and no fees (the Albers December 2025 L4 set).
MARKOUT_L0_BOOK_FEATURE_COLUMNS = (
    "sz",
    "maker_side",
    "l2_spread_bps",
    "l2_microprice_offset_bps",
    "l2_top_imbalance",
    *HYPERLIQUID_OFI_COLUMNS,
)
FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "v2": HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    "l0": MARKOUT_L0_FEATURE_COLUMNS,
    "l0_book": MARKOUT_L0_BOOK_FEATURE_COLUMNS,
    # Rung L1: L0 plus the CEX-gap control (marketimmune.features.cex_gap).
    "l1": (*MARKOUT_L0_FEATURE_COLUMNS, *CEX_FEATURE_COLUMNS),
    "l1_book": (*MARKOUT_L0_BOOK_FEATURE_COLUMNS, *CEX_FEATURE_COLUMNS),
}
# The rest of the ladder, each rung adding to the one before (v3 Integration):
# L2 taker-wallet scores, L3a speed/race features, L3b forced flow, L3 both.
# On the pre-fee Albers month, L3a is the lost-race count, and L3b is realised
# forced flow (marketimmune.features.order_events) plus the position-book
# forecast (marketimmune.features.forced_flow_features); ``l3b_realised`` keeps
# only the realised part, to show what the forecast adds.
_FORCED = (*FORCED_FEATURE_COLUMNS, *FORECAST_FEATURE_COLUMNS)
for _base in ("l1", "l1_book"):
    _suffix = _base[2:]
    _l2 = (*FEATURE_SETS[_base], *WALLET_FEATURE_COLUMNS)
    FEATURE_SETS[f"l2{_suffix}"] = _l2
    FEATURE_SETS[f"l3a{_suffix}"] = (*_l2, *RACE_FEATURE_COLUMNS)
    FEATURE_SETS[f"l3b{_suffix}"] = (*_l2, *_FORCED)
    FEATURE_SETS[f"l3b_realised{_suffix}"] = (*_l2, *FORCED_FEATURE_COLUMNS)
    FEATURE_SETS[f"l3{_suffix}"] = (*_l2, *RACE_FEATURE_COLUMNS, *_FORCED)
# Placebo for L3a: the lost races aimed at the *other* side only.
FEATURE_SETS["l3a_placebo_book"] = (
    *FEATURE_SETS["l2_book"],
    *(c for c in RACE_FEATURE_COLUMNS if "_opp_" in c),
)
# The 2026 A1 ladder (docs/preregistration/a1-speed-bids-2026.md): no order book, so the state
# rung comes from trades (features.trade_state); L3 adds the priority fees paid on the side that
# hits the maker, the placebo the fees on the other side only.
FEATURE_SETS["l0_trade"] = ("sz", "maker_side", *TRADE_STATE_COLUMNS)
FEATURE_SETS["l1_trade"] = (*FEATURE_SETS["l0_trade"], *CEX_FEATURE_COLUMNS)
FEATURE_SETS["l2_trade"] = (*FEATURE_SETS["l1_trade"], *WALLET_FEATURE_COLUMNS)
FEATURE_SETS["l3_fee"] = (*FEATURE_SETS["l2_trade"], *FEE_COLUMNS)
FEATURE_SETS["l3_fee_placebo"] = (*FEATURE_SETS["l2_trade"], *FEE_PLACEBO_COLUMNS)
OFI_WINDOWS_MS = {
    "ofi_1s": 1_000.0,
    "ofi_5s": 5_000.0,
    "ofi_10s": 10_000.0,
}
# A jump of more than this between book rows is a Silver book reset (the L4 rebuild restarts
# after an archive gap, e.g. 2025-12-12 17:40:43 -> 18:26:01 UTC); same bound as the label's
# stale-mid rule.
STALE_BOOK_MS = 30_000.0
TRAINING_ROW_FEATURE_COLUMNS = (
    "feature_ts_ms",
    *(f"l2_{name}" for name in L2_FEATURES),
    *(f"asset_{name}" for name in ASSET_FEATURES),
)
# Longest feature window is 10 s of OFI; asset contexts can be minutes apart.
LOOKAHEAD_CHECK_LOOKBACK_MS = 300_000.0
_BOOK_COLUMNS = ("bid_px", "bid_sz", "ask_px", "ask_sz")
_L2_ROW_FEATURES = ("mid", "spread_bps", "microprice", "top_imbalance")
# What the join reads from a Silver L2 row; anything else (depth levels, ts_ns) stays on disk.
L2_JOIN_COLUMNS = ("coin", "ts_ms", *_BOOK_COLUMNS, *_L2_ROW_FEATURES)
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class _CoinIndex:
    """Rows of one coin sorted by time (stable), their times, and derived per-row columns."""

    ts_ms: FloatArray
    rows: list[Mapping[str, Any]]
    columns: dict[str, list[float]]

    def latest_before(self, ts_ms: FloatArray) -> npt.NDArray[np.intp]:
        """Index of the last row with ``ts < ts_ms``, -1 when none (fix L1: a row in the
        fill's own millisecond can already show the fill)."""
        return np.searchsorted(self.ts_ms, ts_ms, side="left") - 1


def build_hyperliquid_training_rows(
    label_rows: Sequence[Mapping[str, Any]],
    l2_rows: Sequence[Mapping[str, Any]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Label rows joined to features known strictly before each fill, in ``label_rows`` order.

    A fill with no earlier L2 row is skipped. A fill with no earlier asset context gets no
    ``asset_*`` values (missing, so the trainer drops it), never a later one. Funding, basis
    and open interest change through the day, so an asset row without ``ts_ms`` is an error:
    it cannot be placed before or after any fill.
    """
    if not label_rows:
        return []
    untimed = [row.get("coin") for row in asset_ctx_rows if row.get("ts_ms") is None]
    if untimed:
        raise ValueError(
            f"{len(untimed)} asset context row(s) without ts_ms (coins {sorted(set(map(str, untimed)))[:5]}); dynamic context needs its time"
        )
    l2_index = {coin: _with_ofi(index) for coin, index in _coin_index(l2_rows).items()}
    asset_index = _coin_index(asset_ctx_rows)
    coins = [str(label["coin"]) for label in label_rows]
    fill_ts = np.fromiter((label["ts_ms"] for label in label_rows), dtype=np.float64, count=len(label_rows))
    l2_pos = _asof_positions(coins, fill_ts, l2_index)
    asset_pos = _asof_positions(coins, fill_ts, asset_index)
    out: list[dict[str, Any]] = []
    for i, label in enumerate(label_rows):
        coin, l2_i, asset_i = coins[i], int(l2_pos[i]), int(asset_pos[i])
        if l2_i < 0:
            continue
        l2, row = l2_index[coin], dict(label)
        row["feature_ts_ms"] = float(l2.ts_ms[l2_i])
        for name in _L2_ROW_FEATURES:
            row[f"l2_{name}"] = float(l2.rows[l2_i][name])
        for name, values in l2.columns.items():
            row[f"l2_{name}"] = values[l2_i]
        if asset_i >= 0:
            asset_ctx = asset_index[coin].rows[asset_i]
            row["feature_ts_ms"] = max(row["feature_ts_ms"], float(asset_index[coin].ts_ms[asset_i]))
            for name in ASSET_FEATURES:
                if asset_ctx.get(name) is not None:
                    row[f"asset_{name}"] = float(asset_ctx[name])
        out.append(row)
    return out


def verify_training_rows_no_lookahead(
    label_rows: Sequence[Mapping[str, Any]],
    l2_rows: Sequence[Mapping[str, Any]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] = (),
    *,
    sample: int = 200,
    seed: int = 0,
) -> LookaheadReport:
    """Fix B3: rebuild sampled rows with every source row at or after the fill deleted.

    Passing means the join, OFI windows and as-of selection read nothing from the fill's own
    millisecond or later. The report sits beside each Gold training partition and is the
    only thing that lets a model report say ``leakage_safe``.
    """
    return check_no_lookahead(
        build_hyperliquid_training_rows,
        label_rows,
        (l2_rows, asset_ctx_rows),
        columns=TRAINING_ROW_FEATURE_COLUMNS,
        sample=sample,
        seed=seed,
        lookback_ms=LOOKAHEAD_CHECK_LOOKBACK_MS,
    )


def l2_rows_with_ofi(l2_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copies of the L2 rows with ``ofi_event`` and the OFI windows, per coin in time order."""
    out: list[dict[str, Any]] = []
    for index in _coin_index(l2_rows).values():
        ofi = _ofi_columns(index)
        for pos, row in enumerate(index.rows):
            out.append({**row, **{name: values[pos] for name, values in ofi.items()}})
    return out


def prepare_markout_feature_row(
    row: Mapping[str, Any],
    columns: Sequence[str] = HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
) -> dict[str, float]:
    """One Gold row as the deployed v2 model's feature vector (``frontend/src/lib/features.ts``
    mirrors it). Missing fees and OFI count as 0."""
    required = (
        "px",
        "sz",
        "maker_side",
        "l2_mid",
        "l2_spread_bps",
        "l2_microprice",
        "l2_top_imbalance",
        "asset_basis_bps",
        "asset_funding",
        "asset_open_interest",
        "asset_premium",
    )
    missing = [name for name in required if row.get(name) is None]
    if missing:
        suffix = "" if len(missing) <= 5 else f", +{len(missing) - 5} more"
        raise ValueError(f"Gold row missing markout scoring features: {', '.join(missing[:5])}{suffix}")
    mid = float(row["l2_mid"])
    if mid <= 0.0:
        raise ValueError("Gold row l2_mid must be positive for bps feature derivation")
    maker_side = float(row["maker_side"])
    features = {
        "sz": float(row["sz"]),
        "maker_side": maker_side,
        "fee_bps": float(row.get("fee_bps") or 0.0),
        "maker_fee_bps": float(row.get("maker_fee_bps") or 0.0),
        "l2_spread_bps": float(row["l2_spread_bps"]),
        "l2_microprice_offset_bps": (float(row["l2_microprice"]) - mid) / mid * 10_000.0,
        "l2_top_imbalance": float(row["l2_top_imbalance"]),
        "fill_vs_mid_bps": (float(row["px"]) - mid) / mid * 10_000.0 * maker_side,
        "asset_basis_bps": float(row["asset_basis_bps"]),
        "asset_funding": float(row["asset_funding"]),
        "asset_open_interest": float(row["asset_open_interest"]),
        "asset_premium": float(row["asset_premium"]),
        **{column: float(row.get(column) or 0.0) for column in HYPERLIQUID_OFI_COLUMNS},
    }
    return {name: features[name] for name in columns}


def _coin_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, _CoinIndex]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("coin")), []).append(row)
    index: dict[str, _CoinIndex] = {}
    for coin, coin_rows in grouped.items():
        times = _column(coin_rows, "ts_ms")
        order = np.argsort(times, kind="stable")
        index[coin] = _CoinIndex(ts_ms=times[order], rows=[coin_rows[i] for i in order.tolist()], columns={})
    return index


def _with_ofi(index: _CoinIndex) -> _CoinIndex:
    return _CoinIndex(index.ts_ms, index.rows, _ofi_columns(index))


def _ofi_columns(index: _CoinIndex) -> dict[str, list[float]]:
    columns = ofi_columns(index.ts_ms, {name: _column(index.rows, name) for name in _BOOK_COLUMNS})
    return {name: values.tolist() for name, values in columns.items()}


def ofi_columns(ts_ms: FloatArray, book: Mapping[str, FloatArray]) -> dict[str, FloatArray]:
    """``ofi_event`` per row (time order) and its sums over each window ``[t - span, t]``, from
    the top-of-book columns ``bid_px``, ``bid_sz``, ``ask_px``, ``ask_sz``. Gold's join and the
    simulator's quote-time features (``marketimmune.sim.signals``) both use it.

    NOTE: after a book reset (a jump of more than ``STALE_BOOK_MS``) the first row has no
    previous book to difference against, like the first row of the data: its event is 0
    and no window reaches back across the jump. The prefix sum still runs over the raw
    events, so a window that does not touch a reset is bit-identical to one without.
    """
    events = _normalized_ofi_events(book)
    reset = np.concatenate(([False], np.diff(ts_ms) > STALE_BOOK_MS))
    floor = np.maximum.accumulate(np.where(reset, np.arange(1, ts_ms.size + 1), 0))
    prefix = np.concatenate(([0.0], np.cumsum(events)))
    upto = np.arange(1, ts_ms.size + 1)
    columns = {"ofi_event": np.where(reset, 0.0, events)}
    for name, span in OFI_WINDOWS_MS.items():
        start = np.maximum(np.searchsorted(ts_ms, ts_ms - span, side="left"), floor)
        columns[name] = prefix[upto] - prefix[start]
    return columns


def _asof_positions(coins: Sequence[str], fill_ts: FloatArray, index: Mapping[str, _CoinIndex]) -> npt.NDArray[np.intp]:
    positions = np.full(fill_ts.size, -1, dtype=np.intp)
    coin_array = np.asarray(coins, dtype=object)
    for coin, coin_index in index.items():
        mask = coin_array == coin
        if mask.any():
            positions[mask] = found = coin_index.latest_before(fill_ts[mask])
            assert np.all(coin_index.ts_ms[found[found >= 0]] < fill_ts[mask][found >= 0]), "look-ahead in the as-of join"
    return positions


def _normalized_ofi_events(book: Mapping[str, FloatArray]) -> FloatArray:
    """Top-of-book OFI between consecutive rows (bid/ask price-size pressure), divided by the
    sum of both rows' top sizes so it is comparable across coins; 0 for the first row."""
    bid_px, bid_sz = book["bid_px"], book["bid_sz"]
    ask_px, ask_sz = book["ask_px"], book["ask_sz"]
    events = np.zeros(bid_px.size, dtype=np.float64)
    if bid_px.size < 2:
        return events
    prev_bid_px, prev_bid_sz = bid_px[:-1], bid_sz[:-1]
    prev_ask_px, prev_ask_sz = ask_px[:-1], ask_sz[:-1]
    cur_bid_px, cur_bid_sz = bid_px[1:], bid_sz[1:]
    cur_ask_px, cur_ask_sz = ask_px[1:], ask_sz[1:]
    bid_pressure = np.where(cur_bid_px >= prev_bid_px, cur_bid_sz, 0.0) - np.where(cur_bid_px <= prev_bid_px, prev_bid_sz, 0.0)
    ask_pressure = np.where(cur_ask_px >= prev_ask_px, prev_ask_sz, 0.0) - np.where(cur_ask_px <= prev_ask_px, cur_ask_sz, 0.0)
    denominator = prev_bid_sz + prev_ask_sz + cur_bid_sz + cur_ask_sz
    raw = bid_pressure + ask_pressure
    safe = np.where(denominator > 0.0, denominator, 1.0)
    events[1:] = np.where(denominator > 0.0, raw / safe, 0.0)
    return events


def _column(rows: Sequence[Mapping[str, Any]], name: str) -> FloatArray:
    return np.fromiter((row[name] for row in rows), dtype=np.float64, count=len(rows))
