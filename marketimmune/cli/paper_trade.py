"""Paper-trade every strategy on live Hyperliquid data for a fixed time (no order is ever sent).

    python -m marketimmune.cli.paper_trade --out data/paper/20261106-0500 --hours 1.9 --state-dir data/paper/state
    python -m marketimmune.cli.paper_trade --out data/paper/replay --replay data/paper/20261106-0500/raw
    python -m marketimmune.cli.paper_trade --out data/paper/live --hours 24 --segment-hours 2 --serve 8765   # then open http://127.0.0.1:8765/

Writes ``summary.json`` every minute, and at the end ``fills.jsonl``, ``equity.jsonl``,
``mids.parquet`` and the raw messages under ``raw/``. ``journal/`` holds every strategy's decisions,
fills with the signals behind them, each coin's signals every second and per-minute counters, written
as the run goes (``marketimmune.paper.journal``; ``--no-journal`` to skip; ``cli.paper_journal``
reads it). ``--state-dir`` carries the model rows and the
wallet scores from one run to the next. ``--retime`` replays a recording as a maker elsewhere would
have seen it: Hyperliquid's messages ``hl`` ms after their block, Coinbase's ``cb`` ms later than they
arrived here (``paper.live.retimed``). Strategies and fill model: ``marketimmune.paper``; results:
``docs/research/paper-trading.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.request
from pathlib import Path

from marketimmune.logger import init_logger
from marketimmune.paper.dashboard import Board
from marketimmune.paper.engine import Engine
from marketimmune.paper.journal import Journal
from marketimmune.paper.live import replay, run_live
from marketimmune.paper.strategies import LIVE_STRATEGIES
from marketimmune.utils import parse_symbol_spec, split_csv

logger = init_logger(__name__)
COINS = "BTC,ETH,SOL,XRP,LTC,BCH,LINK,AVAX,DOGE"
INFO_URL = "https://api.hyperliquid.xyz/info"


def sz_decimals(out: Path, replay: Path | None) -> dict[str, int]:
    """Each perp's size decimals (its price step): from the recorded run's ``meta.json`` when
    replaying one that has it, else from Hyperliquid's ``meta``, saved to ``out``."""
    if replay is not None and (replay.parent / "meta.json").exists():
        saved: dict[str, int] = json.loads((replay.parent / "meta.json").read_text(encoding="utf-8"))
        return saved
    req = urllib.request.Request(INFO_URL, data=b'{"type": "meta"}', headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        meta = json.loads(resp.read())
    decimals = {x["name"]: int(x["szDecimals"]) for x in meta["universe"]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(decimals), encoding="utf-8")
    return decimals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default=COINS, help="Hyperliquid perps that also trade as <COIN>-USD on Coinbase")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--replay", type=Path, default=None, help="a recorded run's raw/ directory, instead of the live feeds")
    parser.add_argument(
        "--retime",
        default="",
        help="replay as if elsewhere: hl=<ms after each block>,cb=<ms added to Coinbase's receive time>, e.g. hl=50,cb=70 for Tokyo",
    )
    parser.add_argument("--until-ms", type=int, default=None, help="replay only the messages received by this local ms")
    parser.add_argument("--latency-ms", type=int, default=200, help="decision to order (or cancel) in the book")
    parser.add_argument("--quote-usd", type=float, default=1_000.0)
    parser.add_argument("--max-quotes", type=int, default=5, help="per coin: the most quotes of position a strategy holds")
    parser.add_argument("--budget-usd", type=float, default=None, help="per strategy: the most gross exposure over all coins")
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--no-raw", action="store_true", help="do not keep the raw messages")
    parser.add_argument("--no-journal", action="store_true", help="do not write the decision journal")
    parser.add_argument(
        "--strategies", default=",".join(LIVE_STRATEGIES), help="touch, gap@<bps>, model@<bps>, improve, improve+gap@<bps>, taker@<bps>"
    )
    parser.add_argument("--serve", type=int, default=0, help="serve the live view on http://127.0.0.1:<port>/ (live runs)")
    parser.add_argument(
        "--web", type=Path, default=None, help="the built web terminal (frontend/dist) to serve; its Paper page reads the run"
    )
    parser.add_argument("--segment-hours", type=float, default=None, help="split a live run into segments of this length under --out")
    args = parser.parse_args(argv)
    if args.replay is not None:
        engine = make_engine(args, args.out)
        if args.state_dir is not None:
            engine.load_state(args.state_dir)
        retime = {k: int(v) for k, v in (kv.split("=") for kv in args.retime.split(",") if kv)}
        replay(engine, args.replay, retime or None, args.until_ms)
        engine.write(args.out, final=True)
        if args.state_dir is not None:
            engine.save_state(args.state_dir)
        return 0
    asyncio.run(live(args))
    return 0


def make_engine(args: argparse.Namespace, out: Path) -> Engine:
    return Engine(
        parse_symbol_spec(args.coins),
        latency_ms=args.latency_ms,
        quote_usd=args.quote_usd,
        max_quotes=args.max_quotes,
        maker_fee_bps=args.maker_fee_bps,
        taker_fee_bps=args.taker_fee_bps,
        sz_decimals=sz_decimals(out, args.replay),
        strategies=split_csv(args.strategies),
        budget_usd=args.budget_usd,
        journal=None if args.no_journal else Journal(out / "journal"),
    )


async def live(args: argparse.Namespace) -> None:
    """One live run, or segments of ``--segment-hours`` under ``--out`` (``seg-<UTC start>``), each
    written when it ends; the model rows and wallet scores carry through ``--state-dir``."""
    state_dir = args.state_dir or (args.out / "state" if args.segment_hours else None)
    board = Board()
    server = await board.serve(args.serve, args.web) if args.serve else None
    if server is not None:
        logger.info(f"live view: http://127.0.0.1:{args.serve}/" + ("#/paper" if args.web else ""))
    total = args.hours * 3600
    started = time.monotonic()
    try:
        while (left := total - (time.monotonic() - started)) > 1:
            out = args.out / time.strftime("seg-%Y%m%dT%H%M", time.gmtime()) if args.segment_hours else args.out
            engine = make_engine(args, out)
            if state_dir is not None and state_dir.exists():
                engine.load_state(state_dir)
            board.attach(engine)
            seconds = min(left, args.segment_hours * 3600) if args.segment_hours else left
            stopped = await run_live(engine, out, seconds, raw=not args.no_raw, board=board)
            engine.write(out, final=True)
            if state_dir is not None:
                engine.save_state(state_dir)
            board.close_segment(engine)
            if stopped or not args.segment_hours:
                break
    finally:
        if server is not None:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    raise SystemExit(main())
