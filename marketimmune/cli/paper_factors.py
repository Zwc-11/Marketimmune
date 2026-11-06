"""How well each paper signal predicts the price, by horizon, on recorded runs.

    python -m marketimmune.cli.paper_factors \\
        --chain night=data/paper/seg1-20261106T0441/raw~,data/paper/seg2-20261106T0448/raw,... \\
        --chain live=data/paper/live/seg-20261106T1606/raw,...,data/paper/live-tuned/seg-20261106T2003/raw! \\
        --clock live --out eval/paper/factors_20261106.json --samples data/paper/factors.parquet

Each segment is replayed through the engine with no strategies, as the live run sees it (a chain's
segments carry the wallet scores and the model state from one to the next, through the same state
files the live run uses). On the engine's 100 ms ticks, every coin's signals are read as a strategy
would read them at that moment, and the seen Hyperliquid mid is kept. The label is the seen mid's
log move from the sample to ``h`` later (1 s, 10 s, 60 s), taken only when a sample exists within
200 ms of that time in the same segment.

Signals (all from data received by the sample's time):

- ``gap_z``: the demeaned Coinbase gap over its own volatility (A1's CEX gap, live);
- ``wallet`` and ``wallet_z``: ``CoinState.informed``, the takers' signed notional times their wallet
  scores over 5 s (A1's wallet score, live), raw and over its own volatility (``CoinState.informed_z``);
- ``wallet_1s_z``: the same over 1 s, over its volatility;
- ``imbalance``: signed over total taker notional, 5 s;
- ``micro``: the microprice's offset from the mid, bps;
- ``burst``: the log ratio of the buy and sell Hawkes intensity ratios.

Per signal, coin and horizon, on the selection segments and on the held-out ones (``!``) apart: the
correlation of signal and label (Pearson, the information coefficient) and the rank correlation. ``by_segment`` repeats it per segment for the sign count.
``incremental``: least squares of the 10 s move on ``gap_z`` alone and on ``gap_z`` and
``wallet_z`` (per coin, fitted on the selection segments), scored by R^2 on the held-out ones
(``!``). ``~`` segments only warm the state up.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.cli.paper_trade import COINS, sz_decimals
from marketimmune.cli.paper_tune import Segment, parse_chain
from marketimmune.logger import init_logger
from marketimmune.paper.engine import Engine
from marketimmune.paper.live import clock_offsets, replay
from marketimmune.paper.mm import micro_bps
from marketimmune.utils import parse_symbol_spec

logger = init_logger(__name__)
FloatArray = npt.NDArray[np.float64]
BPS = 1e4
HORIZONS_MS = (1_000, 10_000, 60_000)
MATCH_MS = 200
SIGNALS = ("gap_z", "wallet", "wallet_z", "wallet_1s_z", "imbalance", "micro", "burst")


class Sampler(Engine):
    """The engine with no strategies, reading each coin's signals on every tick."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, strategies=(), **kwargs)
        self.rows: list[tuple[Any, ...]] = []

    def tick(self, local_ms: int) -> None:
        super().tick(local_ms)
        for c, st in self.states.items():
            top, gap, gs = st.top, st.gap(), st.gap_sigma
            if top is None or gap is None or not gs:
                continue
            mid = st.view.at(local_ms)
            if mid is None:
                continue
            w = st.informed(local_ms)
            bb, sb = st.intensity_ratio(1, local_ms), st.intensity_ratio(-1, local_ms)
            signed = total = 0.0
            for t, s, n, _ in st.flow:
                if local_ms - 5_000 <= t <= local_ms:
                    signed += s
                    total += n
            self.rows.append(
                (
                    c,
                    local_ms,
                    mid,
                    gap / gs,
                    w,
                    st.informed_z(local_ms) or 0.0,
                    st.informed_z(local_ms, 1_000) or 0.0,
                    signed / total if total else 0.0,
                    micro_bps(top),
                    math.log(bb / sb) if bb and sb else 0.0,
                )
            )


def sample_segment(seg: Segment, coins: tuple[str, ...], state: Path, clock: bool) -> dict[str, Any]:
    engine = Sampler(coins, sz_decimals=sz_decimals(state, seg.raw))
    engine.load_state(state)
    replay(engine, seg.raw, clock=clock_offsets(seg.raw) if clock else None, causal=True)
    engine.save_state(state)
    cols: list[Any] = list(zip(*engine.rows, strict=True)) if engine.rows else [() for _ in range(3 + len(SIGNALS))]
    out: dict[str, Any] = {"coin": np.asarray(cols[0], dtype=str), "t_ms": np.asarray(cols[1], np.int64), "mid": np.asarray(cols[2])}
    for i, name in enumerate(SIGNALS):
        out[name] = np.asarray(cols[3 + i], np.float64)
    logger.info(f"{seg.chain}/{seg.name}: {len(engine.rows):,} samples")
    return out


def labels(t: npt.NDArray[np.int64], mid: FloatArray, h: int) -> FloatArray:
    """The log move in bps from each sample to ``h`` ms later; NaN without a sample within
    ``MATCH_MS`` of that time."""
    j = np.searchsorted(t, t + h, side="left")
    j = np.minimum(j, t.size - 1)
    ok = np.abs(t[j] - (t + h)) <= MATCH_MS
    out = np.full(t.size, np.nan)
    out[ok] = np.log(mid[j[ok]] / mid[ok]) * BPS
    return out


def corr(x: FloatArray, y: FloatArray) -> tuple[float | None, float | None, int]:
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if x.size < 100 or x.std() == 0 or y.std() == 0:
        return None, None, int(x.size)
    pearson = float(np.corrcoef(x, y)[0, 1])
    rx, ry = x.argsort().argsort().astype(np.float64), y.argsort().argsort().astype(np.float64)
    return round(pearson, 4), round(float(np.corrcoef(rx, ry)[0, 1]), 4), int(x.size)


