"""Tune each paper strategy's parameter on recorded runs, and say how well the choice holds out.

    python -m marketimmune.cli.paper_tune \\
        --chain night=data/paper/seg1-20261106T0441/raw~,data/paper/seg2-20261106T0448/raw,... \\
        --chain live=data/paper/live/seg-20261106T1606/raw,data/paper/live/seg-20261106T1806/raw \\
        --clock live --config 250x4 --config 500x2 --budget-usd 5000 \\
        --work data/paper/tune --out eval/paper/tune.json --md eval/paper/tune.md

Every strategy in the grid (``GRID``: each family over a range of its parameter) runs in one engine
per sizing config (quote USD x quotes a coin may hold, under ``--budget-usd`` per strategy), on
every recorded segment. A chain's segments run in order and share the model's state, as the live
run's do; a segment ending in ``~`` only warms the state up and is not scored. ``--clock`` names the
chains recorded on a machine whose clock was off: their receive times are corrected from
Coinbase's timestamps (``paper.live.clock_offsets``).

Selection, per family, over its parameter values and the sizing configs that Hyperliquid's rate
limit allows (``--max-orders-per-usd``): Hyperliquid allows one order request per USD traded since
the address began, after a 10,000-request buffer, and cancels twice that; past it, one request every
10 s. A maker's order actions are half orders and half cancels (50.0-50.2% orders in the journal of
2026-11-06), so its orders are taken as half its actions; a taker's actions are all orders. Among the
settings under the limit, the one with the most PnL over all scored segments is ``best``
(in-sample, optimistic). Honest estimate: leave one segment
out, pick on the others, score the pick on the one left out, over every segment (``cv``). A family
whose ``cv`` is far below its ``best``, or whose pick changes from fold to fold, is fitting noise.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.logger import init_logger

logger = init_logger(__name__)

GRID: dict[str, tuple[str, ...]] = {
    "touch": ("touch",),
    "improve": ("improve",),
    "gap": tuple(f"gap@{v}" for v in (0.1, 0.15, 0.25, 0.35, 0.5, 0.75, 1, 1.5)),
    "improve+gap": tuple(f"improve+gap@{v}" for v in (0.1, 0.15, 0.25, 0.35, 0.5, 0.75, 1, 1.5)),
    "zgap": tuple(f"zgap@{v}" for v in (0.1, 0.25, 0.4, 0.6, 0.8, 1, 1.5)),
    "hawkes": tuple(f"hawkes@{v}" for v in (1.5, 2, 2.5, 3, 4, 6)),
    "kelly": tuple(f"kelly@{v}" for v in (0.25, 0.5, 0.75, 1, 1.5, 2)),
    "reservation": tuple(f"reservation@{v}" for v in (0.5, 1, 2, 3, 5, 8)),
    "model": tuple(f"model@{v}" for v in (0.25, 0.5, 1, 1.5)),
    "taker": tuple(f"taker@{v}" for v in (3, 4, 6, 8, 10, 15)),
}


def family(strategy: str) -> str:
    return strategy.partition("@")[0]


@dataclass(frozen=True)
class Segment:
    chain: str
    raw: Path
    warmup: bool

    @property
    def name(self) -> str:
        return self.raw.parent.name


def parse_chain(spec: str) -> list[Segment]:
    name, _, paths = spec.partition("=")
    out = []
    for p in paths.split(","):
        warm = p.endswith("~")
        out.append(Segment(name, Path(p.rstrip("~")), warm))
    return out


def run_chain(segments: list[Segment], config: str, args: argparse.Namespace, strategies: tuple[str, ...]) -> None:
    quote, _, quotes = config.partition("x")
    state = args.work / config / segments[0].chain / "state"
    for seg in segments:
        out = args.work / config / seg.chain / seg.name
        if (out / "mids.parquet").exists():  # written only when a replay ends
            logger.info(f"{config} {seg.chain} {seg.name}: done already")
            continue
        cmd = [
            sys.executable,
            "-m",
            "marketimmune.cli.paper_trade",
            "--replay",
            str(seg.raw),
            "--out",
            str(out),
            "--state-dir",
            str(state),
            "--strategies",
            ",".join(strategies),
            "--quote-usd",
            quote,
            "--max-quotes",
            quotes,
            "--latency-ms",
            str(args.latency_ms),
            "--no-journal",
        ]
        if args.budget_usd is not None:
            cmd += ["--budget-usd", str(args.budget_usd)]
        if seg.chain in args.clock:
            cmd += ["--clock-offset", "coinbase"]
        logger.info(f"{config} {seg.chain} {seg.name}: replaying")
        with (args.work / config / seg.chain / f"{seg.name}.log").open("w") as log:
            subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT)


def results(
    segments: list[Segment], configs: list[str], work: Path, load: dict[tuple[str, str], list[float]] | None = None
) -> tuple[dict[str, float], dict[tuple[str, str], dict[str, float]]]:
    """Hours per scored segment, and PnL in USD per (config, strategy) per segment; ``load`` gathers
    [order actions, USD filled] per (config, strategy) over the scored segments."""
    hours: dict[str, float] = {}
    pnl: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    for config in configs:
        for seg in segments:
            if seg.warmup:
                continue
            key = f"{seg.chain}/{seg.name}"
            s = json.loads((work / config / seg.chain / seg.name / "summary.json").read_text())
            hours[key] = s["hours"]
            tot: dict[str, float] = defaultdict(float)
            for row in s["instances"]:
                tot[row["strategy"]] += row["equity"]
                if load is not None:
                    acc = load.setdefault((config, row["strategy"]), [0.0, 0.0])
                    acc[0] += row["actions"]
                    acc[1] += row["notional"]
            for strategy, usd in tot.items():
                pnl[(config, strategy)][key] = usd
    return hours, pnl


def select(
    hours: dict[str, float], pnl: dict[tuple[str, str], dict[str, float]], per_usd: dict[tuple[str, str], float], limit: float
) -> dict[str, Any]:
    segs = list(hours)
    total_h = sum(hours.values())
    by_family: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for config, strategy in pnl:
        if per_usd.get((config, strategy), 0.0) <= limit:
            by_family[family(strategy)].append((config, strategy))
    out: dict[str, Any] = {}
    for fam, options in sorted(by_family.items()):

        def total(o: tuple[str, str], keep: list[str]) -> float:
            return sum(pnl[o][k] for k in keep)

        best = max(options, key=lambda o: total(o, segs))
        folds = []
        held = 0.0
        for left in segs:
            train = [k for k in segs if k != left]
            pick = max(options, key=lambda o: total(o, train))
            held += pnl[pick][left]
            folds.append(
                {"left_out": left, "pick": f"{pick[1]} {pick[0]}", "left_out_usd_per_hour": round(pnl[pick][left] / hours[left], 1)}
            )
        ranked = sorted(options, key=lambda o: -total(o, segs))
        out[fam] = {
            "best": {
                "strategy": best[1],
                "config": best[0],
                "usd_per_hour": round(total(best, segs) / total_h, 1),
                "orders_per_usd": round(per_usd.get(best, 0.0), 2),
            },
            "best_per_segment_usd_per_hour": {k: round(pnl[best][k] / hours[k], 1) for k in segs},
            "cv_usd_per_hour": round(held / total_h, 1),
            "folds": folds,
            "picks_agree": len({f["pick"] for f in folds}) == 1,
            "all": [
                {
                    "strategy": o[1],
                    "config": o[0],
                    "usd_per_hour": round(total(o, segs) / total_h, 1),
                    "orders_per_usd": round(per_usd.get(o, 0.0), 2),
                }
                | {k: round(pnl[o][k] / hours[k], 1) for k in segs}
                for o in ranked
            ],
        }
    return out


def markdown(report: dict[str, Any]) -> str:
    segs = list(report["hours"])
    lines = [
        f"Segments (hours): {', '.join(f'{k} {v:.2f}' for k, v in report['hours'].items())}. "
        f"Configs: {', '.join(report['configs'])} (quote USD x quotes a coin), budget {report['budget_usd']} USD a strategy, "
        f"latency {report['latency_ms']} ms. Only settings at or under {report['max_orders_per_usd']} orders per USD filled "
        f"(Hyperliquid's rate limit) are selected; {report['excluded']} of {report['options']} were over it.",
        "",
        "| family | best (all segments) | config | orders per $ | $/h in-sample | $/h left-out (CV) | picks agree | "
        + " | ".join(segs)
        + " |",
        "|---|---|---|---:|---:|---:|---|" + "---:|" * len(segs),
    ]
    fams = sorted(report["families"].items(), key=lambda kv: -kv[1]["cv_usd_per_hour"])
    for fam, r in fams:
        b = r["best"]
        lines.append(
            f"| {fam} | `{b['strategy']}` | {b['config']} | {b['orders_per_usd']:.2f} | {b['usd_per_hour']:,.1f} | {r['cv_usd_per_hour']:,.1f} | {'yes' if r['picks_agree'] else 'no'} | "
            + " | ".join(f"{r['best_per_segment_usd_per_hour'][k]:,.1f}" for k in segs)
            + " |"
        )
    lines += ["", "Every setting within the rate limit, $ an hour (all segments, then each):", ""]
    lines += ["| strategy | config | orders per $ | all | " + " | ".join(segs) + " |", "|---|---|---:|---:|" + "---:|" * len(segs)]
    for _, r in fams:
        for o in r["all"]:
            lines.append(
                f"| `{o['strategy']}` | {o['config']} | {o['orders_per_usd']:.2f} | {o['usd_per_hour']:,.1f} | "
                + " | ".join(f"{o[k]:,.1f}" for k in segs)
                + " |"
            )
    lines += [
        "",
        "Over the rate limit (not selectable), best first:",
        "",
        "| strategy | config | orders per $ | $/h |",
        "|---|---|---:|---:|",
    ]
    for o in report["over_limit"]:
        lines.append(f"| `{o['strategy']}` | {o['config']} | {o['orders_per_usd']:.2f} | {o['usd_per_hour']:,.1f} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", action="append", required=True, help="name=raw1[~],raw2,... in order")
    parser.add_argument("--clock", default="", help="chains whose receive times to correct from Coinbase timestamps")
    parser.add_argument("--config", action="append", default=None, help="quote USD x quotes a coin, e.g. 250x4")
    parser.add_argument("--budget-usd", type=float, default=5_000.0)
    parser.add_argument("--latency-ms", type=int, default=200)
    parser.add_argument("--families", default=",".join(GRID))
    parser.add_argument("--strategies", default=None, help="an explicit list instead of the families' grids")
    parser.add_argument("--also", type=Path, action="append", default=[], help="earlier --work dirs (same chains) to select over too")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--max-orders-per-usd", type=float, default=1.0)
    args = parser.parse_args(argv)
    args.clock = {c for c in args.clock.split(",") if c}
    configs = args.config or ["250x4"]
    strategies = tuple(args.strategies.split(",")) if args.strategies else tuple(s for f in args.families.split(",") for s in GRID[f])
    chains = [parse_chain(c) for c in args.chain]
    for config in configs:
        for chain in chains:
            (args.work / config / chain[0].chain).mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.jobs) as pool:
        for f in [pool.submit(run_chain, chain, config, args, strategies) for config in configs for chain in chains]:
            f.result()
    segments = [s for chain in chains for s in chain]
    load: dict[tuple[str, str], list[float]] = {}
    hours, pnl = results(segments, configs, args.work, load)
    for earlier in args.also:
        done = sorted(d.name for d in earlier.iterdir() if d.is_dir())
        more_load: dict[tuple[str, str], list[float]] = {}
        _, more = results(segments, done, earlier, more_load)
        for key, by_seg in more.items():
            if key not in pnl:  # a strategy run in both keeps this run's numbers
                pnl[key], load[key] = by_seg, more_load[key]
        configs = sorted(set(configs) | set(done))
    per_usd = {k: (a if family(k[1]) == "taker" else a / 2) / n if n else float("inf") for k, (a, n) in load.items()}
    total_h = sum(hours.values())
    over = sorted((k for k in pnl if per_usd[k] > args.max_orders_per_usd), key=lambda k: -sum(pnl[k].values()))
    report = {
        "hours": {k: round(v, 3) for k, v in hours.items()},
        "configs": configs,
        "budget_usd": args.budget_usd,
        "latency_ms": args.latency_ms,
        "clock_corrected": sorted(args.clock),
        "max_orders_per_usd": args.max_orders_per_usd,
        "options": len(pnl),
        "excluded": len(over),
        "over_limit": [
            {
                "strategy": k[1],
                "config": k[0],
                "orders_per_usd": round(per_usd[k], 2),
                "usd_per_hour": round(sum(pnl[k].values()) / total_h, 1),
            }
            for k in over
        ],
        "families": select(hours, pnl, per_usd, args.max_orders_per_usd),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    if args.md is not None:
        args.md.write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
