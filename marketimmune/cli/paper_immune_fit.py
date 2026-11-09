"""Fit ``immune@``'s fill-markout models (``paper.immune``) on the selection hours' touch fills.

    python -m marketimmune.cli.paper_immune_fit --fills data/paper/immune/fills_night.parquet \\
        data/paper/immune/fills_live.parquet --models marketimmune/paper/models \\
        --out eval/paper/immune_fit_20261106.json

Per horizon (10, 30, 60 s): ridge regression of the fill's markout on ``immune.FEATURES`` (signed
by the side; standardised on the selection fills and clipped at 5 standard deviations) with an
unpenalised intercept per coin, each fill weighted by its notional. The ridge penalty is chosen
by leave-one-segment-out error on the selection hours. Only ``part == "selection"`` rows are
fitted; the held-out rows are scored:

- the correlation of predicted and realised markout, and R^2;
- the realised markout by decile of the prediction;
- the fills a quoter would keep at each threshold (prediction minus the 1.5 bp fee at least
  ``t``): their share of fills, and their realised markout after the fee.

A gradient-boosted benchmark (LightGBM, if installed) on the same rows shows what a nonlinear
model would add; it is not deployed.
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
from marketimmune.paper.immune import FEATURES, SIGNED, FillModel

logger = init_logger(__name__)
FloatArray = npt.NDArray[np.float64]
HORIZONS_S = (10, 30, 60)
ALPHAS = (0.1, 1.0, 10.0, 100.0, 1_000.0, 10_000.0)
CLIP = 5.0
FEE_BPS = 1.5
THRESHOLDS = (-1.0, -0.5, 0.0, 0.5, 1.0, 2.0)


def design(df: pd.DataFrame, mean: FloatArray, scale: FloatArray, coins: list[str]) -> tuple[FloatArray, FloatArray]:
    side = df["side"].to_numpy(np.float64)
    raw = np.column_stack([df[k].to_numpy(np.float64) * (side if k in SIGNED else 1.0) for k in FEATURES])
    z = np.clip((raw - mean) / np.where(scale > 0, scale, 1.0), -CLIP, CLIP)
    d = np.column_stack([(df["coin"] == c).to_numpy(np.float64) for c in coins])
    return z, d


def signed_raw(df: pd.DataFrame) -> FloatArray:
    side = df["side"].to_numpy(np.float64)
    return np.column_stack([df[k].to_numpy(np.float64) * (side if k in SIGNED else 1.0) for k in FEATURES])


def ridge(z: FloatArray, d: FloatArray, y: FloatArray, w: FloatArray, alpha: float) -> tuple[FloatArray, FloatArray]:
    """Weighted least squares with a ridge penalty on the feature weights only."""
    a = np.column_stack([d, z])
    sw = np.sqrt(w)
    aw, yw = a * sw[:, None], y * sw
    pen = np.zeros(a.shape[1])
    pen[d.shape[1] :] = alpha
    beta: FloatArray = np.asarray(np.linalg.solve(aw.T @ aw + np.diag(pen) + 1e-9 * np.eye(a.shape[1]), aw.T @ yw), dtype=np.float64)
    return beta[: d.shape[1]], beta[d.shape[1] :]


def wcorr(x: FloatArray, y: FloatArray, w: FloatArray) -> float:
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    cov = np.average((x - mx) * (y - my), weights=w)
    return float(cov / np.sqrt(np.average((x - mx) ** 2, weights=w) * np.average((y - my) ** 2, weights=w)))


def score(pred: FloatArray, y: FloatArray, w: FloatArray) -> dict[str, Any]:
    ss_res = float(np.sum(w * (y - pred) ** 2))
    ss_tot = float(np.sum(w * (y - np.average(y, weights=w)) ** 2))
    deciles = pd.qcut(pred, 10, labels=False, duplicates="drop")
    by_decile = [
        {
            "decile": int(q),
            "predicted": round(float(np.average(pred[deciles == q], weights=w[deciles == q])), 3),
            "realised": round(float(np.average(y[deciles == q], weights=w[deciles == q])), 3),
            "fills": int((deciles == q).sum()),
        }
        for q in sorted(set(deciles.tolist()))
    ]
    kept = []
    for t in THRESHOLDS:
        m = pred - FEE_BPS >= t
        kept.append(
            {
                "threshold_bps": t,
                "share_of_fills": round(float(m.mean()), 4),
                "realised_after_fee_bps": round(float(np.average(y[m], weights=w[m]) - FEE_BPS), 3) if m.any() else None,
                "dropped_after_fee_bps": round(float(np.average(y[~m], weights=w[~m]) - FEE_BPS), 3) if (~m).any() else None,
            }
        )
    return {
        "fills": int(len(y)),
        "corr": round(wcorr(pred, y, w), 4),
        "r2": round(1.0 - ss_res / ss_tot, 4),
        "all_fills_after_fee_bps": round(float(np.average(y, weights=w) - FEE_BPS), 3),
        "by_decile": by_decile,
        "kept_by_threshold": kept,
    }


def fit_horizon(sel: pd.DataFrame, held: pd.DataFrame, h: int) -> tuple[FillModel, dict[str, Any]]:
    label = f"markout_{h}s"
    sel = sel[np.isfinite(sel[label])]
    held = held[np.isfinite(held[label])]
    raw = signed_raw(sel)
    w = (sel["qty"] * sel["px"]).to_numpy(np.float64)
    mean = np.average(raw, axis=0, weights=w)
    scale = np.sqrt(np.average((raw - mean) ** 2, axis=0, weights=w))
    coins = sorted(sel["coin"].unique())
    z, d = design(sel, mean, scale, coins)
    y = sel[label].to_numpy(np.float64)
    segs = sel["segment"].to_numpy()
    cv = {}
    for alpha in ALPHAS:
        err = 0.0
        for s in sorted(set(segs)):
            tr, te = segs != s, segs == s
            b0, b = ridge(z[tr], d[tr], y[tr], w[tr], alpha)
            err += float(np.sum(w[te] * (y[te] - d[te] @ b0 - z[te] @ b) ** 2))
        cv[alpha] = err / float(w.sum())
    alpha = min(cv, key=lambda a: cv[a])
    b0, b = ridge(z, d, y, w, alpha)
    model = FillModel(
        horizon_s=h,
        mean=tuple(float(v) for v in mean),
        scale=tuple(float(v) for v in scale),
        coef=tuple(float(v) for v in b),
        intercept={c: float(v) for c, v in zip(coins, b0, strict=True)}
        | {"*": float(np.average(b0, weights=[float(w[sel["coin"] == c].sum()) for c in coins]))},
        clip=CLIP,
        info={"alpha": alpha, "fills": int(len(sel)), "segments": sorted(set(segs.tolist())), "weights": "notional"},
    )
    hz, hd = design(held, mean, scale, coins)
    hw = (held["qty"] * held["px"]).to_numpy(np.float64)
    hy = held[label].to_numpy(np.float64)
    pred_held = hd @ b0 + hz @ b
    pred_sel = d @ b0 + z @ b
    report: dict[str, Any] = {
        "horizon_s": h,
        "alpha": alpha,
        "cv_mse_by_alpha": {str(k): round(v, 4) for k, v in cv.items()},
        "coef_per_sd": {k: round(float(v), 4) for k, v in zip(FEATURES, b, strict=True)},
        "intercept_by_coin": {c: round(float(v), 3) for c, v in zip(coins, b0, strict=True)},
        "selection": score(pred_sel, y, w),
        "held_out": score(pred_held, hy, hw),
    }
    try:
        import lightgbm as lgb

        x = np.column_stack([raw, d])
        hx = np.column_stack([signed_raw(held), hd])
        gbm = lgb.LGBMRegressor(
            n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.8, subsample_freq=1, verbose=-1
        )
        gbm.fit(x, y, sample_weight=w)
        gbm_pred = np.asarray(gbm.predict(hx), np.float64)
        report["lightgbm_held_out"] = {k: v for k, v in score(gbm_pred, hy, hw).items() if k in ("corr", "r2")}
    except ImportError:
        report["lightgbm_held_out"] = None
    return model, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fills", type=Path, nargs="+", required=True)
    parser.add_argument("--models", type=Path, required=True, help="directory for immune_<h>s.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    df = pd.concat([pd.read_parquet(p) for p in args.fills], ignore_index=True)
    sel, held = df[df["part"] == "selection"], df[df["part"] == "held_out"]
    report: dict[str, Any] = {"fills": {"selection": len(sel), "held_out": len(held)}, "fee_bps": FEE_BPS, "horizons": []}
    args.models.mkdir(parents=True, exist_ok=True)
    for h in HORIZONS_S:
        model, rep = fit_horizon(sel, held, h)
        (args.models / f"immune_{h}s.json").write_text(json.dumps(model.to_json(), indent=1) + "\n", encoding="utf-8")
        report["horizons"].append(rep)
        logger.info(f"{h}s: alpha {rep['alpha']}, held-out corr {rep['held_out']['corr']}, r2 {rep['held_out']['r2']}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
