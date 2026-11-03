"""Score the forced-flow forecaster against the plan's baselines (B.5).

Input is the grid frame ``forced_forecast`` writes: one row per grid time with
the forecast, the baselines' raw signals and what happened next. Every comparison
is walk-forward by day: a test day's calibration uses only earlier scored days.

Predictors per side ``j`` and horizon ``h``:

- ``zero``.
- ``persistence``: forced notional on side ``j`` in the previous ``h``.
- ``oi_change``: open interest on the side that would be forced (longs for bids)
  that disappeared over the previous 60 s.
- ``volatility``: EWMA per-second volatility of the mid.
- ``heatmap``: notional with a point liquidation price within 1% of the mark.
- ``model``: the forecaster's ``F_j``; ``model_raw`` is the expected notional as
  is, ``model`` is the same signal calibrated like the baselines.
- ``model_persist``: the model's bins split by whether any forced flow hit side
  ``j`` in the previous ``h``. Forced flow comes in bursts that persistence
  captures and the position book does not; this asks whether the book adds to it.

Baselines are ranking signals, not forecasts in USD, so each signal (the model's
included) is mapped to a forecast by binning: deciles of its positive values on
earlier days plus a zero bin, and per bin the training tau-quantile (pinball) or
event rate (Brier). The comparison is then about information, not scale.

Targets: realised forced notional in ``(t, t + h]`` (pinball at 0.5 and 0.9) and
the binary "at least ``binary_usd`` forced on side ``j`` within ``h``" (Brier with
Murphy's decomposition). Lead time: for each onset (first forced block on a
side after 60 s without any), whether the signal was positive and above its alarm
threshold (the training 95th percentile) at the last grid time before the onset,
and for how long it had been (capped at 300 s). Persistence cannot alarm before an
onset by construction. Regimes: grid times whose volatility is in the top 5%
(``fast``) vs the rest (``quiet``). Day-level Diebold-Mariano and stationary
bootstrap intervals come from ``models.compare``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from marketimmune.forced.forecaster import BINARY_USD, brier_decomposition
from marketimmune.models.compare import compare_rungs, diebold_mariano, pinball_loss, stationary_bootstrap_ci

FloatArray = npt.NDArray[np.float64]
OI_LOOKBACK_S = 60.0
SIDES = ("bid", "ask")
OI_SIDE = {"bid": "oi_long_usd", "ask": "oi_short_usd"}
BASELINES = ("persistence", "oi_change", "volatility", "heatmap")
SUMMARY_KEYS = ("rows", "days", "loss_base", "loss_challenger", "mean_daily_improvement", "days_improved", "bootstrap_ci_95")


def bin_edges(signal: FloatArray, n_bins: int = 10) -> FloatArray:
    """Interior decile edges of the positive values (zero gets its own bin)."""
    pos = signal[signal > 0.0]
    if pos.size == 0:
        return np.zeros(0)
    edges: FloatArray = np.unique(np.quantile(pos, np.linspace(0.0, 1.0, n_bins + 1)[1:-1]))
    return edges


def assign_bins(signal: FloatArray, edges: FloatArray) -> npt.NDArray[np.int64]:
    out: npt.NDArray[np.int64] = np.where(signal > 0.0, 1 + np.searchsorted(edges, signal, side="right"), 0).astype(np.int64)
    return out


def keyed_map(
    train_key: npt.NDArray[np.int64], train_y: FloatArray, test_key: npt.NDArray[np.int64], stat: Callable[[FloatArray], float]
) -> FloatArray:
    """``stat`` of the training target per key; unseen keys get the overall ``stat``."""
    size = int(max(train_key.max(initial=0), test_key.max(initial=0))) + 1
    table = np.full(size, stat(train_y) if train_y.size else 0.0)
    for b in np.unique(train_key):
        table[b] = stat(train_y[train_key == b])
    out: FloatArray = table[test_key]
    return out


def binned_map(
    train_signal: FloatArray,
    train_y: FloatArray,
    test_signal: FloatArray,
    stat: Callable[[FloatArray], float],
    n_bins: int = 10,
    train_flag: npt.NDArray[np.bool_] | None = None,
    test_flag: npt.NDArray[np.bool_] | None = None,
) -> FloatArray:
    """``stat`` of the training target within the test signal's training bin, split
    further by ``flag`` when given (used to add the persistence indicator)."""
    edges = bin_edges(train_signal, n_bins)
    btr, bte = assign_bins(train_signal, edges), assign_bins(test_signal, edges)
    if train_flag is not None and test_flag is not None:
        btr = btr + (edges.size + 2) * train_flag.astype(np.int64)
        bte = bte + (edges.size + 2) * test_flag.astype(np.int64)
    return keyed_map(btr, train_y, bte, stat)


def long_frame(frame: pd.DataFrame, horizons: list[float], grid_s: float) -> pd.DataFrame:
    """One row per grid time and side, with every predictor's raw signal."""
    lag = max(1, round(OI_LOOKBACK_S / grid_s))
    parts = []
    for side in SIDES:
        part = pd.DataFrame(
            {
                "date": frame["date"].to_numpy(),
                "ts_ms": frame["ts_ms"].to_numpy(),
                "side": side,
                "sig_volatility": frame["sigma_1s"].fillna(0.0).to_numpy(),
                "sig_heatmap": frame[f"heatmap_{side}_1pct"].to_numpy(),
            }
        )
        oi = frame[OI_SIDE[side]]
        part["sig_oi_change"] = np.maximum((oi.groupby(frame["date"]).shift(lag) - oi).fillna(0.0).to_numpy(), 0.0)
        part["onset_ms"] = frame[f"onset_{side}_ms"].to_numpy()
        for h in horizons:
            hh = f"{int(h)}s"
            part[f"y_{hh}"] = frame[f"real_{side}_{hh}"].to_numpy()
            part[f"sig_model_{hh}"] = frame[f"F_{side}_{hh}"].to_numpy()
            part[f"sig_persistence_{hh}"] = frame[f"persist_{side}_{hh}"].to_numpy()
            part[f"p_model_{hh}"] = frame[f"P_{side}_{hh}"].to_numpy()
        parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    sig_cols = [c for c in out.columns if c.startswith("sig_")]
    out[sig_cols] = out[sig_cols].fillna(0.0)
    return out


