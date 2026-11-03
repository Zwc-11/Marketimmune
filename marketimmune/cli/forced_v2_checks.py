"""Checks behind forecaster v2 (exploratory): the account roll, liquidations against snapshot
prices (including the backstop threshold), and the 2025-10-10 crash.

    python -m marketimmune.cli.forced_v2_checks --coins SOL,ETH --out eval/forced_v2_checks.json

Inputs: node fills, Hydromancer snapshots (Oct 8-12 and Dec 15-31 2025) and, for the crash
timeline, the October grid files of ``cli.forced_v2`` (``--grid-dir``).

- **account roll** (``forced.node_book.Account``): for each pair of snapshots on consecutive
  days, every wallet in the first that traded before the second and holds the same size in it.
  Its rolled liquidation price is compared with the second snapshot's, as is the first
  snapshot's price kept unchanged (v2a's rule), and the drift of wallets that did not trade.
- **liquidations against snapshot prices:** each wallet's first liquidation after a snapshot,
  if it had not traded since. Overshoot is how far the mark at liquidation
  (``liquidation_mark_px``) was past the snapshot's price, as a fraction of it (positive =
  beyond), by method and margin type. The docs: book liquidation when equity falls below
  maintenance margin, the backstop below 2/3 of it. For an isolated position whose margin did
  not change, that puts the backstop ``(r/3) / (1 - 2r/3)`` past the liquidation price for a
  long and ``(r/3) / (1 + 2r/3)`` for a short, ``r`` the maintenance rate (2.5% at 20x: 0.84%
  and 0.82%).
- **2025-10-10:** the 20:04 UTC snapshot against what followed until the next one: which
  wallets the price path crossed (trade-implied mid; the mark can differ) and which were
  liquidated, and the forecasts minute by minute through the crash.
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

from marketimmune.forced.margin_tiers import maintenance_terms
from marketimmune.forced.node_book import (
    account_from_snapshot,
    liquidation_events,
    read_legs,
    read_snapshot,
    roll_accounts,
    solve_liquidation_price,
    wallet_events,
)
from marketimmune.priority.fees import trade_mids
from marketimmune.utils import parse_date_spec, parse_symbol_spec, shift_date

FloatArray = npt.NDArray[np.float64]
PERIODS = {"oct": "20251008..20251012", "dec": "20251215..20251231"}
CRASH_DATE = "20251010"
TIMELINE = ("2025-10-10 20:45", "2025-10-10 21:30")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="SOL,ETH")
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--hydro-dir", type=Path, default=Path("data/bronze/hydromancer"))
    parser.add_argument("--grid-dir", type=Path, default=Path("data/gold/hyperliquid/forced_v2_oct"))
    parser.add_argument("--sections", default="roll,liquidations,crash")
    parser.add_argument("--periods", default="oct,dec", help="for the roll and liquidation sections")
    parser.add_argument("--out", type=Path, default=Path("eval/forced_v2_checks.json"))
    return parser.parse_args(argv)


def _q(x: FloatArray, qs: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)) -> dict[str, float] | None:
    x = x[np.isfinite(x)]
    return {f"p{round(q * 100)}": float(np.quantile(x, q)) for q in qs} if x.size else None


def _events_between(args: argparse.Namespace, coin: str, d0: str, b0: int, b1: int | None) -> pd.DataFrame:
    days = [d0] if b1 is None else [d0, shift_date(d0, 1)]
    parts = [wallet_events(legs) for legs in (read_legs(args.node_dir, coin, d) for d in days) if legs is not None]
    ev = pd.concat(parts, ignore_index=True)
    keep = ev["block_number"] > b0
    if b1 is not None:
        keep &= ev["block_number"] <= b1
    return ev[keep].reset_index(drop=True)


def _accounts(coin: str, snap: pd.DataFrame) -> dict[str, Any]:
    return {
        r.user: account_from_snapshot(
            coin, float(r.size), float(r.notional), float(r.liquidation_price), float(r.account_value),
            r.leverage_type == "isolated", float(r.leverage),
        )
        for r in snap.itertuples()
    }  # fmt: skip


def roll_pair(args: argparse.Namespace, coin: str, d0: str, d1: str) -> dict[str, Any] | None:
    s0, s1 = read_snapshot(args.hydro_dir, coin, d0), read_snapshot(args.hydro_dir, coin, d1)
    if s0 is None or s1 is None:
        return None
    b0, b1 = int(s0["snapshot_block"].iloc[0]), int(s1["snapshot_block"].iloc[0])
    ev = _events_between(args, coin, d0, b0, b1)
    acc = _accounts(coin, s0)
    roll_accounts(coin, ev, acc)
    touched = set(ev["wallet"])
    nxt, old = s1.set_index("user"), s0.set_index("user")
    rows = []
    for w, a in acc.items():
        if w not in nxt.index:
            continue
        size = float(nxt.at[w, "size"])
        mark = abs(float(nxt.at[w, "notional"]) / size)
        same = abs(size - a.size) <= 1e-6 * max(1.0, abs(size))
        eq = a.equity + a.size * (mark - a.mark)
        rolled = solve_liquidation_price(coin, a.size, eq, mark, a.other_mm) if same else np.nan
        rows.append((w, w in touched, same, nxt.at[w, "leverage_type"], abs(size) * mark, np.sign(size), mark,
                     nxt.at[w, "liquidation_price"], old.at[w, "liquidation_price"], rolled))  # fmt: skip
    f = pd.DataFrame(rows, columns=["wallet", "touched", "same", "margin", "usd", "sign", "mark", "truth", "kept", "rolled"])
    f[["truth", "kept"]] = f[["truth", "kept"]].fillna(np.inf)
    out: dict[str, Any] = {"pair": [d0, d1], "touched_same_size": int((f["touched"] & f["same"]).sum())}

    def within(sel: pd.Series, col: str) -> float | None:
        ok = sel & np.isfinite(f["truth"]) & np.isfinite(f[col]) & (f[col] > 1e-9)
        err = (f[col] - f["truth"]).abs() / f["mark"]
        usd = f.loc[ok, "usd"].sum()
        return float(f.loc[ok & (err <= 0.01), "usd"].sum() / usd) if usd > 0 else None

    def room(col: str) -> pd.Series:  # > 0: room left before liquidation, as a fraction of the mark; inf: none
        liq = f[col].to_numpy(dtype=np.float64)
        r = np.where(f["sign"] > 0, f["mark"] / liq - 1.0, liq / f["mark"] - 1.0)
        return pd.Series(np.where(np.isfinite(liq), r, np.inf), index=f.index)

    for margin in ("cross", "isolated"):
        t = f["touched"] & f["same"] & (f["margin"] == margin)
        u = ~f["touched"] & f["same"] & (f["margin"] == margin)
        rt, rr = room("truth"), room("rolled")
        out[margin] = {
            "touched": int(t.sum()),
            "touched_usd": float(f.loc[t, "usd"].sum()),
            "rolled_within_1pct_usd_share": within(t, "rolled"),
            "kept_within_1pct_usd_share": within(t, "kept"),
            "untouched": int(u.sum()),
            "untouched_kept_within_1pct_usd_share": within(u, "kept"),
            "touched_usd_room_under_3pct": {"truth": float(f.loc[t & (rt < 0.03), "usd"].sum()), "rolled": float(f.loc[t & (rr < 0.03), "usd"].sum())},
            "touched_usd_rolled_crossed": float(f.loc[t & (rr <= 0.0), "usd"].sum()),
        }  # fmt: skip
    return out


def first_liquidations(args: argparse.Namespace, coin: str, date: str) -> pd.DataFrame:
    """Each snapshot wallet's first liquidation before the next snapshot, if it had not traded
    since this one, with the snapshot's price, margin type and the account's backstop price."""
    snap = read_snapshot(args.hydro_dir, coin, date)
    nxt = read_snapshot(args.hydro_dir, coin, shift_date(date, 1))
    if snap is None:
        return pd.DataFrame()
    b0 = int(snap["snapshot_block"].iloc[0])
    b1 = int(nxt["snapshot_block"].iloc[0]) if nxt is not None else None
    legs = [read_legs(args.node_dir, coin, d) for d in ([date] if b1 is None else [date, shift_date(date, 1)])]
    allegs = pl.concat([x for x in legs if x is not None])
    allegs = allegs.filter(pl.col("block_number") > b0)
    if b1 is not None:
        allegs = allegs.filter(pl.col("block_number") <= b1)
    liq = liquidation_events(allegs).to_pandas().drop_duplicates("user", keep="first")
    # traded before its liquidation block: a non-liquidation leg of the wallet in an earlier block
    own = (pl.col("user") == pl.col("liquidated_user")).fill_null(False)
    first_trade = allegs.filter(~own).group_by("user").agg(pl.col("block_number").min().alias("first_trade")).to_pandas()
    liq = liq.merge(first_trade, on="user", how="left")
    liq = liq[liq["first_trade"].isna() | (liq["first_trade"] > liq["block_number"])]
    s = snap.set_index("user")
    liq = liq[liq["user"].isin(s.index)]
    out = []
    for r in liq.itertuples():
        size, lp = float(s.at[r.user, "size"]), float(s.at[r.user, "liquidation_price"])
        if not np.isfinite(lp) or abs(size - r.start_position) > 1e-6 * max(1.0, abs(size)):
            continue
        sign = 1.0 if size > 0 else -1.0
        notional = float(s.at[r.user, "notional"])
        a = account_from_snapshot(
            coin,
            size,
            notional,
            lp,
            float(s.at[r.user, "account_value"]),
            s.at[r.user, "leverage_type"] == "isolated",
            float(s.at[r.user, "leverage"]),
        )
        rate, deduction = maintenance_terms(coin, abs(notional))
        # backstop: equity + size (p - mark) = 2/3 (rate |size| p - deduction + other_mm)
        p_b = (2.0 / 3.0 * (a.other_mm - deduction) - a.equity + size * a.mark) / (size - 2.0 / 3.0 * rate * abs(size))
        out.append({
            "user": r.user, "date": date, "method": r.method, "margin": s.at[r.user, "leverage_type"], "sign": sign,
            "usd": abs(size) * r.mark, "liq": lp, "mark": r.mark, "backstop_px": p_b, "rate": rate,
            "overshoot": sign * (lp - r.mark) / lp,
            "backstop_overshoot": sign * (lp - p_b) / lp,
            "hours_after_snapshot": (r.time_ms - float(snap["snapshot_ts_ms"].iloc[0])) / 3.6e6,
        })  # fmt: skip
    return pd.DataFrame(out)


def liquidation_summary(frame: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"events": len(frame)}
    if frame.empty:
        return out
    for (method, margin), g in frame.groupby(["method", "margin"]):
        o = g["overshoot"].to_numpy(dtype=np.float64)
        th = g["backstop_overshoot"].to_numpy(dtype=np.float64)
        out[f"{method}_{margin}"] = {
            "events": len(g),
            "usd": float(g["usd"].sum()),
            "overshoot": _q(o),
            "within_0.25pct": float(np.mean(np.abs(o) <= 0.0025)),
            "within_1pct": float(np.mean(np.abs(o) <= 0.01)),
            "backstop_threshold_overshoot": _q(th),
            "past_backstop_threshold": float(np.mean(o >= th)),
            "hours_after_snapshot": _q(g["hours_after_snapshot"].to_numpy(dtype=np.float64), (0.5,)),
        }
    return out


def crash(args: argparse.Namespace, coin: str) -> dict[str, Any]:
    snap = read_snapshot(args.hydro_dir, coin, CRASH_DATE)
    nxt = read_snapshot(args.hydro_dir, coin, shift_date(CRASH_DATE, 1))
    assert snap is not None and nxt is not None
    t0, t1 = float(snap["snapshot_ts_ms"].iloc[0]), float(nxt["snapshot_ts_ms"].iloc[0])
    b0, b1 = int(snap["snapshot_block"].iloc[0]), int(nxt["snapshot_block"].iloc[0])
    legs = pl.concat([x for x in (read_legs(args.node_dir, coin, d) for d in (CRASH_DATE, shift_date(CRASH_DATE, 1))) if x is not None])
    legs = legs.filter((pl.col("block_number") > b0) & (pl.col("block_number") <= b1))
    mids = trade_mids(legs)
    mid = mids["mid"].to_numpy()
    lo, hi = float(mid.min()), float(mid.max())
    mark0 = float((snap["notional"].abs() / snap["size"].abs()).median())
    liqs = liquidation_events(legs).to_pandas()
    by_user = liqs.groupby("user").agg(method=("method", "first"), usd=("usd", "sum"))
    s = snap.assign(usd=snap["notional"].abs(), sign=np.sign(snap["size"]))
    lp = s["liquidation_price"].to_numpy(dtype=np.float64)
    crossed = np.where(s["sign"] > 0, lo <= lp, hi >= lp) & np.isfinite(lp)
    liquidated = s["user"].isin(by_user.index).to_numpy()
    out: dict[str, Any] = {
        "snapshot_utc": str(pd.Timestamp(t0, unit="ms")),
        "next_snapshot_utc": str(pd.Timestamp(t1, unit="ms")),
        "mark_at_snapshot": mark0,
        "trade_mid_low": lo,
        "trade_mid_low_utc": str(mids["t"][int(np.argmin(mid))]),
        "trade_mid_high": hi,
        "snapshot_positions": len(s),
        "snapshot_usd": float(s["usd"].sum()),
    }
    room = np.where(s["sign"] > 0, mark0 / lp - 1.0, lp / mark0 - 1.0)
    out["snapshot_usd_by_room"] = {
        side: {f"<{int(e * 100)}%": float(s["usd"][(s["sign"] == sg) & np.isfinite(lp) & (room < e)].sum()) for e in (0.01, 0.02, 0.05, 0.10, 0.20, 0.35)}
        for side, sg in (("long", 1.0), ("short", -1.0))
    }  # fmt: skip
    out["wallets"] = {
        name: {"n": int(m.sum()), "usd": float(s["usd"][m].sum())}
        for name, m in (
            ("crossed_and_liquidated", crossed & liquidated),
            ("crossed_not_liquidated", crossed & ~liquidated),
            ("not_crossed_liquidated", ~crossed & liquidated),
            ("long_crossed", crossed & (s["sign"] > 0).to_numpy()),
        )
    }
    in_snap = liqs["user"].isin(set(s["user"]))
    out["liquidated_usd"] = {
        method: {"total": float(g["usd"].sum()), "wallets_in_snapshot": float(g["usd"][in_snap[g.index]].sum())}
        for method, g in liqs.groupby("method")
    }
    out["timeline"] = timeline(args, coin, liqs, mids)
    return out


def timeline(args: argparse.Namespace, coin: str, liqs: pd.DataFrame, mids: pl.DataFrame) -> dict[str, Any]:
    """Per minute through the crash: price, market and backstop liquidations (USD) hitting bids,
    and each variant's 60 s forecast; plus when each signal first alarmed (above the previous
    day's 95th percentile)."""
    start, end = (pd.Timestamp(x).value / 1e6 for x in TIMELINE)
    grids = {}
    for v in ("v1", "v2a", "v2"):
        cur = args.grid_dir / coin / f"{coin}-{CRASH_DATE}.{v}.parquet"
        prev = args.grid_dir / coin / f"{coin}-{shift_date(CRASH_DATE, -1)}.{v}.parquet"
        if cur.exists() and prev.exists():
            grids[v] = (pd.read_parquet(cur), pd.read_parquet(prev))

    def minute(t: FloatArray) -> npt.NDArray[np.int64]:
        out: npt.NDArray[np.int64] = ((t - start) // 60_000).astype(np.int64)
        return out

    n = int((end - start) // 60_000)
    sell = liqs[(liqs["start_position"] > 0) & (liqs["time_ms"] >= start) & (liqs["time_ms"] < end)]
    rows: dict[str, Any] = {"minute_utc": [str(pd.Timestamp(start + 60_000 * k, unit="ms").time()) for k in range(n)]}
    for method in ("market", "backstop"):
        g = sell[sell["method"] == method]
        rows[f"{method}_long_liquidated_usd"] = np.bincount(minute(g["time_ms"].to_numpy()), weights=g["usd"].to_numpy(), minlength=n)[
            :n
        ].tolist()
    mt = mids["t"].dt.epoch("ns").to_numpy() / 1e6
    mm = mids["mid"].to_numpy()
    rows["mid_last"] = [float(mm[np.searchsorted(mt, start + 60_000 * (k + 1), side="left") - 1]) for k in range(n)]
    alarms: dict[str, Any] = {}
    for v, (cur, prev) in grids.items():
        sel = (cur["ts_ms"] >= start) & (cur["ts_ms"] < end)
        g = cur[sel]
        k = minute(g["ts_ms"].to_numpy())
        cnt = np.bincount(k, minlength=n)[:n]
        for col in ("F_bid_60s", "P_bid_60s", "heatmap_bid_1pct"):
            rows[f"{v}_{col}_mean"] = (np.bincount(k, weights=g[col].to_numpy(), minlength=n)[:n] / np.maximum(cnt, 1)).tolist()
        for col in ("F_bid_60s", "heatmap_bid_1pct"):
            thr = float(np.quantile(prev[col].to_numpy(), 0.95))
            on = cur[(cur[col] >= thr) & (cur[col] > 0) & (cur["ts_ms"] >= start)]
            alarms[f"{v}_{col}"] = {
                "threshold": thr,
                "first_alarm_utc": str(pd.Timestamp(on["ts_ms"].iloc[0], unit="ms")) if len(on) else None,
            }
        # expected notional over the window (each 60 s forecast covers 6 grid steps of 10 s)
        rows[f"{v}_expected_bid_usd_per_minute"] = (np.bincount(k, weights=g["F_bid_60s"].to_numpy(), minlength=n)[:n] / 6.0).tolist()
    return {"per_minute": rows, "alarms": alarms}


def run(args: argparse.Namespace) -> dict[str, Any]:
    sections = set(args.sections.split(","))
    res: dict[str, Any] = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for coin in parse_symbol_spec(args.coins):
        entry = res.setdefault(coin, {})
        if "roll" in sections:
            entry.setdefault("account_roll", {})
            for period, spec in ((p, PERIODS[p]) for p in args.periods.split(",")):
                dates = list(parse_date_spec(spec))
                pairs = [p for p in (roll_pair(args, coin, d0, d1) for d0, d1 in zip(dates[:-1], dates[1:], strict=True)) if p]
                entry["account_roll"][period] = {"pairs": pairs, "pooled": pool_pairs(pairs)}
        if "liquidations" in sections:
            entry.setdefault("liquidations", {})
            for period, spec in ((p, PERIODS[p]) for p in args.periods.split(",")):
                frame = pd.concat([first_liquidations(args, coin, d) for d in parse_date_spec(spec)], ignore_index=True)
                entry["liquidations"][period] = liquidation_summary(frame)
        if "crash" in sections:
            entry["crash_20251010"] = crash(args, coin)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1, default=float) + "\n", encoding="utf-8")
    return res


