"""Paper-trade every strategy on live Hyperliquid data for a fixed time (no order is ever sent).

    python -m marketimmune.cli.paper_trade --out data/paper/20261106-0500 --hours 1.9 --state-dir data/paper/state
    python -m marketimmune.cli.paper_trade --out data/paper/replay --replay data/paper/20261106-0500/raw

Writes ``summary.json`` every minute, and at the end ``fills.jsonl``, ``equity.jsonl``,
``mids.parquet`` and the raw messages under ``raw/``. ``--state-dir`` carries the model rows and the
wallet scores from one run to the next. Strategies and fill model: ``marketimmune.paper``; results:
``docs/research/paper-trading.md``.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from marketimmune.logger import init_logger
from marketimmune.paper.engine import Engine
from marketimmune.paper.live import now_ms, replay, run_live
from marketimmune.utils import parse_symbol_spec

logger = init_logger(__name__)
COINS = "BTC,ETH,SOL,XRP,LTC,BCH,LINK,AVAX,DOGE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coins", default=COINS, help="Hyperliquid perps that also trade as <COIN>-USD on Coinbase")
    parser.add_argument("--hours", type=float, default=1.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, default=None)
    parser.add_argument("--replay", type=Path, default=None, help="a recorded run's raw/ directory, instead of the live feeds")
    parser.add_argument("--latency-ms", type=int, default=200, help="decision to order (or cancel) in the book")
    parser.add_argument("--quote-usd", type=float, default=1_000.0)
    parser.add_argument("--max-quotes", type=int, default=5)
    parser.add_argument("--maker-fee-bps", type=float, default=1.5)
    parser.add_argument("--taker-fee-bps", type=float, default=4.5)
    parser.add_argument("--no-raw", action="store_true", help="do not keep the raw messages")
    args = parser.parse_args(argv)
    engine = Engine(
        parse_symbol_spec(args.coins),
        latency_ms=args.latency_ms,
        quote_usd=args.quote_usd,
        max_quotes=args.max_quotes,
        maker_fee_bps=args.maker_fee_bps,
        taker_fee_bps=args.taker_fee_bps,
    )
    if args.state_dir is not None:
        engine.load_state(args.state_dir, now_ms())
    if args.replay is not None:
        replay(engine, args.replay)
    else:
        asyncio.run(run_live(engine, args.out, args.hours * 3600, raw=not args.no_raw))
    engine.write(args.out, final=True)
    if args.state_dir is not None:
        engine.save_state(args.state_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