def _signal(name: str, hh: str) -> str:
    return f"sig_{name}_{hh}" if name in ("model", "persistence") else f"sig_{name}"


def walk_forward(long: pd.DataFrame, value: Callable[[pd.DataFrame, pd.DataFrame], FloatArray]) -> tuple[npt.NDArray[np.bool_], FloatArray]:
    """Apply ``value(train, test)`` to each day with at least one earlier day."""
    days = np.sort(long["date"].unique())
    out = np.full(len(long), np.nan)
    scored = np.zeros(len(long), dtype=bool)
    dates = long["date"].to_numpy()
    for d in days[1:]:
        test = dates == d
        out[test] = value(long[dates < d], long[test])
        scored |= test
    return scored, out


def _summary(cmp: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for regime, entry in cmp.items():
        if not isinstance(entry, dict):
            continue
        s = {k: entry[k] for k in SUMMARY_KEYS if k in entry}
        if "diebold_mariano" in entry:
            dm = entry["diebold_mariano"]
            s["dm_t"], s["dm_p"] = dm["t_stat"], dm["p_value"]
        out[regime] = s
    return out


def lead_times(long: pd.DataFrame, signal: FloatArray, threshold: FloatArray, grid_s: float, cap_s: float = 300.0) -> pd.DataFrame:
    """Per onset (grouped by date and side, in first-seen order): whether the alarm was on at the
    last grid time before it, and for how long it had been on."""
    group = long.groupby(["date", "side"], sort=False).ngroup().to_numpy()
    order = np.argsort(group, kind="stable")
    a = ((signal >= threshold) & (signal > 0.0))[order]
    idx = np.arange(a.size)
    first = np.r_[True, group[order][1:] != group[order][:-1]]
    # length of the alarm run ending at each row, in grid steps; a run never crosses a group
    last_off = np.maximum.accumulate(np.where(~a, idx, np.where(first, idx - 1, -1)))
    run = np.where(a, idx - last_off, 0).astype(np.float64)
    onset, ts = long["onset_ms"].to_numpy()[order], long["ts_ms"].to_numpy()[order]
    at = np.flatnonzero(~np.isnan(onset))
    hit = a[at]
    lead = np.where(hit, np.minimum((onset[at] - ts[at]) / 1000.0 + (run[at] - 1.0) * grid_s, cap_s), 0.0)
    return pd.DataFrame({"date": long["date"].to_numpy()[order][at], "hit": hit, "lead_s": lead})


def _pairs(reference: str) -> list[tuple[str, str]]:
    """(challenger, base) pairs: the model against the reference and every baseline, and the
    model split by persistence against persistence."""
    return [*(("model", base) for base in (reference, *BASELINES)), ("model_persist", "persistence")]


def _calibrate(long: pd.DataFrame, signal: str, target: str, stat: Callable[[FloatArray], float], flag: str | None = None) -> FloatArray:
    """Walk-forward :func:`binned_map` of ``signal`` to ``target``, bins split by ``flag > 0`` when given."""

    def fit(tr: pd.DataFrame, te: pd.DataFrame) -> FloatArray:
        train_flag = None if flag is None else tr[flag].to_numpy() > 0
        test_flag = None if flag is None else te[flag].to_numpy() > 0
        return binned_map(
            tr[signal].to_numpy(np.float64),
            tr[target].to_numpy(np.float64),
            te[signal].to_numpy(np.float64),
            stat,
            train_flag=train_flag,
            test_flag=test_flag,
        )

    return walk_forward(long, fit)[1]


def evaluate_forecasts(
    frame: pd.DataFrame,
    horizons: list[float],
    *,
    grid_s: float = 10.0,
    binary_usd: float = BINARY_USD,
    fast_quantile: float = 0.95,
    seed: int = 0,
) -> dict[str, Any]:
    long = long_frame(frame, horizons, grid_s)
    fast_cut = float(np.quantile(long["sig_volatility"], fast_quantile))
    res: dict[str, Any] = {
        "grid_points": len(frame),
        "days": int(frame["date"].nunique()),
        "binary_usd": binary_usd,
        "fast_sigma_1s_cut": fast_cut,
    }
    scored = long["date"].to_numpy() != long["date"].min()  # the first day only calibrates
    sub = long[scored]
    days = sub["date"].to_numpy()
    fast = sub["sig_volatility"].to_numpy() >= fast_cut
    regimes = {"fast": fast, "quiet": ~fast}
    for h in horizons:
        hh = f"{int(h)}s"
        ycol, evcol, model, persist = f"y_{hh}", f"ev_{hh}", f"sig_model_{hh}", f"sig_persistence_{hh}"
        y_all = long[ycol].to_numpy(dtype=np.float64)
        long[evcol] = (y_all >= binary_usd).astype(np.float64)
        entry: dict[str, Any] = {
            "share_windows_with_forced_flow": float(np.mean(y_all > 0)),
            f"share_windows_above_{int(binary_usd)}": float(np.mean(y_all >= binary_usd)),
            "scored_rows": int(scored.sum()),
            "scored_days": len(np.unique(days)),
        }
        y = y_all[scored]
        for tau in (0.5, 0.9):
            q = f"q{round(tau * 100)}"

            def quantile(v: FloatArray, tau: float = tau) -> float:
                return float(np.quantile(v, tau))

            preds = {name: _calibrate(long, _signal(name, hh), ycol, quantile) for name in ("model", *BASELINES)}
            preds["model_persist"] = _calibrate(long, model, ycol, quantile, flag=persist)
            preds["model_raw"] = long[model].to_numpy(dtype=np.float64)
            preds["zero"] = np.zeros(len(long))
            entry[f"pinball_{q}"] = {
                name: {
                    "all": float(pinball_loss(y, p[scored], tau).mean()),
                    "fast": float(pinball_loss(y[fast], p[scored][fast], tau).mean()),
                    "quiet": float(pinball_loss(y[~fast], p[scored][~fast], tau).mean()),
                }
                for name, p in preds.items()
            }
            entry[f"dm_pinball_{q}"] = {
                f"{chal}_vs_{base}": _summary(
                    compare_rungs(days, y, preds[base][scored], preds[chal][scored], loss="pinball", tau=tau, regimes=regimes, seed=seed)
                )
                for chal, base in _pairs("zero")
            }

        def rate(v: FloatArray) -> float:
            return float(v.mean())

        def climatology(tr: pd.DataFrame, te: pd.DataFrame, evcol: str = evcol) -> FloatArray:
            return np.full(len(te), float(tr[evcol].to_numpy(np.float64).mean()))

        probs = {name: _calibrate(long, _signal(name, hh), evcol, rate) for name in ("model", *BASELINES)}
        probs["climatology"] = walk_forward(long, climatology)[1]
        probs["model_persist"] = _calibrate(long, model, evcol, rate, flag=persist)
        probs["model_raw"] = long[f"p_model_{hh}"].to_numpy(dtype=np.float64)
        event = long[evcol].to_numpy()[scored]
        entry["brier"] = {name: brier_decomposition(np.clip(p[scored], 0.0, 1.0), event) for name, p in probs.items()}
        entry["dm_brier"] = {
            f"{chal}_vs_{base}": _summary(
                compare_rungs(days, event, probs[base][scored], probs[chal][scored], loss="brier", regimes=regimes, seed=seed)
            )
            for chal, base in _pairs("climatology")
        }
        res[hh] = entry
    res["lead_time"] = _lead_time_report(long, horizons, grid_s, seed)
    res["cascade"] = {}
    for h in horizons:
        hh = f"{int(h)}s"
        total = frame[f"F_bid_{hh}"] + frame[f"F_ask_{hh}"]
        rel = (frame[f"cascade_{hh}"] / total.where(total > 0)).dropna()
        res["cascade"][hh] = {
            "mean_relative_change": float(rel.mean()) if rel.size else 0.0,
            "p99_relative_change": float(rel.quantile(0.99)) if rel.size else 0.0,
            "share_above_1pct": float((rel.abs() > 0.01).mean()) if rel.size else 0.0,
        }
    return res


def _lead_time_report(long: pd.DataFrame, horizons: list[float], grid_s: float, seed: int) -> dict[str, Any]:
    """Alarm at the 95th training percentile of each signal (60 s horizon for the model)."""
    hh = f"{int(max(horizons))}s"
    out: dict[str, Any] = {"horizon": hh, "onsets": int(long["onset_ms"].notna().sum())}
    per_day: dict[str, pd.Series] = {}
    for name in ("model", *BASELINES):
        col = _signal(name, hh)

        def thr(tr: pd.DataFrame, te: pd.DataFrame, col: str = col) -> FloatArray:
            return np.full(len(te), float(np.quantile(tr[col].to_numpy(np.float64), 0.95)))

        scored, threshold = walk_forward(long, thr)
        sub = long[scored]
        lt = lead_times(sub, sub[col].to_numpy(np.float64), threshold[scored], grid_s)
        sig = sub[col].to_numpy(np.float64)
        alarm_rate = float(np.mean((sig >= threshold[scored]) & (sig > 0.0)))
        out[name] = {
            "onsets": len(lt),
            "hit_rate": float(lt["hit"].mean()) if len(lt) else 0.0,
            "median_lead_s_when_hit": float(lt.loc[lt["hit"], "lead_s"].median()) if lt["hit"].any() else 0.0,
            "mean_lead_s": float(lt["lead_s"].mean()) if len(lt) else 0.0,
            "alarm_rate": alarm_rate,
        }
        per_day[name] = lt.groupby("date").agg(lead_s=("lead_s", "mean"), hit=("hit", "mean"))
    for metric in ("hit", "lead_s"):
        d = (per_day["model"][metric] - per_day["heatmap"][metric]).dropna().to_numpy()
        if d.size >= 3:
            dm = diebold_mariano(d)
            out[f"model_minus_heatmap_{metric}"] = {
                "days": int(d.size),
                "mean": float(d.mean()),
                "dm_t": dm.t_stat,
                "dm_p": dm.p_value,
                "bootstrap_ci_95": list(stationary_bootstrap_ci(d, seed=seed)),
            }
    return out