def pool_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """USD-weighted shares over the pairs (weights: each pair's touched notional)."""
    out: dict[str, Any] = {}
    for margin in ("cross", "isolated"):
        w = np.array([p[margin]["touched_usd"] for p in pairs])
        entry: dict[str, Any] = {"touched": int(sum(p[margin]["touched"] for p in pairs)), "touched_usd": float(w.sum())}
        for key in ("rolled_within_1pct_usd_share", "kept_within_1pct_usd_share"):
            v = np.array([p[margin][key] if p[margin][key] is not None else np.nan for p in pairs])
            ok = ~np.isnan(v)
            entry[key] = float((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() and w[ok].sum() > 0 else None
        u = np.array(
            [
                p[margin]["untouched_kept_within_1pct_usd_share"]
                if p[margin]["untouched_kept_within_1pct_usd_share"] is not None
                else np.nan
                for p in pairs
            ]
        )
        entry["untouched_kept_within_1pct_usd_share_mean"] = float(np.nanmean(u)) if np.isfinite(u).any() else None
        for key in ("truth", "rolled"):
            entry[f"touched_usd_room_under_3pct_{key}"] = float(sum(p[margin]["touched_usd_room_under_3pct"][key] for p in pairs))
        entry["touched_usd_rolled_crossed"] = float(sum(p[margin]["touched_usd_rolled_crossed"] for p in pairs))
        out[margin] = entry
    return out


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
