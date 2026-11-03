"""Priority fees in fills: rollout date per coin, fee distribution, and maker markout by the taker's fee band.

    python -m marketimmune.cli.priority_fee_bands --coins BTC,ETH,SOL --dates 20260301..20261031
    python -m marketimmune.cli.priority_fee_bands --coins BTC,ETH,SOL --dates 20260301..20261031 --report eval/priority_fee_bands.json

Plan v3, A.5 tests 1 and 2: the first date with ``priorityGas > 0`` per coin, and the maker's
markout by the taker's fee band (0, 0-2, 2-4, 4-8, 8+ bps) with day-level bootstrap intervals,
before any model. Fees are in bps of notional (``priority.fees``). Markouts are on the mid implied by
trades (``priority.fees.trade_mids``; ``cli.validate_trade_mids`` checks it against the rebuilt book).

The first form writes, per coin and date, ``<out>/<COIN>/<COIN>-<date>.bands.parquet`` (band sums,
so days add up) and ``.hist.parquet`` (fee histogram in 0.02 bp bins); dates already written are
skipped, so it can run in pieces. ``--report`` reads them and writes the JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from marketimmune.models.compare import stationary_bootstrap_ci
from marketimmune.priority.fees import BANDS, HORIZONS_S, band_stats, fill_markouts, hype_usd
from marketimmune.utils import parse_date_spec, parse_symbol_spec

HIST_BIN_BPS = 0.02
MIN_DAY_FILLS = 30  # a day enters a band's interval only with this many fills in the band


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--dates", default="20260301..20261031")
    parser.add_argument("--node-dir", type=Path, default=Path("data/bronze/node_fills"))
    parser.add_argument("--candles-dir", type=Path, default=Path("data/bronze/hyperliquid/candles"))
    parser.add_argument("--out", type=Path, default=Path("data/gold/hyperliquid/priority_bands"))
    parser.add_argument("--report", type=Path, default=None, help="aggregate the written days into this JSON")
    parser.add_argument("--recent-days", type=int, default=60, help="the report also covers the last this many dates")
    return parser.parse_args(argv)


def day_files(out: Path, coin: str, date: str) -> tuple[Path, Path]:
    base = out / coin / f"{coin}-{date}"
    return base.with_suffix(".bands.parquet"), base.with_suffix(".hist.parquet")


def write_day(args: argparse.Namespace, hype: pl.DataFrame, coin: str, date: str) -> bool:
    bands_path, hist_path = day_files(args.out, coin, date)
    if bands_path.exists() and hist_path.exists():
        return False
    trades = fill_markouts(pl.read_parquet(args.node_dir / coin / f"{coin}-{date}.parquet"), hype)
    stats = band_stats(trades).with_columns(pl.lit(trades.select(pl.col("hype_usd").mean()).item()).alias("hype_usd"))
    paid = trades.filter(pl.col("fee_bps") > 0)
    hist = paid.group_by((pl.col("fee_bps") / HIST_BIN_BPS).floor().cast(pl.Int32).alias("bin")).agg(
        pl.len().alias("fills"), pl.col("notional").sum()
    )
    bands_path.parent.mkdir(parents=True, exist_ok=True)
    for frame, path in ((stats, bands_path), (hist.sort("bin"), hist_path)):
        tmp = path.with_suffix(".part")
        frame.write_parquet(tmp)
        tmp.replace(path)  # whole files only, so a run stopped midway resumes cleanly
    return True


def _sum(frame: pl.DataFrame, col: str) -> float:
    return float(frame.select(pl.col(col).sum()).item())


def _mean(frame: pl.DataFrame, col: str, weight: str = "fills") -> float | None:
    total = _sum(frame, weight)
    key = f"{col}_sum" if weight == "fills" else f"{col}_nsum"
    return _sum(frame, key) / total if total else None


def band_table(days: pl.DataFrame) -> dict[str, Any]:
    """Per band: share of fills and notional, mean fee, and fill- and notional-weighted markouts;
    the mean of daily means with a day-level stationary-bootstrap interval for the 1, 10 and 60 s
    markouts and the 1 s adverse move."""
    out: dict[str, Any] = {"days": int(days["date"].n_unique()), "fills": int(days["fills"].sum())}
    total_fills, total_notional = _sum(days, "fills"), _sum(days, "notional")
    for band in BANDS:
        b = days.filter(pl.col("band") == band)
        if b.is_empty():
            continue
        row: dict[str, Any] = {
            "fills": int(b["fills"].sum()),
            "fill_share": _sum(b, "fills") / total_fills,
            "notional_share": _sum(b, "notional") / total_notional,
            "mean_fee_bps": _sum(b, "fee_bps_sum") / _sum(b, "fills"),
            "half_spread_bps": _mean(b, "hs_bps"),
        }
        for h in HORIZONS_S:
            for k in ("mo", "adv"):
                row[f"{k}_{h:g}s"] = _mean(b, f"{k}_{h:g}s")
                row[f"{k}_{h:g}s_notional_weighted"] = _mean(b, f"{k}_{h:g}s", "notional")
        daily = b.filter(pl.col("fills") >= MIN_DAY_FILLS).sort("date")
        row["days_in_interval"] = daily.height
        if daily.height >= 3:
            for k in ("mo_1s", "adv_1s", "mo_10s", "mo_60s"):
                lo, hi = stationary_bootstrap_ci((daily[f"{k}_sum"] / daily["fills"]).to_numpy())
                row[f"{k}_daily_mean"] = float((daily[f"{k}_sum"] / daily["fills"]).mean())  # type: ignore[arg-type]
                row[f"{k}_ci95"] = [lo, hi]
        out[band] = row
    return out


def fee_summary(hist: pl.DataFrame, days: pl.DataFrame) -> dict[str, Any]:
    """Quantiles of the fee among fee-paying fills, and the units check.

    The protocol's latency benefit stops at 8 bps, so fees bunch at 8 (and at 4). Those spikes sit
    at the same bps every month only if ``priorityGas`` is converted with the right HYPE price:
    with the wrong units they would drift with HYPE's price, which ranged widely over the window."""
    if hist.is_empty():
        return {}
    h = hist.group_by("bin").agg(pl.col("fills").sum()).sort("bin")
    cum = np.cumsum(h["fills"].to_numpy()) / h["fills"].sum()
    q = {
        f"q{round(p * 100)}": float((h["bin"].to_numpy()[np.searchsorted(cum, p)] + 0.5) * HIST_BIN_BPS)
        for p in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99)
    }
    bps = (pl.col("bin") + 0.5) * HIST_BIN_BPS
    month = pl.col("date").str.slice(0, 6)
    hype = days.group_by("date").agg(pl.col("hype_usd").first()).group_by(month.alias("month")).agg(pl.col("hype_usd").mean())
    monthly = []
    for (m,), g in hist.with_columns(bps.alias("bps")).group_by(month.alias("month"), maintain_order=True):

        def fills(lo: float, hi: float, g: pl.DataFrame = g) -> int:
            return int(g.filter((pl.col("bps") >= lo) & (pl.col("bps") < hi))["fills"].sum())

        above = g.filter(pl.col("bps") > 2.0).group_by("bps").agg(pl.col("fills").sum()).sort("fills", "bps", descending=[True, False])
        monthly.append(
            {
                "month": m,
                "hype_usd": float(hype.filter(pl.col("month") == m)["hype_usd"].item()),
                "mode_above_2bps": float(above["bps"][0]) if above.height else None,
                "fills_7.9_8.1": fills(7.9, 8.1),
                "fills_7.5_7.9": fills(7.5, 7.9),
                "fills_8.1_8.5": fills(8.1, 8.5),
                "fills_3.9_4.1": fills(3.9, 4.1),
                "fills_3.5_3.9": fills(3.5, 3.9),
            }
        )
    return {"fee_bps_quantiles": q, "units_check": sorted(monthly, key=lambda r: r["month"])}


