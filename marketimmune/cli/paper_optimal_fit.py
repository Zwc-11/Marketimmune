"""Solve ``optimal@``'s quoting policy: a market maker's optimal control problem, calibrated per coin on
the selection hours (``paper.optimal``).

    python -m marketimmune.cli.paper_optimal_fit --samples data/paper/factors/samples.parquet \\
        --fills data/paper/immune/fills_night.parquet data/paper/immune/fills_live.parquet \\
        --policy marketimmune/paper/models/optimal.json --out eval/paper/optimal_fit_20261106.json

The model, one second a step:

- **Market state.** A linear prediction of the seen mid's next 10 s move from the signals A1 and
  the factor study found (gap z, microprice, wallet factor over 1 s and 5 s, taker imbalance),
  fitted by least squares per coin, cut into ``K`` states at its quantiles. The state moves by an
  estimated Markov chain ``P``.
- **Price.** In state ``k`` the mid drifts ``mu_k`` bps a second, with variance ``sigma^2`` a second.
- **Fills.** A bid (ask) at the touch fills within the second with probability ``lambda_k`` and the
  fill is worth ``e_k`` bps over its first second (spread edge plus the move against it), both
  measured on every touch fill of the selection hours in state ``k``.
- **Reward** for a position of ``q`` quotes, per step, in bps of one quote:
  ``q * mu_k - phi * q^2 * sigma^2 + [bid] lambda_k^b (e_k^b - fee) + [ask] lambda_k^a (e_k^a - fee)``.
- **Value iteration** (discount ``gamma`` a second) over q in -Q..Q and the K states, actions
  {bid, ask, both, neither}, gives the policy: which sides to quote for each position and state.

The policy is a table per coin and ``phi``. Nothing from the held-out or test hours is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.logger import init_logger
from marketimmune.paper.optimal import REGIME_FEATURES

logger = init_logger(__name__)
FloatArray = npt.NDArray[np.float64]
SAMPLE_COLUMNS = {"gap_z": "gap_z", "micro": "micro", "wallet1_z": "wallet_1s_z", "wallet5_z": "wallet_z", "imbalance": "imbalance"}
K = 7
Q = 4
FEE_BPS = 1.5
GAMMA = 0.998
PHIS = (0.0, 0.01, 0.05, 0.2)
LATENCY_MS = 200


def per_second(samples: pd.DataFrame) -> pd.DataFrame:
    """One row per coin, segment and whole second: the last 100 ms sample of that second."""
    s = samples.copy()
    s["sec"] = s["t_ms"] // 1_000
    return s.sort_values("t_ms").groupby(["segment", "coin", "sec"], as_index=False).last()


def solve(
    mu: FloatArray, var: float, lam_b: FloatArray, lam_a: FloatArray, e_b: FloatArray, e_a: FloatArray, p: FloatArray, phi: float
) -> tuple[FloatArray, npt.NDArray[np.int64]]:
    """Value iteration. Returns the value and the policy (0 none, 1 bid, 2 ask, 3 both), shape
    (2Q+1, K)."""
    qs = np.arange(-Q, Q + 1)
    v: FloatArray = np.zeros((qs.size, K))
    pol: npt.NDArray[np.int64] = np.zeros((qs.size, K), dtype=np.int64)
    acts = ((0, 0), (1, 0), (0, 1), (1, 1))
    for _ in range(20_000):
        ev = v @ p.T  # E[V(q, k') | k], shape (2Q+1, K)
        best: FloatArray = np.full_like(v, -np.inf)
        pol = np.zeros((qs.size, K), dtype=np.int64)
        for ai, (b, a) in enumerate(acts):
            val = np.zeros_like(v)
            for i, q in enumerate(qs):
                lb = lam_b * b * (q < Q)
                la = lam_a * a * (q > -Q)
                r = q * mu - phi * q * q * var + lb * (e_b - FEE_BPS) + la * (e_a - FEE_BPS)
                # independent fills: q+1 w.p. lb(1-la), q-1 w.p. la(1-lb), q otherwise
                up, dn = min(i + 1, qs.size - 1), max(i - 1, 0)
                cont = lb * (1 - la) * ev[up] + la * (1 - lb) * ev[dn] + (1 - lb * (1 - la) - la * (1 - lb)) * ev[i]
                val[i] = r + GAMMA * cont
            better = val > best
            best = np.asarray(np.where(better, val, best), np.float64)
            pol = np.asarray(np.where(better, ai, pol), np.int64)
        if np.max(np.abs(best - v)) < 1e-9:
            v = best
            break
        v = best
    return v, pol


def calibrate_coin(sec: pd.DataFrame, fills: pd.DataFrame) -> dict[str, Any]:
    sec = sec.sort_values(["segment", "t_ms"]).reset_index(drop=True)
    x = np.column_stack([sec[SAMPLE_COLUMNS[k]].to_numpy(np.float64) for k in REGIME_FEATURES])
    x = np.clip(x, -10, 10)
    nxt1 = sec.groupby("segment")["mid"].shift(-1)
    nxt10 = sec.groupby("segment")["mid"].shift(-10)
    gap_ok = (sec.groupby("segment")["sec"].shift(-10) - sec["sec"]) == 10
    y10 = np.log(nxt10 / sec["mid"]).to_numpy() * 1e4
    ok = np.isfinite(y10) & gap_ok.to_numpy()
    a = np.column_stack([np.ones(ok.sum()), x[ok]])
    coef = np.linalg.lstsq(a, y10[ok], rcond=None)[0]
    pred = coef[0] + x @ coef[1:]
    edges = np.quantile(pred, np.linspace(0, 1, K + 1)[1:-1])
    state = np.searchsorted(edges, pred, side="right")
    d1 = np.log(nxt1 / sec["mid"]).to_numpy() * 1e4
    one = ((sec.groupby("segment")["sec"].shift(-1) - sec["sec"]) == 1).to_numpy() & np.isfinite(d1)
    mu = np.array([d1[one & (state == k)].mean() if (one & (state == k)).any() else 0.0 for k in range(K)])
    var = float(np.var(d1[one]))
    p = np.full((K, K), 1e-9)
    nxt_state = pd.Series(state).groupby(sec["segment"]).shift(-1).to_numpy()
    for k0, k1 in zip(state[one], nxt_state[one], strict=True):
        p[k0, int(k1)] += 1
    p /= p.sum(axis=1, keepdims=True)
    seconds = np.bincount(state, minlength=K).astype(np.float64)
    # each fill's state: the second whose last sample is at least LATENCY_MS before it
    t_sec = sec["t_ms"].to_numpy()
    lam = {1: np.zeros(K), -1: np.zeros(K)}
    e = {1: np.zeros(K), -1: np.zeros(K)}
    for side in (1, -1):
        f = fills[fills["side"] == side]
        counts = np.zeros(K)
        marks: list[list[float]] = [[] for _ in range(K)]
        for seg, g in f.groupby("segment"):
            m = (sec["segment"] == seg).to_numpy()
            ts, st, mids = t_sec[m], state[m], sec["mid"].to_numpy()[m]
            i = np.searchsorted(ts, g["t"].to_numpy() - LATENCY_MS, side="right") - 1
            j = np.searchsorted(ts, g["t"].to_numpy() + 1_000, side="left")
            good = (i >= 0) & (j < ts.size)
            for ii, jj, px in zip(i[good], j[good], g["px"].to_numpy()[good], strict=True):
                k = st[ii]
                counts[k] += 1
                marks[k].append(side * (mids[jj] / px - 1) * 1e4)
        lam[side] = np.minimum(counts / np.maximum(seconds, 1), 0.95)
        e[side] = np.array([np.mean(mk) if len(mk) >= 20 else -10.0 for mk in marks])  # too few fills: never worth it
    policies = {}
    for phi in PHIS:
        _, pol = solve(mu, var, lam[1], lam[-1], e[1], e[-1], p, phi)
        policies[str(phi)] = pol.tolist()
    return {
        "coef": [float(c) for c in coef],
        "edges": [float(v) for v in edges],
        "policies": policies,
        "calibration": {
            "mu_bps_per_s": [round(float(v), 4) for v in mu],
            "var_bps2_per_s": round(var, 4),
            "seconds": seconds.astype(int).tolist(),
            "fill_prob_bid": [round(float(v), 4) for v in lam[1]],
            "fill_prob_ask": [round(float(v), 4) for v in lam[-1]],
            "fill_value_bid_bps": [round(float(v), 3) for v in e[1]],
            "fill_value_ask_bps": [round(float(v), 3) for v in e[-1]],
            "stay_prob": [round(float(p[k, k]), 3) for k in range(K)],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--fills", type=Path, nargs="+", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    samples = pd.read_parquet(args.samples)
    samples = samples[~samples["segment"].str.contains("T2003")]  # held out: not used to fit
    fills = pd.concat([pd.read_parquet(p) for p in args.fills], ignore_index=True)
    fills = fills[fills["part"] == "selection"]
    sec = per_second(samples)
    out: dict[str, Any] = {
        "K": K,
        "Q": Q,
        "fee_bps": FEE_BPS,
        "gamma": GAMMA,
        "phis": list(PHIS),
        "features": list(REGIME_FEATURES),
        "coins": {},
    }
    for coin, g in sec.groupby("coin"):
        out["coins"][str(coin)] = calibrate_coin(g, fills[fills["coin"] == coin])
        logger.info(f"{coin}: mu {out['coins'][str(coin)]['calibration']['mu_bps_per_s']}")
    args.policy.parent.mkdir(parents=True, exist_ok=True)
    args.policy.write_text(
        json.dumps(
            {k: v for k, v in out.items()}
            | {"coins": {c: {k: d[k] for k in ("coef", "edges", "policies")} for c, d in out["coins"].items()}},
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
