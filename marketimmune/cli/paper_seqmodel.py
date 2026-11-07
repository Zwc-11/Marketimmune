"""Train and score the Transformer fill-markout model (``paper.seqmodel``) against the ridge model of
``immune@`` on the same touch fills.

    python -m marketimmune.cli.paper_seqmodel train --bars data/paper/bars --fills <train parquet> ... \\
        --val-fills <parquet> --val-segments <names> --out marketimmune/paper/models/seq_30s.pt
    python -m marketimmune.cli.paper_seqmodel score --bars data/paper/bars --fills <parquet> --segments <names> \\
        --model marketimmune/paper/models/seq_30s.pt --out eval/paper/...json

Scoring: the correlation of each model's prediction with the realised 30 s markout, the markout by
tenth of prediction, and the fills each model would keep under ``immune@``'s rule (prediction minus
the 1.5 bp fee at least -1 bp): their mean markout after the fee, and dollars an hour at $250 a fill
with a stationary-bootstrap interval over 15-minute blocks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from marketimmune.models.compare import stationary_bootstrap_ci
from marketimmune.paper.immune import FEATURES, SIGNED, model_for
from marketimmune.paper.seqmodel import CHANNELS, bar_features, build_model, sequences

FEE = 1.5
RULE_T = -1.0
QUOTE_USD = 250.0


def load_bars(root: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    d = pd.concat([pd.read_parquet(f) for f in sorted(root.glob("*.parquet"))], ignore_index=True)
    d = d.sort_values(["coin", "t"]).drop_duplicates(["coin", "t"], keep="last")
    d["hl_mid"] = (d.hl_bid + d.hl_ask) / 2
    d["cb_mid"] = (d.cb_bid + d.cb_ask) / 2
    d["spread_bps"] = (d.hl_ask - d.hl_bid) / d.hl_mid * 1e4
    out = {}
    for coin, g in d.groupby("coin"):
        g = g.set_index("t")
        idx = np.arange(g.index.min(), g.index.max() + 1000, 1000)
        g = g.reindex(idx)
        for c in ("hl_mid", "cb_mid", "spread_bps"):
            g[c] = g[c].ffill(limit=600)
        for c in ("buy_usd", "sell_usd", "trades"):
            g[c] = g[c].fillna(0)
        out[str(coin)] = bar_features(g)
    return out


def load_fills(paths: list[Path], segments: list[str] | None) -> pd.DataFrame:
    f = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    if segments:
        f = f[f["segment"].str.split("/").str[-1].isin(segments)]
    return f.dropna(subset=["markout_30s"]).sort_values("t").reset_index(drop=True)


def signed(f: pd.DataFrame) -> np.ndarray:
    """The ridge model's features, the directional ones signed by the fill's side (as it was fitted)."""
    side = f["side"].to_numpy(float)
    return np.column_stack([f[k].to_numpy(float) * (side if k in SIGNED else 1.0) for k in FEATURES])


def ridge(f: pd.DataFrame) -> np.ndarray:
    m = model_for(30)
    return np.array([m.predict(c, list(x)) for c, x in zip(f["coin"], signed(f), strict=True)])


def static(f: pd.DataFrame, mean: np.ndarray | None = None, scale: np.ndarray | None = None) -> np.ndarray:
    """The ridge model's features, standardised and clipped as it does."""
    x = signed(f)
    if mean is None or scale is None:
        mean, scale = np.nanmean(x, 0), np.nanstd(x, 0) + 1e-9
    return np.clip(np.nan_to_num((x - mean) / scale), -5, 5).astype(np.float32)


def predict(net: Any, x: np.ndarray, mu: np.ndarray, sd: np.ndarray, s: np.ndarray | None = None) -> np.ndarray:
    import torch

    net.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(x), 1024):
            st = torch.from_numpy(s[i : i + 1024]) if s is not None else None
            out.append(net(torch.from_numpy((x[i : i + 1024] - mu) / sd), st).numpy())
    return np.concatenate(out) if out else np.zeros(0)


