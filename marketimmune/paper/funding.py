"""Perp funding on paper positions: what a held Hyperliquid position pays or receives.

Hyperliquid settles funding every hour: a position of ``size`` coins pays
``size x oracle price x rate`` (longs pay shorts when the rate is positive). The engine
does not book it, so the report does, from the hourly rates of ``fundingHistory`` and each
strategy's position in ``equity.jsonl`` at the last minute before each funding time. The
position is valued at the mid, not the oracle price; the two differ by the basis, a few bps.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

INFO_URL = "https://api.hyperliquid.xyz/info"
Post = Callable[[dict[str, Any]], Any]


def post_info(body: dict[str, Any]) -> Any:
    request = urllib.request.Request(INFO_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def fetch_funding(coins: Iterable[str], start_ms: int, end_ms: int, post: Post = post_info) -> dict[str, list[tuple[int, float]]]:
    """Each coin's ``(time ms, hourly rate)`` from ``start_ms`` to ``end_ms``, paging as the
    endpoint returns at most 500 rows a call."""
    out: dict[str, list[tuple[int, float]]] = {}
    for coin in coins:
        rows: list[tuple[int, float]] = []
        cursor = start_ms
        while cursor <= end_ms:
            page = post({"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end_ms})
            if not page:
                break
            rows += [(int(r["time"]), float(r["fundingRate"])) for r in page if start_ms <= int(r["time"]) <= end_ms]
            last = int(page[-1]["time"])
            if len(page) < 500 or last < cursor:
                break
            cursor = last + 1
        out[coin] = sorted(dict(rows).items())
    return out


def funding_for_run(run: Path, post: Post = post_info) -> dict[str, list[tuple[int, float]]]:
    """The rates over a run's minutes, cached beside it as ``funding.json``."""
    cache = run / "funding.json"
    if cache.exists():
        return {coin: [(int(t), float(r)) for t, r in rows] for coin, rows in json.loads(cache.read_text()).items()}
    eq = pd.read_json(run / "equity.jsonl", lines=True)
    rates = fetch_funding(sorted(eq["coin"].unique()), int(eq["t_ms"].min()), int(eq["t_ms"].max()), post)
    cache.write_text(json.dumps(rates))
    return rates


def funding_payments(equity: pd.DataFrame, rates: dict[str, list[tuple[int, float]]]) -> pd.DataFrame:
    """``coin, strategy, funding_usd, settlements``: the sum of ``-position_usd x rate`` over
    the funding times inside the run, each with the position of the last snapshot at or before
    it. A funding time before the first snapshot or after the last is outside the run."""
    rows: list[dict[str, Any]] = []
    for (coin, strategy), g in equity.groupby(["coin", "strategy"]):
        g = g.sort_values("t_ms")
        t = g["t_ms"].to_numpy(dtype=np.int64)
        pos = g["position_usd"].to_numpy(dtype=np.float64)
        paid, n = 0.0, 0
        for when, rate in rates.get(str(coin), []):
            if when < t[0] or when > t[-1]:
                continue
            i = int(np.searchsorted(t, when, side="right")) - 1
            paid -= pos[i] * rate
            n += 1
        rows.append({"coin": coin, "strategy": strategy, "funding_usd": paid, "settlements": n})
    return pd.DataFrame(rows, columns=["coin", "strategy", "funding_usd", "settlements"])