def report(args: argparse.Namespace) -> dict[str, Any]:
    dates = parse_date_spec(args.dates)
    out: dict[str, Any] = {"dates": args.dates, "bands_bps": list(BANDS), "horizons_s": list(HORIZONS_S), "coins": {}}
    for coin in parse_symbol_spec(args.coins):
        parts, hists = [], []
        for date in dates:
            bands_path, hist_path = day_files(args.out, coin, date)
            if bands_path.exists():
                parts.append(pl.read_parquet(bands_path).with_columns(pl.lit(date).alias("date")))
                hists.append(pl.read_parquet(hist_path).with_columns(pl.lit(date).alias("date")))
        assert parts, f"no days written for {coin}; run without --report first"
        days = pl.concat(parts, how="diagonal")
        hist = pl.concat(hists, how="diagonal")
        paid = days.filter(pl.col("band") != "0").group_by("date").agg(pl.col("fills").sum()).filter(pl.col("fills") > 0).sort("date")
        rollout = paid["date"][0] if paid.height else None
        per_day = (
            days.group_by("date")
            .agg(pl.col("fills").sum().alias("all"), pl.col("fills").filter(pl.col("band") != "0").sum().alias("paid"))
            .sort("date")
        )
        share = per_day.with_columns((pl.col("paid") / pl.col("all")).alias("share"))
        live = days.filter(pl.col("date") >= rollout) if rollout else days.head(0)
        recent = sorted(live["date"].unique().to_list())[-args.recent_days :]
        out["coins"][coin] = {
            "dates_written": len(parts),
            "rollout_first_fee_date": rollout,
            "first_date_fee_share_above_1pct": next((d for d, s in share.select("date", "share").iter_rows() if s >= 0.01), None),
            "fee_paying_share_by_month": {
                m: _sum(g, "paid") / _sum(g, "all")
                for (m,), g in share.with_columns(pl.col("date").str.slice(0, 6).alias("m")).group_by("m", maintain_order=True)
            },
            **fee_summary(hist.filter(pl.col("date") >= rollout) if rollout else hist.head(0), live),
            "since_rollout": band_table(live) if rollout else None,
            f"last_{args.recent_days}_days": band_table(live.filter(pl.col("date").is_in(recent))) if rollout else None,
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.report is not None:
        out = report(args)
        for coin, r in out["coins"].items():
            t = r["since_rollout"] or {}
            adv = " ".join(f"{b} {t[b]['adv_1s']:+.2f}" for b in BANDS if b in t)
            print(f"{coin}: rollout {r['rollout_first_fee_date']}; adverse move at 1 s by fee band (bps): {adv}")
        return 0
    hype = hype_usd(args.candles_dir)
    for coin in parse_symbol_spec(args.coins):
        for date in parse_date_spec(args.dates):
            if write_day(args, hype, coin, date):
                print(f"{coin} {date}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
