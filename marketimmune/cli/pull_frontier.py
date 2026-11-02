"""S2/S3 across pull limits, against a time-shifted placebo (exploratory; block simulator).

    python -m marketimmune.cli.pull_frontier --coin SOL --dates 20251201..20251231 --out eval/sim_frontier_sol.json

``simulate_quotes`` runs S2 and S3 at one limit, fixed before the run (pull a side while the
quote-time q10 of its next fill is below -2 bps). Both lost less than S1 mostly by trading 5-7% of
its volume. This asks two things at once, on the same days and book:

- **the frontier:** S2 and S3 at each ``--limits``, so volume can be traded against the loss per
  filled dollar;
- **whether the signal or the pulling helps:** ``s2_shifted`` pulls on S2's own q10 series rolled
  by half the day's L2 rows. It keeps how often and for how long S2 pulls but not when, so it
  trades a similar volume with no information. S2 beating it at the same limit is the model's
  value; S2 matching it means pulling alone did the work.

Engine, costs and S1 are ``simulate_quotes``'s; each day's rows are kept in ``--day-dir`` and
reused, and ``--max-days`` bounds a call.
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
import pyarrow.parquet as pq

from marketimmune.cli.simulate_quotes import quote_qty, summarise
from marketimmune.logger import init_logger
from marketimmune.sim.attribution import COMPONENTS, Costs, attribute_day
from marketimmune.sim.data import load_day
from marketimmune.sim.engine import FIFO, MakerSpec, Strategy, simulate_day
from marketimmune.sim.pnl import compare_policies
from marketimmune.sim.signals import quote_signals_path
from marketimmune.sim.strategies import QuantilePuller, TouchQuoter
from marketimmune.utils import parse_date_spec, split_csv

logger = init_logger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--signals-dir", type=Path, default=Path("data/gold/hyperliquid/quote_signals"))
    parser.add_argument("--limits", default="0.5,1,2,3,5", help="pull when q10 < -limit (bps)")
    parser.add_argument("--models", default="s2,s3")
    parser.add_argument("--queue", default=FIFO)
    parser.add_argument("--delay-ms", type=float, default=200.0)
    parser.add_argument("--quote-usd", type=float, default=1_000.0)
    parser.add_argument("--max-quotes", type=float, default=5.0)
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--horizon-s", type=float, default=1.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--day-dir", type=Path, default=Path("data/gold/hyperliquid/sim_frontier"))
    parser.add_argument("--max-days", type=int, default=0, help="simulate at most this many new days, then summarise what exists")
    parser.add_argument("--out", type=Path, default=Path("eval/sim_frontier.json"))
    return parser.parse_args(argv)


def limit_name(model: str, limit: float) -> str:
    return f"{model}@{limit:g}"


def run_day(args: argparse.Namespace, date: str) -> list[dict[str, Any]]:
    coin = args.coin.upper()
    book = load_day(args.lake_root, coin, date)
    qty = quote_qty(book, coin, args.quote_usd)
    s1 = TouchQuoter(max_position=args.max_quotes * qty)
    strategies: dict[str, Strategy] = {"S1": s1}
    path = quote_signals_path(args.signals_dir, coin, date)
    if path.exists():
        table = pq.read_table(path)
        assert np.array_equal(table["ts_ns"].to_numpy(), book.l2_ts), f"{path}: signals are not on the simulator's L2 rows"
        half = book.l2_ts.size // 2
        for model in split_csv(args.models):
            if f"{model}_q10_bid" not in table.column_names:
                continue
            q10 = [table[f"{model}_q10_{side}"].to_numpy().astype(np.float64) for side in ("bid", "ask")]
            for limit in (float(x) for x in split_csv(args.limits)):
                strategies[limit_name(model, limit)] = QuantilePuller(s1, q10[0], q10[1], limit)
                if model == "s2":
                    strategies[limit_name("s2_shifted", limit)] = QuantilePuller(s1, np.roll(q10[0], half), np.roll(q10[1], half), limit)
    specs = [MakerSpec(name, strategy, args.queue, qty) for name, strategy in strategies.items()]
    results = simulate_day(book, specs, delay_ns=round(args.delay_ms * 1e6))
    costs = Costs(args.maker_fee_bps, args.taker_fee_bps, round(args.horizon_s * 1e9))
    rows = [
        {"day": date, "maker": r.name, "qty": qty, **attribute_day(r, book.l2_ts, book.bid_px[:, 0], book.ask_px[:, 0], costs)}
        for r in results
    ]
    logger.info(f"{date}: {len(rows)} makers")
    return rows


def day_path(args: argparse.Namespace, date: str) -> Path:
    path: Path = Path(args.day_dir) / str(args.coin).upper() / f"{date}.json"
    return path


def cached_day(args: argparse.Namespace, date: str) -> list[dict[str, Any]]:
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


def report(args: argparse.Namespace, frame: pd.DataFrame) -> dict[str, Any]:
    by = {name: g.sort_values("day") for name, g in frame.groupby("maker")}
    out: dict[str, Any] = {
        "coin": args.coin.upper(),
        "dates": args.dates,
        "settings": {k: v for k, v in vars(args).items() if k not in ("lake_root", "signals_dir", "out", "workers", "day_dir", "max_days")},
        "makers": {name: summarise(g) for name, g in by.items()},
        "vs_S1": {name: compare_policies(by["S1"], g) for name, g in by.items() if name != "S1"},
        "s2_vs_shifted": {},
    }
    for limit in (float(x) for x in split_csv(args.limits)):
        a, b = limit_name("s2", limit), limit_name("s2_shifted", limit)
        if a in by and b in by:
            out["s2_vs_shifted"][f"{limit:g}"] = compare_policies(by[b], by[a])
    return out


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
    result = {**report(args, frame), "days_done": len(done), "days_missing": [d for d in dates if d not in done]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    for name, s in result["makers"].items():
        parts = " ".join(f"{c} {s[f'{c}_bps']:+.2f}" for c in COMPONENTS)
        print(f"{name:<18} {s['fills']:>8} fills  {parts} bps  {s['daily_pnl_usd_mean']:+,.0f} USD/day")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
