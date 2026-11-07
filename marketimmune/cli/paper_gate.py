"""A Transformer that guesses the probability that a market maker's fill wins after the fee, and the
fills it would keep (candidate 4 of ``docs/preregistration/paper-mm-five-20261107.md``).

    python -m marketimmune.cli.paper_gate fills --runs <tune work dir>/<chain>/<segment> ... --strategy <name> \\
        --bars data/paper/bars --out data/paper/gate/<name>.parquet
    python -m marketimmune.cli.paper_gate train --fills <parquet> --bars data/paper/bars --split <UTC> \\
        --out marketimmune/paper/models/gate_<x>.pt --report eval/paper/gate_train.json
    python -m marketimmune.cli.paper_gate score --fills <parquet> --bars <dirs> --model <pt> --p <threshold> --out <json>

The model is ``paper.seqmodel``'s Transformer: the last 120 one-second bars of the coin and BTC,
signed by the fill's side. Its target is a win: the 30 s markout after the 1.5 bp maker fee is above
zero. Trained on the earlier selection fills; its threshold is chosen on the later selection fills.
Scoring is per fill: the kept fills' markout after the fee, in dollars an hour at the fill size,
with a stationary-bootstrap interval over 15-minute blocks. There is no inventory or queue effect
of skipping a fill.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.cli.paper_seqmodel import load_bars, predict
from marketimmune.models.compare import stationary_bootstrap_ci
from marketimmune.paper.seqmodel import CHANNELS, build_model, sequences

FEE = 1.5
Arr = npt.NDArray[np.float64]


def fills_of(runs: list[Path], strategy: str, bars_root: list[Path]) -> pd.DataFrame:
    rows = []
    for r in runs:
        p = r / "fills.jsonl"
        if not p.exists():
            continue
        with open(p) as fh:
            for line in fh:
                j = json.loads(line)
                if j.get("strategy") == strategy and float(j.get("fee_rate", 0.0)) < 3e-4:  # maker fills
                    rows.append(
                        {
                            "t": int(j["t_ms"]),
                            "coin": j["coin"],
                            "side": int(j["side"]),
                            "px": float(j["px"]),
                            "qty": float(j["qty"]),
                            "segment": r.name,
                        }
                    )
    f = pd.DataFrame(rows)
    if not len(f):
        return f
    mids = []
    for root in bars_root:
        for b in sorted(root.glob("*.parquet")):
            d = pd.read_parquet(b, columns=["coin", "t", "hl_bid", "hl_ask"])
            mids.append(d)
    m = pd.concat(mids).drop_duplicates(["coin", "t"]).sort_values(["coin", "t"])
    m["mid"] = (m["hl_bid"] + m["hl_ask"]) / 2
    out = []
    for coin, g in f.groupby("coin"):
        mm = m[m["coin"] == coin]
        tt, mid = mm["t"].to_numpy(), mm["mid"].to_numpy()
        for h in (10, 30, 60):
            target = (g["t"].to_numpy() // 1000 + h) * 1000
            i = np.searchsorted(tt, target)
            ok = (i < len(tt)) & (tt[np.minimum(i, len(tt) - 1)] == target)
            later = np.where(ok, mid[np.minimum(i, len(tt) - 1)], np.nan)
            g = g.assign(**{f"markout_{h}s": g["side"].to_numpy() * (later / g["px"].to_numpy() - 1) * 1e4})
        out.append(g)
    return pd.concat(out).sort_values("t").reset_index(drop=True)


def _xy(f: pd.DataFrame, bars: Any) -> tuple[pd.DataFrame, npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    f = f.dropna(subset=["markout_30s"]).reset_index(drop=True)
    x, ok = sequences(f, bars)
    f, x = f[ok].reset_index(drop=True), x[ok]
    y = ((f["markout_30s"].to_numpy() - FEE) > 0).astype(np.float32)
    return f, x, y


def economics(f: pd.DataFrame, keep: npt.NDArray[np.bool_], hours: float, usd_per_fill: float) -> dict[str, Any]:
    net = f["markout_30s"].to_numpy() - FEE
    usd = np.where(keep, net * usd_per_fill / 1e4, 0.0)
    block = (f["t"].to_numpy() // 900_000).astype(np.int64)
    per_block = pd.Series(usd).groupby(block).sum()
    n_blocks = max(int(round(hours * 4)), len(per_block))
    vals = np.concatenate([per_block.to_numpy(), np.zeros(n_blocks - len(per_block))]) * 4
    lo, hi = stationary_bootstrap_ci(vals, mean_block=3, n_boot=5000, seed=0)
    return {
        "fills": len(f),
        "kept": int(keep.sum()),
        "kept_net_bps": float(net[keep].mean()) if keep.any() else None,
        "all_net_bps": float(net.mean()) if len(net) else None,
        "kept_win_rate": float((net[keep] > 0).mean()) if keep.any() else None,
        "usd_per_hour": float(usd.sum() / hours),
        "usd_per_hour_ci95": [float(lo), float(hi)],
    }


def cmd_fills(a: argparse.Namespace) -> dict[str, Any]:
    f = fills_of(a.runs, a.strategy, a.bars)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    f.to_parquet(a.out)
    return {"fills": len(f), "segments": sorted(f["segment"].unique().tolist()) if len(f) else []}


def cmd_train(a: argparse.Namespace) -> dict[str, Any]:
    import torch

    torch.set_num_threads(a.threads)
    bars: dict[str, Any] = {}
    for root in a.bars:
        bars.update(load_bars(root))
    f = pd.concat([pd.read_parquet(p) for p in a.fills], ignore_index=True).sort_values("t").reset_index(drop=True)
    split = int(pd.Timestamp(a.split, tz="UTC").value // 1_000_000)
    tr, xt, yt = _xy(f[f["t"] < split], bars)
    va, xv, yv = _xy(f[f["t"] >= split], bars)
    mu = xt.reshape(-1, CHANNELS).mean(0).astype(np.float32)
    sd = (xt.reshape(-1, CHANNELS).std(0) + 1e-6).astype(np.float32)
    net = build_model(a.seed, 0)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-3)
    pos_w = torch.tensor((1 - yt.mean()) / max(yt.mean(), 1e-3))
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_w)
    xt_n, yt_t = torch.from_numpy((xt - mu) / sd), torch.from_numpy(yt)
    rng = np.random.default_rng(a.seed)
    best, best_state, history = np.inf, None, []
    for epoch in range(a.epochs):
        net.train()
        perm = rng.permutation(len(xt_n))
        for i in range(0, len(perm), a.batch):
            b = perm[i : i + a.batch]
            opt.zero_grad()
            loss = loss_fn(net(xt_n[b]), yt_t[b])
            loss.backward()
            opt.step()
        pv = predict(net, xv, mu, sd)
        vloss = float(loss_fn(torch.from_numpy(pv).float(), torch.from_numpy(yv)))
        auc = _auc(pv, yv)
        history.append({"epoch": epoch, "val_bce": vloss, "val_auc": auc})
        print(history[-1], flush=True)
        if vloss < best:
            best, best_state = vloss, {k: v.clone() for k, v in net.state_dict().items()}
    assert best_state is not None
    net.load_state_dict(best_state)
    pv = 1 / (1 + np.exp(-predict(net, xv, mu, sd)))
    hours = (va["t"].max() - va["t"].min()) / 3.6e6 if len(va) else 1.0
    table = []
    for p in a.grid:
        keep = pv >= p
        table.append({"p": p, **economics(va, keep, hours, a.usd_per_fill)})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state": best_state, "mu": mu, "sd": sd, "seed": a.seed}, a.out)
    return {
        "train_fills": len(tr),
        "train_win_rate": float(yt.mean()),
        "val_fills": len(va),
        "val_win_rate": float(yv.mean()),
        "val_auc": _auc(pv, yv),
        "history": history,
        "thresholds_on_validation": table,
    }


def _auc(score: Arr, y: npt.NDArray[np.float32]) -> float:
    pos, neg = score[y > 0.5], score[y <= 0.5]
    if not len(pos) or not len(neg):
        return float("nan")
    r = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((r[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def cmd_score(a: argparse.Namespace) -> dict[str, Any]:
    import torch

    bars: dict[str, Any] = {}
    for root in a.bars:
        bars.update(load_bars(root))
    f = pd.concat([pd.read_parquet(p) for p in a.fills], ignore_index=True).sort_values("t").reset_index(drop=True)
    if a.from_:
        f = f[f["t"] >= int(pd.Timestamp(a.from_, tz="UTC").value // 1_000_000)]
    f, x, y = _xy(f, bars)
    ck = torch.load(a.model, weights_only=False)
    net = build_model(ck["seed"], 0)
    net.load_state_dict(ck["state"])
    pv = 1 / (1 + np.exp(-predict(net, x, ck["mu"], ck["sd"])))
    hours = a.hours
    return {
        "threshold": a.p,
        "auc": _auc(pv, y),
        "win_rate_all": float(y.mean()) if len(y) else None,
        "gated": economics(f, pv >= a.p, hours, a.usd_per_fill),
        "ungated": economics(f, np.ones(len(f), bool), hours, a.usd_per_fill),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    fl = sub.add_parser("fills")
    fl.add_argument("--runs", type=Path, nargs="+", required=True)
    fl.add_argument("--strategy", required=True)
    fl.add_argument("--bars", type=Path, nargs="+", required=True)
    fl.add_argument("--out", type=Path, required=True)
    tr = sub.add_parser("train")
    tr.add_argument("--fills", type=Path, nargs="+", required=True)
    tr.add_argument("--bars", type=Path, nargs="+", required=True)
    tr.add_argument("--split", required=True)
    tr.add_argument("--out", type=Path, required=True)
    tr.add_argument("--report", type=Path, required=True)
    tr.add_argument("--epochs", type=int, default=8)
    tr.add_argument("--batch", type=int, default=256)
    tr.add_argument("--lr", type=float, default=1e-3)
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--threads", type=int, default=2)
    tr.add_argument("--usd-per-fill", type=float, default=250.0)
    tr.add_argument("--grid", type=float, nargs="+", default=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    sc = sub.add_parser("score")
    sc.add_argument("--fills", type=Path, nargs="+", required=True)
    sc.add_argument("--bars", type=Path, nargs="+", required=True)
    sc.add_argument("--model", type=Path, required=True)
    sc.add_argument("--p", type=float, required=True)
    sc.add_argument("--from", dest="from_", default=None)
    sc.add_argument("--hours", type=float, required=True)
    sc.add_argument("--usd-per-fill", type=float, default=250.0)
    sc.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    result = {"fills": cmd_fills, "train": cmd_train, "score": cmd_score}[a.cmd](a)
    out = a.report if a.cmd == "train" else (None if a.cmd == "fills" else a.out)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=1, default=float)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
