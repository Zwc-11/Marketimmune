"""Point-in-time Hyperliquid feature joins for markout training rows.

The row-dict API is what the lake writers and tests consume, but the work is done
column-wise: OFI windows are prefix-sum differences located with ``searchsorted``,
and the as-of join resolves every fill's latest prior L2 / asset row in one
vectorized ``searchsorted`` per coin. The only per-row Python left is building the
output dicts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import numpy.typing as npt

from marketimmune.labels.leakage import LeakageError, assert_as_of

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
OFI_WINDOWS_MS = {
    "ofi_1s": 1_000.0,
    "ofi_5s": 5_000.0,
    "ofi_10s": 10_000.0,
}
_BOOK_COLUMNS = ("bid_px", "bid_sz", "ask_px", "ask_sz")
FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class _CoinIndex:
    """Rows of one coin sorted by time, with the timestamps as an array."""

    ts_ms: FloatArray
    rows: list[Mapping[str, Any]]

    def latest_at_or_before(self, ts_ms: FloatArray) -> npt.NDArray[np.intp]:
        """Index of the last row with ``ts <= ts_ms`` (``-1`` when none)."""
        return np.searchsorted(self.ts_ms, ts_ms, side="right") - 1


def training_row_from_asof(
    label_row: Mapping[str, Any],
    l2_row: Mapping[str, Any],
    asset_ctx_row: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge one label row with already-selected as-of feature rows.

    ``l2_row`` must be timestamped and at or before the fill. ``asset_ctx_row`` may
    be timestamped; if it has no ``ts_ms`` it is treated as static daily context.
    """
    fill_ts_ms = _as_float(label_row["ts_ms"])
    feature_ts_ms = [_as_float(l2_row["ts_ms"])]
    if asset_ctx_row is not None and "ts_ms" in asset_ctx_row:
        feature_ts_ms.append(_as_float(asset_ctx_row["ts_ms"]))
    assert_as_of([ts / 1000.0 for ts in feature_ts_ms], fill_ts_ms / 1000.0)
    return _merge_row(label_row, l2_row, asset_ctx_row, max(feature_ts_ms))


