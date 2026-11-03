"""S1 in hftbacktest against the block-accurate engine, on the same days (``marketimmune.sim.hft_baseline``).

    python -m marketimmune.cli.hft_baseline --coin SOL --dates 20251201..20251231 --out eval/sim_hft_sol.json

Needs the ``sim`` extra (hftbacktest) and the near-touch L4 events (``build_albers_silver --mbo``).
Runs S1 through hftbacktest (risk-averse and power-probability queues) and through the engine
(``fifo`` and ``risk_averse``). The engine also runs with ``l2_crossing_fills``, the rule an L2
backtester applies: a post-only order resting through our quote fills it. With that rule the
engine should land near hftbacktest; the gap without it is what HyperCore's post-only rejection is
worth to a maker. Same quote size, position limit, fees and attribution as ``simulate_quotes``;
the engine's delay is hftbacktest's feed plus order latency.
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

from marketimmune.cli.simulate_quotes import LOT, quote_qty, summarise
from marketimmune.logger import init_logger
from marketimmune.sim.attribution import COMPONENTS, PX_SCALE, Costs, attribute_day
from marketimmune.sim.data import load_day
from marketimmune.sim.engine import QUEUE_MODELS, MakerSpec, simulate_day
from marketimmune.sim.hft_baseline import HFT_QUEUE_MODELS, day_events, run_touch_quoter
from marketimmune.sim.strategies import TouchQuoter
from marketimmune.utils import parse_date_spec

logger = init_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--feed-ms", type=float, default=100.0, help="from a block to its data reaching us")
    parser.add_argument("--entry-ms", type=float, default=100.0, help="from sending an order to it reaching the book")
    parser.add_argument("--step-ms", type=float, default=100.0, help="hftbacktest's decision interval")
    parser.add_argument("--quote-usd", type=float, default=1_000.0)
    parser.add_argument("--max-quotes", type=float, default=5.0)
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--horizon-s", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path, default=Path("eval/sim_hft.json"))
    parser.add_argument(
        "--day-dir",
        type=Path,
        default=Path("data/gold/hyperliquid/sim_hft"),
        help="each day's rows are kept here (<COIN>/<date>.json) and reused, so a month can run a few days per call",
    )
    parser.add_argument("--max-days", type=int, default=0, help="simulate at most this many new days, then summarise what exists")
    return parser.parse_args(argv)


def run_day(args: argparse.Namespace, date: str) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    book = load_day(args.lake_root, coin, date)
    qty = quote_qty(book, coin, args.quote_usd)
    s1 = TouchQuoter(max_position=args.max_quotes * qty)
    feed_ns, entry_ns = round(args.feed_ms * 1e6), round(args.entry_ms * 1e6)
    results = []
    for crossing in (False, True):
        specs = [MakerSpec(f"S1/{q}{'+l2_crossing' if crossing else ''}", s1, q, qty) for q in QUEUE_MODELS]
        results += simulate_day(book, specs, delay_ns=feed_ns + entry_ns, l2_crossing_fills=crossing)
    events = day_events(book, feed_ns=feed_ns)
    tick = float(np.diff(np.unique(book.bid_px[:, 0])).min()) / PX_SCALE
    for queue in HFT_QUEUE_MODELS:
        results.append(
            run_touch_quoter(
                events,
                queue=queue,
                qty=qty,
                max_position=args.max_quotes * qty,
                tick=tick,
                lot=LOT[coin],
                entry_ns=entry_ns,
                step_ns=round(args.step_ms * 1e6),
            )
        )
    costs = Costs(args.maker_fee_bps, args.taker_fee_bps, round(args.horizon_s * 1e9))
    rows = [
        {"day": date, "maker": r.name, "qty": qty, **attribute_day(r, book.l2_ts, book.bid_px[:, 0], book.ask_px[:, 0], costs)}
        for r in results
    ]
    logger.info(f"{date}: " + ", ".join(f"{r['maker']} {r['fills']}" for r in rows))
    return rows


def day_path(args: argparse.Namespace, date: str) -> Path:
    path: Path = Path(args.day_dir) / str(args.coin).upper() / f"{date}.json"
    return path


def cached_day(args: argparse.Namespace, date: str) -> list[dict[str, Any]]:
    """``run_day``, kept in ``--day-dir``: a day already there is read, not simulated again."""
    path = day_path(args, date)
    if path.exists():
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return rows
    rows = run_day(args, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(rows, default=float), encoding="utf-8")
    tmp.replace(path)
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dates = list(parse_date_spec(args.dates))
    todo = [d for d in dates if not day_path(args, d).exists()]
    if args.max_days:
        todo = todo[: args.max_days]
    if todo:
        with ProcessPoolExecutor(min(args.workers, len(todo)), mp_context=get_context("spawn")) as pool:
            list(pool.map(cached_day, [args] * len(todo), todo))
    done = [d for d in dates if day_path(args, d).exists()]
    frame = pd.DataFrame([row for d in done for row in cached_day(args, d)])
    makers = {name: summarise(daily.sort_values("day")) for name, daily in frame.groupby("maker", sort=False)}
    result = {
        "coin": args.coin.upper(),
        "dates": args.dates,
        "days_done": len(done),
        "days_missing": [d for d in dates if d not in done],
        "settings": {k: v for k, v in vars(args).items() if k not in ("lake_root", "out", "workers", "day_dir", "max_days")},
        "makers": makers,
        "daily": frame.to_dict(orient="records"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    for name, s in makers.items():
        parts = " ".join(f"{c} {s[f'{c}_bps']:+.2f}" for c in COMPONENTS)
        print(f"{name:<32} {s['fills']:>8} fills  {parts} bps")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
