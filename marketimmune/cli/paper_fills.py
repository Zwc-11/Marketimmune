"""Every fill a quote at the touch would have had, with the signals known before it and what the price
did after: the training rows of ``immune@``'s fill-markout model (``paper.immune``).

    python -m marketimmune.cli.paper_fills \\
        --chain night=data/paper/seg1-20261106T0441/raw~,data/paper/seg2-20261106T0448/raw,... \\
        --chain live=...,data/paper/live-tuned/seg-20261106T2003/raw! --clock live \\
        --out data/paper/immune/fills.parquet

Each segment is replayed (chains carry the model state, as ``cli.paper_factors``) with ``touch``
quoting both sides of every coin without a position limit, so its fills are the fills any touch
quoter could get. On each 100 ms tick every coin's ``immune.features`` are kept. A fill is joined
with the features of the last tick at least ``--latency-ms`` before it: the latest moment a cancel
could still have reached the book, so the model sees only what a quoter could have acted on.
Labels: the seen mid 10, 30 and 60 s after the fill against the fill price, in bps signed by the
side (the spread edge in, the fee out), where a tick exists within 200 ms of that time in the
segment. The clock of fast-clock chains is corrected from earlier timestamps only.
"""

from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.cli.paper_trade import COINS, sz_decimals
from marketimmune.cli.paper_tune import Segment, parse_chain
from marketimmune.logger import init_logger
from marketimmune.paper.engine import Engine
from marketimmune.paper.immune import FEATURES, features
from marketimmune.paper.journal import Journal
from marketimmune.paper.live import clock_offsets, replay
from marketimmune.utils import parse_symbol_spec

logger = init_logger(__name__)
HORIZONS_S = (10, 30, 60)
MATCH_MS = 200


class FillSampler(Engine):
    """``touch`` without limits, and every coin's features on every tick."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, strategies=("touch",), max_quotes=1_000_000, **kwargs)
        self.rows: list[dict[str, Any]] = []

    def tick(self, local_ms: int) -> None:
        super().tick(local_ms)
        for c, st in self.states.items():
            f = features(st, local_ms)
            mid = st.view.at(local_ms)
            if f is not None and mid is not None:
                self.rows.append({"coin": c, "t_ms": local_ms, "mid": mid, **f})


def segment_fills(seg: Segment, coins: tuple[str, ...], state: Path, clock: bool, latency_ms: int, quote_usd: float) -> pd.DataFrame:
    with tempfile.TemporaryDirectory() as tmp:
        journal = Journal(Path(tmp))
        engine = FillSampler(coins, latency_ms=latency_ms, quote_usd=quote_usd, sz_decimals=sz_decimals(state, seg.raw), journal=journal)
        engine.load_state(state)
        replay(engine, seg.raw, clock=clock_offsets(seg.raw) if clock else None, causal=True)
        engine.save_state(state)
        journal.close()
        with gzip.open(Path(tmp) / "fills.jsonl.gz", "rt", encoding="utf-8") as fh:
            fills = pd.DataFrame([r for line in fh if line.strip() and (r := json.loads(line)).get("kind") == "maker"])
    rows = pd.DataFrame(engine.rows)
    if fills.empty or rows.empty:
        return pd.DataFrame()
    out = []
    for coin, f in fills.groupby("c"):
        r = rows[rows["coin"] == coin].sort_values("t_ms")
        t = r["t_ms"].to_numpy()
        mid = r["mid"].to_numpy()
        f = f.sort_values("t")
        # the features of the last tick at least latency_ms before the fill
        i = np.searchsorted(t, f["t"].to_numpy() - latency_ms, side="right") - 1
        ok = i >= 0
        g = f[ok].copy()
        idx = i[ok]
        for k in FEATURES:
            g[k] = r[k].to_numpy()[idx]
        side, px = g["side"].to_numpy(), g["px"].to_numpy()
        for h in HORIZONS_S:
            j = np.minimum(np.searchsorted(t, g["t"].to_numpy() + h * 1_000, side="left"), t.size - 1)
            hit = np.abs(t[j] - (g["t"].to_numpy() + h * 1_000)) <= MATCH_MS
            g[f"markout_{h}s"] = np.where(hit, side * (mid[j] / px - 1.0) * 1e4, np.nan)
        k0 = np.minimum(np.searchsorted(t, g["t"].to_numpy(), side="left"), t.size - 1)
        g["edge_bps"] = side * (mid[k0] / px - 1.0) * 1e4
        out.append(g)
    df = pd.concat(out, ignore_index=True)
    df["coin"] = df.pop("c")
    df["segment"] = f"{seg.chain}/{seg.name}"
    df["part"] = "held_out" if seg.holdout else "selection"
    keep = ["segment", "part", "coin", "t", "blk", "side", "px", "qty", "edge_bps", *FEATURES, *[f"markout_{h}s" for h in HORIZONS_S]]
    return df[[c for c in keep if c in df.columns]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", action="append", required=True, help="name=raw1[~],raw2,raw3[!] in order (as cli.paper_tune)")
    parser.add_argument("--clock", default="", help="chains whose receive times to correct from Coinbase timestamps (causally)")
    parser.add_argument("--coins", default=COINS)
    parser.add_argument("--latency-ms", type=int, default=200)
    parser.add_argument("--quote-usd", type=float, default=250.0)
    parser.add_argument("--part", default=None, help="label every segment with this part instead (e.g. test)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    coins = parse_symbol_spec(args.coins)
    clock = {c for c in args.clock.split(",") if c}
    frames = []
    for spec in args.chain:
        chain = parse_chain(spec)
        with tempfile.TemporaryDirectory() as state:
            for seg in chain:
                df = segment_fills(seg, coins, Path(state), seg.chain in clock, args.latency_ms, args.quote_usd)
                logger.info(f"{seg.chain}/{seg.name}: {len(df):,} fills")
                if not seg.warmup and not df.empty:
                    frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    if args.part:
        out["part"] = args.part
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    logger.info(f"wrote {len(out):,} fills to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