def build_hyperliquid_training_rows(
    label_rows: Sequence[Mapping[str, Any]],
    l2_rows: Sequence[Mapping[str, Any]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build model-ready rows using only features known at or before each fill.

    Output order follows ``label_rows``; fills with no prior L2 snapshot are skipped.
    """
    if not label_rows:
        return []
    l2_index = _coin_index(l2_rows_with_ofi(l2_rows))
    asset_index = _coin_index([row for row in asset_ctx_rows if "ts_ms" in row])
    asset_static_latest = _latest_static_by_coin(asset_ctx_rows)

    coins = [str(label["coin"]) for label in label_rows]
    fill_ts = np.fromiter(
        (_as_float(label["ts_ms"]) for label in label_rows),
        dtype=np.float64,
        count=len(label_rows),
    )
    l2_pos = _asof_positions(coins, fill_ts, l2_index)
    asset_pos = _asof_positions(coins, fill_ts, asset_index)
    _assert_point_in_time(coins, fill_ts, l2_pos, l2_index)
    _assert_point_in_time(coins, fill_ts, asset_pos, asset_index)

    out: list[dict[str, Any]] = []
    for i, label in enumerate(label_rows):
        coin = coins[i]
        l2_i = int(l2_pos[i])
        if l2_i < 0:
            continue
        l2_row = l2_index[coin].rows[l2_i]
        feature_ts = float(l2_index[coin].ts_ms[l2_i])
        asset_i = int(asset_pos[i])
        asset_ctx: Mapping[str, Any] | None = None
        if asset_i >= 0:
            asset_ctx = asset_index[coin].rows[asset_i]
            feature_ts = max(feature_ts, float(asset_index[coin].ts_ms[asset_i]))
        elif coin not in asset_index:
            asset_ctx = asset_static_latest.get(coin)
        out.append(_merge_row(label, l2_row, asset_ctx, feature_ts))
    return out


def l2_rows_with_ofi(
    l2_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach snapshot-derived event OFI and rolling OFI windows to L2 rows.

    OFI is computed from consecutive top-of-book snapshots using the standard
    bid/ask price-size pressure formula. The event value is normalized by current
    plus previous top-of-book size so it is comparable across coins and regimes.
    Untimestamped rows pass through with zero OFI, ahead of the timed rows.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    out: list[dict[str, Any]] = []
    for row in l2_rows:
        if "ts_ms" not in row:
            out.append(_with_zero_ofi(row))
            continue
        grouped.setdefault(str(row.get("coin")), []).append(row)

    for rows in grouped.values():
        times = _column(rows, "ts_ms")
        order = np.argsort(times, kind="stable")
        times = times[order]
        book = {name: _column(rows, name)[order] for name in _BOOK_COLUMNS}
        events = _normalized_ofi_events(book)
        prefix = np.concatenate(([0.0], np.cumsum(events)))
        upto = np.arange(1, times.size + 1)
        windows = {
            name: (prefix[upto] - prefix[np.searchsorted(times, times - span, side="left")])
            for name, span in OFI_WINDOWS_MS.items()
        }
        event_list = events.tolist()
        window_lists = {name: values.tolist() for name, values in windows.items()}
        for pos, src in enumerate(order.tolist()):
            enriched = dict(rows[src])
            enriched["ofi_event"] = event_list[pos]
            for name, values in window_lists.items():
                enriched[name] = values[pos]
            out.append(enriched)
    return out


def prepare_markout_feature_row(row: Mapping[str, Any]) -> dict[str, float]:
    """Derive the deployable CatBoost feature vector from one Gold training row."""
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
    missing = [name for name in required if name not in row or row[name] is None]
    if missing:
        joined = ", ".join(missing[:5])
        suffix = "" if len(missing) <= 5 else f", +{len(missing) - 5} more"
        raise ValueError(f"Gold row missing markout scoring features: {joined}{suffix}")

    mid = _as_float(row["l2_mid"])
    if mid <= 0.0:
        raise ValueError("Gold row l2_mid must be positive for bps feature derivation")

    features = {
        "sz": _as_float(row["sz"]),
        "maker_side": _as_float(row["maker_side"]),
        "fee_bps": _as_float(row.get("fee_bps", 0.0) or 0.0),
        "l2_spread_bps": _as_float(row["l2_spread_bps"]),
        "l2_microprice_offset_bps": (_as_float(row["l2_microprice"]) - mid) / mid * 10_000.0,
        "l2_top_imbalance": _as_float(row["l2_top_imbalance"]),
        "fill_vs_mid_bps": (_as_float(row["px"]) - mid) / mid * 10_000.0
        * _as_float(row["maker_side"]),
        "asset_basis_bps": _as_float(row["asset_basis_bps"]),
        "asset_funding": _as_float(row["asset_funding"]),
        "asset_open_interest": _as_float(row["asset_open_interest"]),
        "asset_premium": _as_float(row["asset_premium"]),
    }
    for column in HYPERLIQUID_OFI_COLUMNS:
        features[column] = _as_float(row.get(column, 0.0) or 0.0)
    return {name: features[name] for name in HYPERLIQUID_MARKOUT_FEATURE_COLUMNS}


def _merge_row(
    label_row: Mapping[str, Any],
    l2_row: Mapping[str, Any],
    asset_ctx_row: Mapping[str, Any] | None,
    feature_ts_ms: float,
) -> dict[str, Any]:
    row = dict(label_row)
    row["feature_ts_ms"] = feature_ts_ms
    for name in L2_FEATURES:
        row[f"l2_{name}"] = _as_float(l2_row[name])
    if asset_ctx_row is not None:
        for name in ASSET_FEATURES:
            value = asset_ctx_row.get(name)
            if value is not None:
                row[f"asset_{name}"] = _as_float(value)
    return row


def _coin_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, _CoinIndex]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if "ts_ms" in row:
            grouped.setdefault(str(row.get("coin")), []).append(row)
    index: dict[str, _CoinIndex] = {}
    for coin, coin_rows in grouped.items():
        times = _column(coin_rows, "ts_ms")
        order = np.argsort(times, kind="stable")
        index[coin] = _CoinIndex(
            ts_ms=times[order],
            rows=[coin_rows[i] for i in order.tolist()],
        )
    return index


def _asof_positions(
    coins: Sequence[str],
    fill_ts: FloatArray,
    index: Mapping[str, _CoinIndex],
) -> npt.NDArray[np.intp]:
    positions = np.full(fill_ts.size, -1, dtype=np.intp)
    coin_array = np.asarray(coins, dtype=object)
    for coin, coin_index in index.items():
        mask = coin_array == coin
        if mask.any():
            positions[mask] = coin_index.latest_at_or_before(fill_ts[mask])
    return positions


def _assert_point_in_time(
    coins: Sequence[str],
    fill_ts: FloatArray,
    positions: npt.NDArray[np.intp],
    index: Mapping[str, _CoinIndex],
) -> None:
    """Vectorized form of ``assert_as_of`` over every resolved join."""
    coin_array = np.asarray(coins, dtype=object)
    for coin, coin_index in index.items():
        mask = (coin_array == coin) & (positions >= 0)
        if not mask.any():
            continue
        feature_ts = coin_index.ts_ms[positions[mask]]
        late = feature_ts > fill_ts[mask]
        if late.any():
            raise LeakageError(
                f"look-ahead: feature ts {feature_ts[late].max()} > fill ts "
                f"{fill_ts[mask][late].min()}"
            )


def _latest_static_by_coin(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if "ts_ms" not in row:
            latest[str(row.get("coin"))] = row
    return latest


def _normalized_ofi_events(book: Mapping[str, FloatArray]) -> FloatArray:
    bid_px, bid_sz = book["bid_px"], book["bid_sz"]
    ask_px, ask_sz = book["ask_px"], book["ask_sz"]
    events = np.zeros(bid_px.size, dtype=np.float64)
    if bid_px.size < 2:
        return events
    prev_bid_px, prev_bid_sz = bid_px[:-1], bid_sz[:-1]
    prev_ask_px, prev_ask_sz = ask_px[:-1], ask_sz[:-1]
    cur_bid_px, cur_bid_sz = bid_px[1:], bid_sz[1:]
    cur_ask_px, cur_ask_sz = ask_px[1:], ask_sz[1:]
    bid_pressure = np.where(cur_bid_px >= prev_bid_px, cur_bid_sz, 0.0) - np.where(
        cur_bid_px <= prev_bid_px, prev_bid_sz, 0.0
    )
    ask_pressure = np.where(cur_ask_px >= prev_ask_px, prev_ask_sz, 0.0) - np.where(
        cur_ask_px <= prev_ask_px, cur_ask_sz, 0.0
    )
    denominator = prev_bid_sz + prev_ask_sz + cur_bid_sz + cur_ask_sz
    raw = bid_pressure + ask_pressure
    safe = np.where(denominator > 0.0, denominator, 1.0)
    events[1:] = np.where(denominator > 0.0, raw / safe, 0.0)
    return events


def _column(rows: Sequence[Mapping[str, Any]], name: str) -> FloatArray:
    return np.fromiter((_as_float(row[name]) for row in rows), dtype=np.float64, count=len(rows))


def _as_float(value: object) -> float:
    if type(value) is float:
        return value
    try:
        return float(cast(Any, value))
    except TypeError as exc:
        raise ValueError(f"expected a number, got {value!r}") from exc


def _with_zero_ofi(row: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    enriched["ofi_event"] = 0.0
    for name in OFI_WINDOWS_MS:
        enriched[name] = 0.0
    return enriched
