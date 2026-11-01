"""The position book and the margin-free liquidation prior against Hydromancer snapshots.

    python -m marketimmune.cli.validate_positions --coins SOL,ETH --dates 20251201..20251231 --out eval/position_book_validation.json

The forced-flow forecaster (``cli.forced_forecast``) rolls each wallet's position forward
through fills and, with no margin data, gives a position the liquidation price
``entry * (1 - sign * median(delta | delta > excursion))``, where ``delta`` is the distance from
entry at which earlier wallets were liquidated. Hydromancer snapshots (one per UTC date, from
2025-12-15) hold every open position with its exact liquidation price. At each snapshot time
this rebuilds the forecaster's book as it stood (the same state and prior, fills strictly
before the snapshot) and compares:

- **positions:** wallets whose size matches exactly, wallets one side has and the other
  lacks, and the share of open notional each covers;
- **entry prices** of the exact matches;
- **liquidation prices:** the prior's against Hydromancer's, as distance from the mark, and
  the open notional by distance from the mark (what the forecaster sums);
- **forced fills** after each snapshot (node fills, ``liquidated_user``): how far the mark at
  liquidation was from the liquidation price in the latest snapshot, by method.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import polars as pl

from marketimmune.cli.build_positions import positions_path
from marketimmune.forced.forecaster import conditional_median_distance, liquidation_distances
from marketimmune.forced.margin_tiers import max_leverage_distance
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.utils import parse_date_spec, parse_symbol_spec

FloatArray = npt.NDArray[np.float64]
TOLERANCE = 1e-6
DISTANCE_EDGES = (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, np.inf)  # |liq / mark - 1|
POSITION_COLUMNS = ["ts_ms", "wallet", "start_pos", "px", "forced", "position_after", "entry_px_after"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="SOL,ETH")
    parser.add_argument("--dates", default="20251201..20251231", help="the book is rolled from the first date")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--hydro-dir", type=Path, default=Path("data/bronze/hydromancer"))
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--out", type=Path, default=Path("eval/position_book_validation.json"))
    return parser.parse_args(argv)


def _q(x: FloatArray, qs: tuple[float, ...] = (0.5, 0.9, 0.99)) -> dict[str, float] | None:
    return {f"p{round(q * 100)}": float(np.quantile(x, q)) for q in qs} if x.size else None


def distance_notional(distance: FloatArray, notional: FloatArray) -> dict[str, float]:
    """Share of notional by |liquidation / mark - 1| bucket."""
    total = notional.sum()
    out = {}
    for lo, hi in zip(DISTANCE_EDGES[:-1], DISTANCE_EDGES[1:], strict=True):
        m = (distance >= lo) & (distance < hi)
        out[f"{lo:.0%}-{hi:.0%}" if np.isfinite(hi) else f">{lo:.0%}"] = float(notional[m].sum() / total) if total else 0.0
    return out


def compare_snapshot(book: pd.DataFrame, hydro: pd.DataFrame, deltas: FloatArray, mark: float, coin: str) -> dict[str, Any]:
    """``book``: wallet, size, entry (our state at the snapshot). ``hydro``: the snapshot rows."""
    ours = book[book["size"].abs() > TOLERANCE].set_index("wallet")
    hm = hydro.set_index("user")
    both = ours.join(hm, how="inner")
    exact = both[(both["size"] - both["hm_size"]).abs() <= TOLERANCE * np.maximum(1.0, both["hm_size"].abs())]
    hm_notional = hm["hm_size"].abs() * mark
    total = float(hm_notional.sum())
    seen = set(book["wallet"])
    hm_only = hm.index.difference(ours.index)
    out: dict[str, Any] = {
        "mark": mark,
        "hydromancer_positions": len(hm),
        "book_positions": len(ours),
        "exact": len(exact),
        "exact_notional_share": float(hm_notional[exact.index].sum() / total),
        "size_mismatch": len(both) - len(exact),
        "size_mismatch_notional_share": float(hm_notional[both.index.difference(exact.index)].sum() / total),
        "hydromancer_only_never_seen": int(sum(w not in seen for w in hm_only)),
        "hydromancer_only_never_seen_notional_share": float(hm_notional[[w for w in hm_only if w not in seen]].sum() / total),
        "hydromancer_only_seen_flat": int(sum(w in seen for w in hm_only)),
        "book_only": len(ours.index.difference(hm.index)),
        "book_only_notional_usd": float(ours.loc[ours.index.difference(hm.index), "size"].abs().sum() * mark),
        "long_short_size": {"hydromancer": [float(hm["hm_size"].clip(lower=0).sum()), float(-hm["hm_size"].clip(upper=0).sum())],
                            "book": [float(ours["size"].clip(lower=0).sum()), float(-ours["size"].clip(upper=0).sum())]},
    }  # fmt: skip
    known = exact[exact["entry"].notna()]
    rel = (known["entry"] / known["hm_entry"] - 1.0).abs().to_numpy()
    out["entry"] = {
        "known": len(known),
        "unknown_entry": len(exact) - len(known),
        "abs_rel_diff": _q(rel),
        "within_1bp": float(np.mean(rel <= 1e-4)) if rel.size else None,
    }
    # liquidation prices: the prior on our book against Hydromancer's, for the same positions
    liq = known[known["hm_liq"].notna() & (known["hm_liq"] > 0)]
    sign = np.sign(liq["size"].to_numpy())
    entry = liq["entry"].to_numpy()
    excursion = np.maximum(-sign * (mark - entry) / entry, 0.0)
    prior = entry * (1.0 - sign * conditional_median_distance(deltas, excursion))
    maxlev = np.array(
        [
            entry[i] * (1.0 - s * max_leverage_distance(coin, int(s), abs(z) * mark))
            for i, (s, z) in enumerate(zip(sign, liq["size"].to_numpy(), strict=True))
        ]
    )
    hm_liq = liq["hm_liq"].to_numpy()
    d_hm = np.abs(hm_liq / mark - 1.0)
    ok = np.isfinite(prior) & (prior > 0)
    d_prior = np.abs(prior[ok] / mark - 1.0)
    notional = np.abs(liq["size"].to_numpy()) * mark
    out["liquidation"] = {
        "positions": int(len(liq)),
        "prior_defined": int(ok.sum()),
        "hydromancer_distance_from_mark": _q(d_hm),
        "prior_distance_from_mark": _q(d_prior),
        "max_leverage_distance_from_mark": _q(np.abs(maxlev / mark - 1.0)),
        "abs_error_prior_pct_of_mark": _q(np.abs(prior[ok] - hm_liq[ok]) / mark * 100),
        "abs_error_max_leverage_pct_of_mark": _q(np.abs(maxlev - hm_liq) / mark * 100),
        "corr_distance_prior_hydromancer": float(np.corrcoef(d_prior, d_hm[ok])[0, 1]) if ok.sum() > 2 else None,
        "notional_by_distance_hydromancer": distance_notional(d_hm, notional),
        "notional_by_distance_prior": distance_notional(d_prior, notional[ok]),
        "notional_by_distance_hydromancer_all_positions": distance_notional(
            np.abs(hm["hm_liq"].dropna().to_numpy() / mark - 1.0), (hm.loc[hm["hm_liq"].notna(), "hm_size"].abs() * mark).to_numpy()
        ),
    }
    return out


def forced_vs_snapshots(node_dir: Path, coin: str, dates: list[str], snaps: dict[int, pd.DataFrame]) -> dict[str, Any]:
    """Each liquidated wallet's first forced fill per block after the first snapshot, against the
    liquidation price in the latest earlier snapshot: the mark's overshoot past it (fraction,
    positive = beyond), by method."""
    times = np.array(sorted(snaps))
    rows = []
    for date in dates:
        f = node_dir / coin / f"{coin}-{date}.parquet"
        if not f.exists():
            continue
        legs = pl.read_parquet(
            f, columns=["time_ms", "user", "liquidated_user", "crossed", "liquidation_mark_px", "liquidation_method", "start_position"]
        )
        legs = legs.filter(pl.col("crossed") & (pl.col("user") == pl.col("liquidated_user"))).unique(
            ["time_ms", "user"], keep="first", maintain_order=True
        )
        rows.append(legs.to_pandas())
    if not rows:
        return {}
    ev = pd.concat(rows)
    k = np.searchsorted(times, ev["time_ms"].to_numpy(), side="right") - 1
    ev = ev[k >= 0].assign(snap=times[k[k >= 0]])
    out: dict[str, Any] = {"events": len(ev)}
    over, age, method = [], [], []
    for snap, g in ev.groupby("snap"):
        hm = snaps[int(snap)].set_index("user")
        g = g[g["user"].isin(hm.index)]
        liq = hm.loc[g["user"], "hm_liq"].to_numpy()
        sign = np.sign(g["start_position"].to_numpy())
        mk = g["liquidation_mark_px"].to_numpy()
        over.append(-sign * (mk - liq) / liq)  # long: liquidated when the mark falls below liq
        age.append((g["time_ms"].to_numpy() - snap) / 3.6e6)
        method.append(g["liquidation_method"].to_numpy())
    if over:
        o, a, m = np.concatenate(over), np.concatenate(age), np.concatenate(method)
        keep = np.isfinite(o)
        o, a, m = o[keep], a[keep], m[keep]
        out["with_snapshot_liq"] = int(o.size)
        out["snapshot_age_hours"] = _q(a)
        for name in sorted(set(m.tolist())):
            sel = m == name
            out[name] = {
                "events": int(sel.sum()),
                "overshoot": _q(o[sel], (0.1, 0.25, 0.5, 0.75, 0.9)),
                "within_1pct": float(np.mean(np.abs(o[sel]) <= 0.01)),
            }
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    dates = list(parse_date_spec(args.dates))
    result: dict[str, Any] = {"dates": args.dates, "coins": {}}
    for coin in parse_symbol_spec(args.coins):
        state: dict[str, tuple[float, float]] = {}
        sample: list[FloatArray] = []
        snapshots: dict[str, Any] = {}
        snaps: dict[int, pd.DataFrame] = {}
        for date in dates:
            positions = pd.read_parquet(positions_path(args.lake_root, coin, date), columns=POSITION_COLUMNS)
            hp = args.hydro_dir / coin / f"{coin}-{date}.parquet"
            if hp.exists():
                hydro = pd.read_parquet(hp).rename(columns={"size": "hm_size", "entry_price": "hm_entry", "liquidation_price": "hm_liq"})
                t = int(hydro["snapshot_ts_ms"].iloc[0])
                snaps[t] = hydro[["user", "hm_size", "hm_entry", "hm_liq"]]
                before = positions[positions["ts_ms"] < t].drop_duplicates("wallet", keep="last")
                merged = dict(state)
                merged.update(zip(before["wallet"], zip(before["position_after"], before["entry_px_after"], strict=True), strict=True))
                book = pd.DataFrame([(w, s, e) for w, (s, e) in merged.items()], columns=["wallet", "size", "entry"])
                l2 = pl.read_parquet(layout.silver_l2_book_path(coin, date), columns=["ts_ms", "mid"]).filter(pl.col("ts_ms") < t)
                mark = float(l2["mid"][-1])
                deltas = np.sort(np.concatenate(sample)) if sample else np.zeros(0)
                snapshots[date] = {
                    "snapshot_ts_ms": t,
                    "prior_n": int(deltas.size),
                    **compare_snapshot(book, hydro.drop(columns=["user"]).assign(user=hydro["user"]), deltas, mark, coin),
                }
            last = positions.drop_duplicates("wallet", keep="last")
            state.update(zip(last["wallet"], zip(last["position_after"], last["entry_px_after"], strict=True), strict=True))
            state = {w: v for w, v in state.items() if abs(v[0]) > TOLERANCE}
            sample.append(liquidation_distances(positions))
        result["coins"][coin] = {"snapshots": snapshots, "forced_fills": forced_vs_snapshots(args.node_dir, coin, dates, snaps)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    result = run(parse_args(argv))
    for coin, r in result["coins"].items():
        for date, s in r["snapshots"].items():
            liq = s["liquidation"]
            print(
                f"{coin} {date}: {s['exact']}/{s['hydromancer_positions']} exact ({s['exact_notional_share']:.0%} of notional), "
                f"never seen {s['hydromancer_only_never_seen_notional_share']:.0%}, mismatch {s['size_mismatch_notional_share']:.0%}; "
                f"prior error p50 {liq['abs_error_prior_pct_of_mark'] and liq['abs_error_prior_pct_of_mark']['p50']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
