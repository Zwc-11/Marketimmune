"""Point-in-time Hyperliquid feature joins for markout training rows."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from typing import Any

from marketimmune.labels.leakage import assert_as_of

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
TimedIndex = dict[str, tuple[list[float], list[Mapping[str, Any]]]]


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

    row = dict(label_row)
    row["feature_ts_ms"] = max(feature_ts_ms)
    for name in L2_FEATURES:
        row[f"l2_{name}"] = _as_float(l2_row[name])
    if asset_ctx_row is not None:
        for name in ASSET_FEATURES:
            if name in asset_ctx_row and asset_ctx_row[name] is not None:
                row[f"asset_{name}"] = _as_float(asset_ctx_row[name])
    return row


def build_hyperliquid_training_rows(
    label_rows: Sequence[Mapping[str, Any]],
    l2_rows: Sequence[Mapping[str, Any]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build model-ready rows using only features known at or before each fill."""
    enriched_l2_rows = l2_rows_with_ofi(l2_rows)
    l2_index = _timed_index(enriched_l2_rows)
    asset_timed_index = _timed_index([row for row in asset_ctx_rows if "ts_ms" in row])
    asset_static_latest = _latest_static_by_coin(asset_ctx_rows)
    out: list[dict[str, Any]] = []
    for label in label_rows:
        coin = str(label["coin"])
        fill_ts_ms = _as_float(label["ts_ms"])
        l2_row = _latest_from_index(l2_index, coin=coin, ts_ms=fill_ts_ms)
        if l2_row is None:
            continue
        asset_ctx = _latest_from_index(asset_timed_index, coin=coin, ts_ms=fill_ts_ms)
        if asset_ctx is None and coin not in asset_timed_index:
            asset_ctx = asset_static_latest.get(coin)
        out.append(training_row_from_asof(label, l2_row, asset_ctx))
    return out


def l2_rows_with_ofi(
    l2_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach snapshot-derived event OFI and rolling OFI windows to L2 rows.

    OFI is computed from consecutive top-of-book snapshots using the standard
    bid/ask price-size pressure formula. The event value is normalized by current
    plus previous top-of-book size so it is comparable across coins and regimes.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in l2_rows:
        if "ts_ms" not in row:
            passthrough.append(_with_zero_ofi(row))
            continue
        grouped.setdefault(str(row.get("coin")), []).append(row)

    out = passthrough
    for rows in grouped.values():
        ordered = sorted(rows, key=lambda row: _as_float(row["ts_ms"]))
        times = [_as_float(row["ts_ms"]) for row in ordered]
        event_values: list[float] = []
        enriched: list[dict[str, Any]] = []
        previous: Mapping[str, Any] | None = None
        for row in ordered:
            event = 0.0 if previous is None else _normalized_ofi_event(previous, row)
            event_values.append(event)
            enriched.append({**dict(row), "ofi_event": event})
            previous = row

        cumulative = [0.0]
        for event in event_values:
            cumulative.append(cumulative[-1] + event)
        for idx, row in enumerate(enriched):
            ts_ms = times[idx]
            for name, window_ms in OFI_WINDOWS_MS.items():
                left = bisect_left(times, ts_ms - window_ms)
                row[name] = cumulative[idx + 1] - cumulative[left]
        out.extend(enriched)
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


def _timed_index(rows: Sequence[Mapping[str, Any]]) -> TimedIndex:
    grouped: dict[str, list[tuple[float, Mapping[str, Any]]]] = {}
    for row in rows:
        if "ts_ms" not in row:
            continue
        grouped.setdefault(str(row.get("coin")), []).append((_as_float(row["ts_ms"]), row))
    index: TimedIndex = {}
    for coin, pairs in grouped.items():
        pairs.sort(key=lambda item: item[0])
        index[coin] = (
            [ts for ts, _row in pairs],
            [row for _ts, row in pairs],
        )
    return index


def _latest_from_index(
    index: TimedIndex,
    *,
    coin: str,
    ts_ms: float,
) -> Mapping[str, Any] | None:
    item = index.get(coin)
    if item is None:
        return None
    timestamps, rows = item
    idx = bisect_right(timestamps, ts_ms) - 1
    if idx < 0:
        return None
    return rows[idx]


def _latest_static_by_coin(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    latest: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if "ts_ms" not in row:
            latest[str(row.get("coin"))] = row
    return latest


def _as_float(value: object) -> float:
    return float(str(value))


def _with_zero_ofi(row: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    enriched["ofi_event"] = 0.0
    for name in OFI_WINDOWS_MS:
        enriched[name] = 0.0
    return enriched


def _normalized_ofi_event(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float:
    raw = _ofi_event(previous, current)
    denominator = (
        _as_float(previous["bid_sz"])
        + _as_float(previous["ask_sz"])
        + _as_float(current["bid_sz"])
        + _as_float(current["ask_sz"])
    )
    if denominator <= 0.0:
        return 0.0
    return raw / denominator


def _ofi_event(previous: Mapping[str, Any], current: Mapping[str, Any]) -> float:
    prev_bid_px = _as_float(previous["bid_px"])
    prev_bid_sz = _as_float(previous["bid_sz"])
    prev_ask_px = _as_float(previous["ask_px"])
    prev_ask_sz = _as_float(previous["ask_sz"])
    bid_px = _as_float(current["bid_px"])
    bid_sz = _as_float(current["bid_sz"])
    ask_px = _as_float(current["ask_px"])
    ask_sz = _as_float(current["ask_sz"])

    bid_pressure = (bid_sz if bid_px >= prev_bid_px else 0.0) - (
        prev_bid_sz if bid_px <= prev_bid_px else 0.0
    )
    ask_pressure = (prev_ask_sz if ask_px >= prev_ask_px else 0.0) - (
        ask_sz if ask_px <= prev_ask_px else 0.0
    )
    return bid_pressure + ask_pressure