def cmd_train(a: argparse.Namespace) -> dict[str, Any]:
    import torch

    torch.set_num_threads(a.threads)
    bars = load_bars(a.bars)
    tr = load_fills(a.fills, a.segments)
    va = load_fills(a.val_fills, a.val_segments)
    xt, okt = sequences(tr, bars)
    xv, okv = sequences(va, bars)
    tr, xt = tr[okt].reset_index(drop=True), xt[okt]
    va, xv = va[okv].reset_index(drop=True), xv[okv]
    yt = np.clip(tr["markout_30s"].to_numpy(np.float32), -20, 20)
    yv = np.clip(va["markout_30s"].to_numpy(np.float32), -20, 20)
    mu = xt.reshape(-1, CHANNELS).mean(0).astype(np.float32)
    sd = (xt.reshape(-1, CHANNELS).std(0) + 1e-6).astype(np.float32)
    raw_t = signed(tr)
    smean, sscale = np.nanmean(raw_t, 0), np.nanstd(raw_t, 0) + 1e-9
    st = static(tr, smean, sscale) if a.with_static else None
    sv = static(va, smean, sscale) if a.with_static else None
    net = build_model(a.seed, len(FEATURES) if a.with_static else 0)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=1e-4)
    loss_fn = torch.nn.HuberLoss(delta=5.0)
    xt_n = torch.from_numpy((xt - mu) / sd)
    yt_t = torch.from_numpy(yt)
    rng = np.random.default_rng(a.seed)
    best, best_state, history = np.inf, None, []
    for epoch in range(a.epochs):
        net.train()
        perm = rng.permutation(len(xt_n))
        for i in range(0, len(perm), a.batch):
            b = perm[i : i + a.batch]
            opt.zero_grad()
            loss = loss_fn(net(xt_n[b], torch.from_numpy(st[b]) if st is not None else None), yt_t[b])
            loss.backward()
            opt.step()
        pv = predict(net, xv, mu, sd, sv)
        vloss = float(loss_fn(torch.from_numpy(pv), torch.from_numpy(yv)))
        ic = float(np.corrcoef(pv, yv)[0, 1])
        history.append({"epoch": epoch, "val_huber": vloss, "val_ic": ic})
        print(history[-1], flush=True)
        if vloss < best:
            best, best_state = vloss, {k: v.clone() for k, v in net.state_dict().items()}
    assert best_state is not None
    net.load_state_dict(best_state)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"state": best_state, "mu": mu, "sd": sd, "seed": a.seed, "static": bool(a.with_static), "smean": smean, "sscale": sscale},
        a.out,
    )
    pv = predict(net, xv, mu, sd, sv)
    return {
        "train_fills": len(tr),
        "val_fills": len(va),
        "history": history,
        "val_ic_transformer": float(np.corrcoef(pv, yv)[0, 1]),
        "val_ic_ridge": float(np.corrcoef(ridge(va), yv)[0, 1]),
    }


def economics(f: pd.DataFrame, pred: np.ndarray, hours: float) -> dict[str, Any]:
    keep = pred - FEE >= RULE_T
    net = f["markout_30s"].to_numpy() - FEE
    usd = np.where(keep, net * QUOTE_USD / 1e4, 0.0)
    block = (f["t"].to_numpy() // 900_000).astype(np.int64)
    per_block = pd.Series(usd).groupby(block).sum()
    lo, hi = stationary_bootstrap_ci(per_block.to_numpy() * 4, mean_block=3, n_boot=5000, seed=0)
    return {
        "kept_fills": int(keep.sum()),
        "kept_share": float(keep.mean()),
        "kept_net_bps": float(net[keep].mean()) if keep.any() else None,
        "usd_per_hour": float(usd.sum() / hours),
        "usd_per_hour_ci95": [float(lo), float(hi)],
        "ic": float(np.corrcoef(pred, f["markout_30s"].to_numpy())[0, 1]),
        "deciles": pd.DataFrame({"p": pred, "y": f["markout_30s"].to_numpy()})
        .assign(q=lambda d: pd.qcut(d.p.rank(method="first"), 10, labels=False) + 1)
        .groupby("q")
        .agg(predicted=("p", "mean"), realised=("y", "mean"), fills=("y", "size"))
        .reset_index()
        .to_dict("records"),
    }


def cmd_score(a: argparse.Namespace) -> dict[str, Any]:
    import torch

    torch.set_num_threads(a.threads)
    bars = load_bars(a.bars)
    f = load_fills(a.fills, a.segments)
    x, ok = sequences(f, bars)
    f, x = f[ok].reset_index(drop=True), x[ok]
    ck = torch.load(a.model, weights_only=False)
    net = build_model(ck["seed"], len(FEATURES) if ck.get("static") else 0)
    net.load_state_dict(ck["state"])
    pt = predict(net, x, ck["mu"], ck["sd"], static(f, ck["smean"], ck["sscale"]) if ck.get("static") else None)
    pr = ridge(f)
    hours = float(a.hours)
    return {
        "fills": len(f),
        "hours": hours,
        "transformer": economics(f, pt, hours),
        "ridge": economics(f, pr, hours),
        "all_fills": {"net_bps": float((f["markout_30s"] - FEE).mean())},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--bars", type=Path, required=True)
    t.add_argument("--fills", type=Path, nargs="+", required=True)
    t.add_argument("--segments", nargs="*")
    t.add_argument("--val-fills", type=Path, nargs="+", required=True)
    t.add_argument("--val-segments", nargs="*")
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--report", type=Path, required=True)
    t.add_argument("--epochs", type=int, default=12)
    t.add_argument("--batch", type=int, default=256)
    t.add_argument("--lr", type=float, default=1e-3)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--threads", type=int, default=1)
    t.add_argument("--with-static", action="store_true", help="also feed the ridge model's features to the head")
    s = sub.add_parser("score")
    s.add_argument("--bars", type=Path, required=True)
    s.add_argument("--fills", type=Path, nargs="+", required=True)
    s.add_argument("--segments", nargs="*")
    s.add_argument("--model", type=Path, required=True)
    s.add_argument("--hours", type=float, required=True)
    s.add_argument("--report", type=Path, required=True)
    s.add_argument("--threads", type=int, default=1)
    a = ap.parse_args(argv)
    result = cmd_train(a) if a.cmd == "train" else cmd_score(a)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=1, default=float)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
