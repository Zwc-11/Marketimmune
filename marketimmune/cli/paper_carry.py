"""Funding carry on Hyperliquid (candidate 1 of
``docs/preregistration/paper-five-candidates-20261107.md``): short the perp and hold the same
dollars of the coin on Hyperliquid spot, so the price cancels and the position collects funding.

    python -m marketimmune.cli.paper_carry --days 60 --out eval/paper/carry_20261107.json

Per hour and $1 hedged: funding received by the short (the hourly rate) minus the change of the
perp's premium over the oracle (the hedge's basis risk; the spot leg is taken to track the oracle).
Equal dollars in each coin of the universe, entered once and held; a maker round trip on both legs
(perp 1.5 bp, spot 4 bp, in and out) is charged once. Reported for each half of the window and
overall: net bp, % a year, daily mean and sd, t-statistic of the daily PnL, worst day.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

API = "https://api.hyperliquid.xyz/info"
UNIVERSE = ("BTC", "ETH", "SOL", "HYPE", "AVAX")  # spot: UBTC, UETH, USOL, HYPE, UAVAX
ROUND_TRIP_BPS = {"maker": 2 * (1.5 + 4.0), "taker": 2 * (4.5 + 7.0)}


def _post(body: dict[str, Any]) -> Any:
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def funding_history(coins: tuple[str, ...], start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = []
    for c in coins:
        t = start_ms
        while t < end_ms:
            batch = _post({"type": "fundingHistory", "coin": c, "startTime": t, "endTime": end_ms})
            if not batch:
                break
            rows += [(c, x["time"], float(x["fundingRate"]), float(x["premium"])) for x in batch]
            t = batch[-1]["time"] + 1
            if len(batch) < 500:
                break
            time.sleep(0.2)
    f = pd.DataFrame(rows, columns=["coin", "t", "rate", "premium"]).drop_duplicates(["coin", "t"])
    f["hour"] = pd.to_datetime(f["t"], unit="ms").dt.floor("h")
    return f


def carry(f: pd.DataFrame, coins: tuple[str, ...], execution: str = "maker") -> dict[str, Any]:
    r = f.pivot(index="hour", columns="coin", values="rate")[list(coins)]
    p = f.pivot(index="hour", columns="coin", values="premium")[list(coins)]
    hourly = (r - p.diff().fillna(0.0)).mean(axis=1) * 1e4  # bp per $ hedged
    days = len(hourly) / 24
    daily = hourly.groupby(hourly.index.floor("D")).sum()
    net = float(hourly.sum() - ROUND_TRIP_BPS[execution])
    return {
        "from": str(hourly.index[0]),
        "to": str(hourly.index[-1]),
        "days": days,
        "execution": execution,
        "gross_bps": float(hourly.sum()),
        "net_bps": net,
        "net_pct_a_year": net / 100 * 365 / days,
        "daily_mean_bps": float(daily.mean()),
        "daily_sd_bps": float(daily.std()),
        "t_daily": float(daily.mean() / daily.std() * np.sqrt(len(daily))),
        "worst_day_bps": float(daily.min()),
        "share_days_positive": float((daily > 0).mean()),
        "by_coin_pct_a_year": {c: float(r[c].mean() * 24 * 365 * 100) for c in coins},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--end", help="UTC end, default now")
    ap.add_argument("--cache", type=Path, default=Path("data/paper/funding_history.csv"))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    end = int(pd.Timestamp(a.end, tz="UTC").value // 1_000_000) if a.end else int(time.time() * 1000)
    f = funding_history(UNIVERSE, end - a.days * 86_400_000, end)
    a.cache.parent.mkdir(parents=True, exist_ok=True)
    f.to_csv(a.cache, index=False)
    hours = sorted(f["hour"].unique())
    mid = hours[len(hours) // 2]
    out = {
        "universe": list(UNIVERSE),
        "round_trip_bps": ROUND_TRIP_BPS,
        "halves": [
            carry(f[f["hour"] < mid], UNIVERSE),
            carry(f[f["hour"] >= mid], UNIVERSE),
        ],
        "all": {e: carry(f, UNIVERSE, e) for e in ROUND_TRIP_BPS},
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
