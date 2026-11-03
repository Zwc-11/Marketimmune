"""A1 secondary: how long a fee-paying taker's warning lasts (plan A.5 test 4).

    python -m marketimmune.cli.a1_lead_time --coins BTC,ETH,SOL --out eval/a1/lead_time.json

The pre-registration lists "the lead-time curve (plan A.5 test 4)" as secondary: the maker's
markout as a function of how many blocks before the fill a fee-paying taker hit the same side.
For each Gold fill at block ``b`` on side ``s``, the lag is ``b`` minus the latest earlier block
(``< b``, as the features see it) in which a taker that paid a priority fee hit side ``s``, the
previous date's last blocks included. Fills are grouped by lag; each group's markouts (the move
from the pre-fill mid at 1 s and 10 s, and from the fill price at 1 s) are averaged per day and
reported as the mean of daily means with a stationary-bootstrap 95% interval, for the
confirmation and the discovery dates. No model is involved, and the CEX gap is not controlled for.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import polars as pl

from marketimmune.cli.a1_ladder import CONFIRMATION, DISCOVERY, FIRST_GOLD
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.models.compare import stationary_bootstrap_ci
from marketimmune.utils import parse_date_spec, parse_symbol_spec, shift_date

FloatArray = npt.NDArray[np.float64]
COLUMNS = ["ts_ms", "block_number", "maker_side", "taker_fee_prio_bps", "markout_bps_1s", "markout_bps_10s", "markout_px_bps_1s"]
# lag in blocks: [lo, hi]; "none" = no fee-paying taker on that side in the last 300 blocks
BUCKETS = ((1, 1), (2, 3), (4, 10), (11, 30), (31, 100), (101, 300))
LABELS = (*(f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in BUCKETS), "none")
MARKOUTS = ("markout_bps_1s", "markout_bps_10s", "markout_px_bps_1s")
CARRY = 300


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("eval/a1/lead_time.json"))
    return parser.parse_args(argv)


def lags(block: npt.NDArray[np.int64], side: FloatArray, fee_blocks: dict[float, npt.NDArray[np.int64]]) -> FloatArray:
    """Blocks since the latest strictly earlier fee-paying block on the fill's side (inf if none)."""
    out = np.full(block.size, np.inf)
    for s, blocks in fee_blocks.items():
        m = side == s
        if blocks.size == 0 or not m.any():
            continue
        j = np.searchsorted(blocks, block[m], side="left") - 1
        ok = j >= 0
        lag = np.full(int(m.sum()), np.inf)
        lag[ok] = (block[m][ok] - blocks[j[ok]]).astype(np.float64)
        out[m] = lag
    return out


def bucket(lag: FloatArray) -> npt.NDArray[np.int64]:
    out = np.full(lag.size, len(BUCKETS), dtype=np.int64)  # "none"
    for k, (lo, hi) in enumerate(BUCKETS):
        out[(lag >= lo) & (lag <= hi)] = k
    return out


def day_rows(
    layout: HyperliquidLakeLayout, coin: str, date: str, carry: dict[float, npt.NDArray[np.int64]]
) -> tuple[pl.DataFrame, dict[float, npt.NDArray[np.int64]]]:
    """One date's fills with their lag bucket, and this date's last fee blocks for the next."""
    g = pl.read_parquet(layout.gold_training_path(coin, date), columns=COLUMNS).sort("block_number")
    block = g["block_number"].to_numpy().astype(np.int64)
    side = g["maker_side"].to_numpy().astype(np.float64)
    paid = g["taker_fee_prio_bps"].fill_null(0.0).to_numpy() > 0
    fee_blocks = {}
    for s in (1.0, -1.0):
        today = np.unique(block[paid & (side == s)])
        fee_blocks[s] = np.concatenate([carry.get(s, np.zeros(0, dtype=np.int64)), today])
    lag = lags(block, side, fee_blocks)
    out = g.with_columns(pl.Series("bucket", bucket(lag)), pl.Series("lag", lag), pl.lit(date).alias("date"))
    nxt = {s: b[b > block.max() - CARRY] if block.size else b for s, b in fee_blocks.items()}
    return out, nxt


def day_summary(rows: pl.DataFrame) -> pl.DataFrame:
    """One row per lag bucket of one date: fills, mean markouts (a NaN label is a stale mid, so it
    is left out), and the date's milliseconds per block."""
    rows = rows.with_columns(pl.col(m).fill_nan(None) for m in MARKOUTS)
    span = rows["block_number"].max() - rows["block_number"].min()  # type: ignore[operator]
    ms = (rows["ts_ms"].max() - rows["ts_ms"].min()) / span if span else np.nan  # type: ignore[operator]
    return (
        rows.group_by("date", "bucket").agg(pl.len().alias("n"), *(pl.col(m).mean() for m in MARKOUTS)).with_columns(pl.lit(ms).alias("ms"))
    )


def summarise(daily: pl.DataFrame) -> dict[str, Any]:
    """Mean of daily means per bucket with a bootstrap interval, from ``day_summary`` rows."""
    total = int(daily["n"].sum())
    out: dict[str, Any] = {
        "fills": total,
        "days": int(daily["date"].n_unique()),
        "ms_per_block_median": float(np.median(daily.unique("date")["ms"].to_numpy())),
    }
    for k, label in enumerate(LABELS):
        d = daily.filter(pl.col("bucket") == k).sort("date")
        entry: dict[str, Any] = {"fills": int(d["n"].sum()), "share": float(d["n"].sum() / total) if total else 0.0, "days": d.height}
        for m in MARKOUTS:
            v = d[m].drop_nulls().to_numpy().astype(np.float64)
            v = v[np.isfinite(v)]
            entry[m] = float(v.mean()) if v.size else None
            entry[f"{m}_ci95"] = list(stationary_bootstrap_ci(v)) if v.size >= 3 else None
        out[label] = entry
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    periods = {"confirmation": set(parse_date_spec(CONFIRMATION)), "discovery": set(parse_date_spec(DISCOVERY))}
    result: dict[str, Any] = {"buckets_blocks": LABELS, "coins": {}}
    for coin in parse_symbol_spec(args.coins):
        carry: dict[float, npt.NDArray[np.int64]] = {}
        parts: dict[str, list[pl.DataFrame]] = {p: [] for p in periods}
        date, last = FIRST_GOLD, max(max(v) for v in periods.values())
        while date <= last:
            if layout.gold_training_path(coin, date).exists():
                rows, carry = day_rows(layout, coin, date, carry)
                for p, dates in periods.items():
                    if date in dates:
                        parts[p].append(day_summary(rows))
            else:
                carry = {}
            date = shift_date(date, 1)
        result["coins"][coin] = {p: summarise(pl.concat(v)) for p, v in parts.items() if v}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    res = run(parse_args(argv))
    for coin, periods in res["coins"].items():
        c = periods.get("confirmation", {})
        row = " ".join(f"{b}:{c[b]['markout_bps_1s']:+.2f}" for b in LABELS if b in c and c[b]["markout_bps_1s"] is not None)
        print(f"{coin} confirmation, 1 s markout by lag (blocks): {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
