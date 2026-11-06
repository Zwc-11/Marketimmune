"""Check that a paper replay never uses data from after the moment it decides (no look-ahead).

    python -m marketimmune.cli.paper_lookahead --replay data/paper/live/seg-20261106T1806/raw \\
        --strategies guard@z=0.05/w=1,mm@1.5,zgap@0.05,touch --cuts 0.25,0.5,0.75 --clock-offset coinbase-causal \\
        --out eval/paper/lookahead_20261106.json

The prefix test: the same recording is replayed in full, and again cut off at each time ``T`` (only
the messages received by ``T``). A strategy that used anything received after ``T`` (a later
price, a trade's outcome, a refit on later rows) would decide differently before ``T`` in the two
runs. The clock correction of a fast-clock recording is estimated in each run from what that run
received, so a correction that reads ahead is caught too. Every decision, order, fill and taker exit in the decision journal, and every coin's
signals on each tick (``cli.paper_factors``), received before ``T`` must be identical; the check
reports how many were compared and every difference.
"""

from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from pathlib import Path
from typing import Any

from marketimmune.cli.paper_factors import Sampler
from marketimmune.cli.paper_trade import COINS, sz_decimals
from marketimmune.logger import init_logger
from marketimmune.paper.engine import Engine
from marketimmune.paper.journal import STREAMS, Journal
from marketimmune.paper.live import clock_offsets, raw_lines, replay
from marketimmune.utils import parse_symbol_spec, split_csv

logger = init_logger(__name__)
COMPARED = ("decisions", "fills", "taker")


def journal_rows(root: Path, until_ms: int) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for stream in COMPARED:
        path = root / f"{stream}.jsonl.gz"
        rows = []
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rows = [r for line in fh if line.strip() and (r := json.loads(line))["t"] < until_ms]
        out[stream] = rows
    return out


def run(
    raw: Path, strategies: tuple[str, ...], coins: tuple[str, ...], args: argparse.Namespace, until_ms: int | None, work: Path
) -> tuple[Path, list[tuple[Any, ...]]]:
    """One replay with the journal (strategies) and one with the sampler (signals); both cut at
    ``until_ms`` when given."""
    clock = clock_offsets(raw, until_ms) if args.clock_offset else None  # from what was received by the cut
    decimals = sz_decimals(work, raw)
    jroot = work / ("full" if until_ms is None else f"cut-{until_ms}")
    journal = Journal(jroot)
    engine = Engine(
        coins,
        latency_ms=args.latency_ms,
        quote_usd=args.quote_usd,
        max_quotes=args.max_quotes,
        budget_usd=args.budget_usd,
        sz_decimals=decimals,
        strategies=strategies,
        journal=journal,
    )
    replay(engine, raw, until_ms=until_ms, clock=clock, causal=args.clock_offset == "coinbase-causal")
    journal.close()
    sampler = Sampler(coins, sz_decimals=decimals)
    replay(sampler, raw, until_ms=until_ms, clock=clock, causal=args.clock_offset == "coinbase-causal")
    return jroot, sampler.rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--strategies", required=True)
    parser.add_argument("--coins", default=COINS)
    parser.add_argument("--cuts", default="0.25,0.5,0.75", help="where to cut, as shares of the recording's receive time span")
    parser.add_argument(
        "--clock-offset",
        default=None,
        choices=[None, "coinbase", "coinbase-causal"],
        help="correct a fast clock as the replays do: 'coinbase' interpolates each minute's estimate (it reads up to 30 s "
        "ahead, and this check finds that); 'coinbase-causal' uses each minute's only after it ends",
    )
    parser.add_argument("--latency-ms", type=int, default=200)
    parser.add_argument("--quote-usd", type=float, default=250.0)
    parser.add_argument("--max-quotes", type=int, default=4)
    parser.add_argument("--budget-usd", type=float, default=5_000.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    assert set(COMPARED) <= set(STREAMS)
    strategies = tuple(split_csv(args.strategies))
    coins = parse_symbol_spec(args.coins)
    first = last = None
    for local_ns, venue, _ in raw_lines(args.replay):
        if venue != "tick":
            first = local_ns // 1_000_000 if first is None else first
            last = local_ns // 1_000_000
    assert first is not None and last is not None, "an empty recording"
    report: dict[str, Any] = {"replay": str(args.replay), "strategies": list(strategies), "cuts": []}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        full_root, full_rows = run(args.replay, strategies, coins, args, None, work)
        for share in (float(x) for x in args.cuts.split(",")):
            cut = int(first + share * (last - first))
            until = cut - 1_000
            cut_root, cut_rows = run(args.replay, strategies, coins, args, cut, work)
            entry: dict[str, Any] = {"cut_ms": cut, "share": share, "compared_before_ms": until, "streams": {}}
            a, b = journal_rows(full_root, until), journal_rows(cut_root, until)
            for stream in COMPARED:
                diffs = [i for i, (x, y) in enumerate(zip(a[stream], b[stream], strict=False)) if x != y]
                entry["streams"][stream] = {
                    "rows": len(a[stream]),
                    "rows_cut": len(b[stream]),
                    "different": len(diffs) + abs(len(a[stream]) - len(b[stream])),
                    "first_difference": a[stream][diffs[0]] if diffs else None,
                }
            fa, fb = [r for r in full_rows if r[1] < until], [r for r in cut_rows if r[1] < until]
            entry["signals"] = {
                "rows": len(fa),
                "rows_cut": len(fb),
                "different": sum(x != y for x, y in zip(fa, fb, strict=False)) + abs(len(fa) - len(fb)),
            }
            entry["identical"] = entry["signals"]["different"] == 0 and all(s["different"] == 0 for s in entry["streams"].values())
            report["cuts"].append(entry)
            logger.info(f"cut at {share:.0%}: identical before it = {entry['identical']}")
    report["identical"] = all(c["identical"] for c in report["cuts"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "identical": report["identical"],
                "cuts": [
                    {k: c[k] for k in ("share", "identical")}
                    | {"rows": {s: v["rows"] for s, v in c["streams"].items()} | {"signals": c["signals"]["rows"]}}
                    for c in report["cuts"]
                ],
            },
            indent=1,
        )
    )
    return 0 if report["identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
