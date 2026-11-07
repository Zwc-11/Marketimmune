"""Range trading on the recorded mids (``paper.range_study``): mean reversion by horizon, a sweep
of the band maker on the selection hours, and one scored test on held-out hours.

    python -m marketimmune.cli.paper_range study --mids <seg>/mids.parquet ... --out eval/paper/range_vr.json
    python -m marketimmune.cli.paper_range sweep --mids ... --until 2026-11-07T04:09 --out eval/paper/range_sweep.json
    python -m marketimmune.cli.paper_range test --mids ... --from 2026-11-07T04:09 --k 1 --horizon 30 --out ...

Selection and held-out hours are cut by time; the held-out run starts its averages three hours
earlier so that every held-out decision has a warm volatility estimate (from past data only).
Each result comes with the same rule on hour-shuffled copies of the same hours (the null).
"""

from __future__ import annotations

import argparse
import itertools
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.paper.range_study import Band, hour_shuffle, load_mids, run_all, second_series, variance_ratios

WARM_MS = 3 * 3600 * 1000


def _ms(text: str) -> int:
    return int(pd.Timestamp(text, tz="UTC").value // 1_000_000)


def _cut(series: dict[str, pd.Series], lo: int | None, hi: int | None) -> dict[str, pd.Series]:
    out = {}
    for c, s in series.items():
        m = np.ones(len(s), bool)
        if lo is not None:
            m &= s.index.to_numpy() >= lo
        if hi is not None:
            m &= s.index.to_numpy() < hi
        out[c] = s[m]
    return out


def _hours(series: dict[str, pd.Series], from_ms: int | None = None) -> float:
    s = next(iter(series.values()))
    ok = s.notna().to_numpy().copy()
    if from_ms is not None:
        ok &= s.index.to_numpy() >= from_ms
    return float(ok.sum() / 3600)


def _summary(df: pd.DataFrame, hours: float) -> dict[str, Any]:
    if not len(df):
        return {"trades": 0, "usd_per_hour": 0.0}
    return {
        "trades": len(df),
        "gross_bps": float(df["gross_bps"].mean()),
        "net_bps": float(df["net_bps"].mean()),
        "usd_per_hour": float(df["usd"].sum() / hours),
        "exits": df["exit"].value_counts().to_dict(),
        "minutes_held_median": float(((df["t_out"] - df["t_in"]) / 60_000).median()),
    }


def _job(args: tuple[dict[str, pd.Series], Band, int | None, float]) -> dict[str, Any]:
    series, p, from_ms, hours = args
    return {"setting": p.label(), **asdict(p), **_summary(run_all(series, p, from_ms), hours)}


def _shuffled(series: dict[str, pd.Series], seed: int) -> dict[str, pd.Series]:
    return {c: hour_shuffle(s, 1000 * seed + j) for j, (c, s) in enumerate(sorted(series.items()))}


def cmd_study(a: argparse.Namespace) -> dict[str, Any]:
    series = second_series(load_mids(a.mids))
    vr = variance_ratios(series, draws=a.draws)
    lx = {c: np.log(s.to_numpy(float)) for c, s in series.items()}
    vol = {}
    for c, x in lx.items():
        r1 = x[1:] - x[:-1]
        r60 = x[60::60] - x[:-60:60]
        vol[c] = {"sd_1s_bps": float(np.nanstd(r1) * 1e4), "sd_1min_bps": float(np.nanstd(r60) * 1e4)}
    return {"hours": _hours(series), "variance_ratios": vr.to_dict("records"), "volatility": vol}


def cmd_sweep(a: argparse.Namespace) -> dict[str, Any]:
    series = _cut(second_series(load_mids(a.mids)), None, _ms(a.until))
    hours = _hours(series)
    grid = [
        Band(k=k, horizon_min=h, centre_halflife_min=c, stop=st, max_min=m, quote_usd=a.quote_usd)
        for k, h, c, st, m in itertools.product([0.5, 1.0, 1.5, 2.0], [15, 30, 60], [15, 60], [1.5, 3.0], [30, 120])
    ]
    with ProcessPoolExecutor(a.workers) as ex:
        real = list(ex.map(_job, [(series, p, None, hours) for p in grid]))
        null = []
        for seed in range(a.null_draws):
            sh = _shuffled(series, seed)
            null.append(list(ex.map(_job, [(sh, p, None, hours) for p in grid])))
    best_null = [max(r["usd_per_hour"] for r in draw) for draw in null]
    for j, r in enumerate(real):
        r["null_gross_bps"] = float(np.nanmean([draw[j].get("gross_bps", np.nan) for draw in null]))
        r["null_usd_per_hour"] = float(np.mean([draw[j]["usd_per_hour"] for draw in null]))
    return {"hours": hours, "until": a.until, "settings": real, "best_of_null_usd_per_hour": best_null}


def cmd_test(a: argparse.Namespace) -> dict[str, Any]:
    start = _ms(a.from_)
    series = _cut(second_series(load_mids(a.mids)), start - WARM_MS, None)
    hours = _hours(series, start)
    p = Band(k=a.k, horizon_min=a.horizon, centre_halflife_min=a.centre, stop=a.stop, max_min=a.max_min, quote_usd=a.quote_usd)
    df = run_all(series, p, start)
    out: dict[str, Any] = {"from": a.from_, "hours": hours, "setting": p.label(), **asdict(p), **_summary(df, hours)}
    if len(df):
        block = (df["t_in"] - start) // 3_600_000
        per_hour = df.groupby(block)["usd"].sum().reindex(range(int(np.ceil(hours))), fill_value=0.0).to_numpy()
        rng = np.random.default_rng(0)
        boot = [rng.choice(per_hour, len(per_hour)).mean() for _ in range(10_000)]
        out["usd_per_hour_ci95"] = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
        tb = rng.choice(df["net_bps"].to_numpy(), (10_000, len(df))).mean(1)
        out["net_bps_ci95"] = [float(np.percentile(tb, 2.5)), float(np.percentile(tb, 97.5))]
        out["by_coin"] = (
            df.groupby("coin").agg(trades=("usd", "size"), net_bps=("net_bps", "mean"), usd=("usd", "sum")).reset_index().to_dict("records")
        )
    with ProcessPoolExecutor(a.workers) as ex:
        null = list(ex.map(_job, [(_shuffled(series, s), p, start, hours) for s in range(a.null_draws)]))
    ng = np.array([r.get("gross_bps", np.nan) for r in null])
    nu = np.array([r["usd_per_hour"] for r in null])
    out["null"] = {
        "draws": a.null_draws,
        "gross_bps_mean": float(np.nanmean(ng)),
        "usd_per_hour_mean": float(nu.mean()),
        "share_gross_at_least_real": float(np.nanmean(ng >= out.get("gross_bps", np.inf))),
        "share_usd_at_least_real": float((nu >= out["usd_per_hour"]).mean()),
    }
    for fee in a.fee_scenarios:
        q = replace(p, maker_fee_bps=fee, taker_fee_bps=fee + 3.0)
        out.setdefault("fee_scenarios", []).append({"maker_fee_bps": fee, **_summary(run_all(series, q, start), hours)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("study", "sweep", "test"):
        sp = sub.add_parser(name)
        sp.add_argument("--mids", type=Path, nargs="+", required=True)
        sp.add_argument("--out", type=Path, required=True)
        sp.add_argument("--workers", type=int, default=2)
        sp.add_argument("--quote-usd", type=float, default=500.0)
    sub.choices["study"].add_argument("--draws", type=int, default=2000)
    sub.choices["sweep"].add_argument("--until", required=True)
    sub.choices["sweep"].add_argument("--null-draws", type=int, default=3)
    t = sub.choices["test"]
    t.add_argument("--from", dest="from_", required=True)
    t.add_argument("--k", type=float, default=1.0)
    t.add_argument("--horizon", type=float, default=30.0)
    t.add_argument("--centre", type=float, default=60.0)
    t.add_argument("--stop", type=float, default=3.0)
    t.add_argument("--max-min", type=float, default=120.0)
    t.add_argument("--null-draws", type=int, default=40)
    t.add_argument("--fee-scenarios", type=float, nargs="*", default=[1.5, 1.2, 0.8, 0.4, 0.0])
    a = ap.parse_args(argv)
    result = {"study": cmd_study, "sweep": cmd_sweep, "test": cmd_test}[a.cmd](a)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, list)}, indent=1, default=float)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