def r2(y: FloatArray, pred: FloatArray) -> float:
    return 1.0 - float(((y - pred) ** 2).sum()) / float(((y - y.mean()) ** 2).sum())


def ols(x: FloatArray, y: FloatArray) -> FloatArray:
    a = np.column_stack([np.ones(len(y)), x])
    return np.asarray(np.linalg.lstsq(a, y, rcond=None)[0], np.float64)


def analyse(frames: list[tuple[Segment, dict[str, Any]]]) -> dict[str, Any]:
    pooled: dict[tuple[str, str, int, str], tuple[list[FloatArray], list[FloatArray]]] = {}
    by_segment: dict[str, dict[str, float | None]] = {}
    fit: dict[str, dict[str, list[FloatArray]]] = {}
    for seg, f in frames:
        key = f"{seg.chain}/{seg.name}"
        by_segment[key] = {}
        for coin in sorted(set(f["coin"].tolist())):
            m = f["coin"] == coin
            t, mid = f["t_ms"][m], f["mid"][m]
            ys = {h: labels(t, mid, h) for h in HORIZONS_MS}
            part = "held_out" if seg.holdout else "selection"
            d = fit.setdefault(f"{coin}|{part}", {"x": [], "w": [], "y": []})
            d["x"].append(f["gap_z"][m])
            d["w"].append(f["wallet_z"][m])
            d["y"].append(ys[10_000])
            for name in SIGNALS:
                for h, y in ys.items():
                    xs, yl = pooled.setdefault((name, coin, h, part), ([], []))
                    xs.append(f[name][m])
                    yl.append(y)
                c, _, _ = corr(f[name][m], ys[10_000])
                by_segment[key][f"{name}|{coin}"] = c
    ic: dict[str, Any] = {"selection": {}, "held_out": {}}
    for (name, coin, h, part), (xs, yl) in sorted(pooled.items()):
        p, s, n = corr(np.concatenate(xs), np.concatenate(yl))
        ic[part].setdefault(name, {}).setdefault(coin, {})[f"{h // 1000}s"] = {"ic": p, "rank_ic": s, "n": n}
    for by_name in ic.values():
        for coins in by_name.values():
            per_coin = list(coins.values())
            mean: dict[str, Any] = {}
            for h in HORIZONS_MS:
                vals = [v[f"{h // 1000}s"]["ic"] for v in per_coin if v[f"{h // 1000}s"]["ic"] is not None]
                mean[f"{h // 1000}s"] = {
                    "ic": round(float(np.mean(vals)), 4) if vals else None,
                    "positive": f"{sum(v > 0 for v in vals)}/{len(vals)}",
                }
            coins["_mean"] = mean
    signs: dict[str, str] = {}
    for name in SIGNALS:
        vals = [v for seg in by_segment.values() for k, v in seg.items() if k.startswith(name + "|") and v is not None]
        signs[name] = f"{sum(v > 0 for v in vals)}/{len(vals)}"
    incremental: dict[str, Any] = {}
    for coin in sorted({k.split("|")[0] for k in fit}):
        sel, held = fit.get(f"{coin}|selection"), fit.get(f"{coin}|held_out")
        if sel is None or held is None:
            continue
        x, w, y = (np.concatenate(sel[k]) for k in ("x", "w", "y"))
        hx, hw, hy = (np.concatenate(held[k]) for k in ("x", "w", "y"))
        ok, hok = np.isfinite(y), np.isfinite(hy)
        b1 = ols(x[ok, None], y[ok])
        b2 = ols(np.column_stack([x[ok], w[ok]]), y[ok])
        p1 = b1[0] + b1[1] * hx[hok]
        p2 = b2[0] + b2[1] * hx[hok] + b2[2] * hw[hok]
        incremental[coin] = {
            "gap_only_r2": round(r2(hy[hok], p1), 5),
            "gap_and_wallet_r2": round(r2(hy[hok], p2), 5),
            "wallet_coef_bps_per_z": round(float(b2[2]), 4),
        }
    return {"ic": ic, "segments_positive_at_10s": signs, "by_segment_10s": by_segment, "incremental_10s_held_out": incremental}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chain", action="append", required=True, help="name=raw1[~],raw2,raw3[!] in order (as cli.paper_tune)")
    parser.add_argument("--clock", default="", help="chains whose receive times to correct from Coinbase timestamps")
    parser.add_argument("--coins", default=COINS)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--samples", type=Path, default=None, help="also write every sample (parquet)")
    args = parser.parse_args(argv)
    coins = parse_symbol_spec(args.coins)
    clock = {c for c in args.clock.split(",") if c}
    frames: list[tuple[Segment, dict[str, Any]]] = []
    for spec in args.chain:
        chain = parse_chain(spec)
        with tempfile.TemporaryDirectory() as state:
            for seg in chain:
                f = sample_segment(seg, coins, Path(state), seg.chain in clock)
                if not seg.warmup:
                    frames.append((seg, f))
    report = {"segments": [f"{s.chain}/{s.name}" + (" (held out)" if s.holdout else "") for s, _ in frames]} | analyse(frames)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    if args.samples is not None:
        cols: dict[str, Any] = {"segment": np.concatenate([np.full(f["t_ms"].size, f"{s.chain}/{s.name}") for s, f in frames])}
        for k in ("coin", "t_ms", "mid", *SIGNALS):
            cols[k] = np.concatenate([f[k] for _, f in frames])
        args.samples.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table(cols), args.samples)
    logger.info(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
