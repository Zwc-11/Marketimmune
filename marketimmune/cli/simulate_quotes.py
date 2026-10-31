"""Block-accurate maker PnL: our quotes injected into the rebuilt book (v3 plan, the economic test).

    python -m marketimmune.cli.simulate_quotes --coin SOL --dates 20251201..20251231 --out eval/sim_sol.json

Needs Silver L2 with the near-touch L4 events (``build_albers_silver --mbo``) and Binance
aggTrades. Runs two strategies under both queue models of ``marketimmune.sim.engine``:

* S1 (inventory only): join the best bid and ask;
* ``stale``: S1, but pull a side while Binance has moved ``--stale-bps`` against it since the
  Hyperliquid mid last changed.

An action decided after a block lands ``--delay-ms`` later. Each day starts flat and is
flattened at its last book, so days run in parallel. The PnL split (spread, adverse selection at
``--horizon-s``, inventory, fees, the closing hedge) is ``marketimmune.sim.attribution``. Pairs are
compared by day, as in ``simulate_policy``.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.logger import init_logger
from marketimmune.models.compare import stationary_bootstrap_ci
from marketimmune.sim.attribution import BPS, COMPONENTS, PX_SCALE, Costs, attribute_day
from marketimmune.sim.data import cex_gaps, load_day
from marketimmune.sim.engine import FIFO, QUEUE_MODELS, DayBook, MakerSpec, Strategy, simulate_day
from marketimmune.sim.pnl import compare_policies
from marketimmune.sim.strategies import StaleQuotePuller, TouchQuoter
from marketimmune.utils import parse_date_spec

logger = init_logger(__name__)

LOT = {"BTC": 1e-5, "ETH": 1e-4, "SOL": 1e-2}  # Hyperliquid size decimals
STRATEGIES = ("S1", "stale")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--binance-dir", type=Path, default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--delay-ms", type=float, default=200.0, help="from a block to our action landing in the book")
    parser.add_argument("--cex-latency-ms", type=float, default=300.0, help="Binance feed latency")
    parser.add_argument("--stale-bps", type=float, default=2.0)
    parser.add_argument("--quote-usd", type=float, default=1_000.0, help="quote size, at the day's first mid")
    parser.add_argument("--max-quotes", type=float, default=5.0, help="position limit in quote sizes")
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--horizon-s", type=float, default=1.0, help="adverse-selection window")
    parser.add_argument("--workers", type=int, default=4, help="days simulated in parallel")
    parser.add_argument("--out", type=Path, default=Path("eval/sim_quotes.json"))
    return parser.parse_args(argv)


def quote_qty(book: DayBook, coin: str, quote_usd: float) -> float:
    """``quote_usd`` at the day's first mid, in whole lots."""
    lot = LOT[coin]
    mid0 = (book.bid_px[0, 0] + book.ask_px[0, 0]) / 2.0 / PX_SCALE
    return float(max(round(quote_usd / mid0 / lot), 1) * lot)


def run_day(args: argparse.Namespace, date: str) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    book = load_day(args.lake_root, coin, date)
    qty = quote_qty(book, coin, args.quote_usd)
    bid_gap, ask_gap = cex_gaps(book, args.binance_dir, coin, date, latency_ms=args.cex_latency_ms)
    s1 = TouchQuoter(max_position=args.max_quotes * qty)
    strategies: dict[str, Strategy] = {"S1": s1, "stale": StaleQuotePuller(s1, bid_gap, ask_gap, args.stale_bps)}
    specs = [MakerSpec(f"{name}/{queue}", strategies[name], queue, qty) for name in STRATEGIES for queue in QUEUE_MODELS]
    results = simulate_day(book, specs, delay_ns=round(args.delay_ms * 1e6))
    costs = Costs(args.maker_fee_bps, args.taker_fee_bps, round(args.horizon_s * 1e9))
    rows = [
        {"day": date, "maker": r.name, "qty": qty, **attribute_day(r, book.l2_ts, book.bid_px[:, 0], book.ask_px[:, 0], costs)}
        for r in results
    ]
    logger.info(f"{date}: " + ", ".join(f"{r['maker']} {r['fills']} fills {r['pnl_usd']:+.0f} USD" for r in rows))
    return rows


def summarise(daily: pd.DataFrame) -> dict[str, Any]:
    """Whole-period USD and bps per filled dollar by component, and the daily PnL's interval."""
    notional = float(daily["notional_usd"].sum())
    out: dict[str, Any] = {"days": len(daily), "fills": int(daily["fills"].sum()), "notional_usd": notional}
    for c in COMPONENTS:
        usd = float(daily[f"{c}_usd"].sum())
        out[f"{c}_usd"] = usd
        out[f"{c}_bps"] = usd / notional * BPS if notional > 0 else 0.0
    pnl = daily["pnl_usd"].to_numpy(dtype=np.float64)
    out["daily_pnl_usd_mean"] = float(pnl.mean())
    if pnl.size >= 3:
        out["daily_pnl_usd_ci95"] = list(stationary_bootstrap_ci(pnl))
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dates = parse_date_spec(args.dates)
    with ProcessPoolExecutor(min(args.workers, len(dates)), mp_context=get_context("spawn")) as pool:
        frame = pd.DataFrame([row for rows in pool.map(run_day, [args] * len(dates), dates) for row in rows])
    by_maker = {name: group.sort_values("day") for name, group in frame.groupby("maker")}
    result: dict[str, Any] = {
        "coin": args.coin.upper(),
        "dates": args.dates,
        "settings": {k: v for k, v in vars(args).items() if k not in ("lake_root", "binance_dir", "out", "workers")},
        "makers": {name: summarise(daily) for name, daily in by_maker.items()},
        "stale_vs_S1": {q: compare_policies(by_maker[f"S1/{q}"], by_maker[f"stale/{q}"]) for q in QUEUE_MODELS},
        "fifo_vs_risk_averse_S1": compare_policies(by_maker["S1/risk_averse"], by_maker[f"S1/{FIFO}"]),
        "daily": frame.to_dict(orient="records"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    for name, s in result["makers"].items():
        parts = " ".join(f"{c} {s[f'{c}_bps']:+.2f}" for c in COMPONENTS)
        print(f"{name:<18} {s['fills']:>8} fills {s['notional_usd'] / 1e6:8.2f}M USD  {parts} bps  {s['total_usd']:+,.0f} USD")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
