"""Read the decision journals of paper runs: where each strategy's fills made or lost money, what it saw
when it sent the orders that filled, and how often and how well it changed its quotes.

    python -m marketimmune.cli.paper_journal --runs data/paper/live/seg-* --out eval/paper/journal.json --md journal.md

Each run is a ``cli.paper_trade`` output directory with a ``journal/`` (``marketimmune.paper.journal``);
a run still going is read up to its last flush.

**Fills**, in bps of each fill's notional (``mid0``: the last Hyperliquid mid before the fill's block):

- ``spread``: side x (mid0 - px) / px;
- ``move_<h>``: side x (mid at block + h - mid0) / px, for h = 1 s, 10 s, 60 s, 300 s, 900 s and
  ``end`` (the run's last mid, where it is marked); a horizon past the run's end is marked there;
- ``fee``; ``net_<h>`` = spread + move_h - fee: what the fill earned if closed at the mid h later.
- ``markout_usd``: the same moves in USD, summed over the fills. At ``end`` it is the inventory PnL;
  the horizons in between show how long after its fills a strategy's positions make their money.

The strategy's PnL (each run marked to its last mid, from the minute counters) splits into
``spread_usd`` - ``fee_usd`` + ``inventory_usd``: everything the positions made or lost while held.
A strategy that makes money on its position timing shows negative ``net_60s`` and a positive
``inventory_usd``.

Mids come from the run's ``mids.parquet`` (every block) once the run has ended, else from the
journal's signals (one a second: ``move_1s`` is then coarse; see ``mids`` in the output).

**Splits** of the maker fills, by what the strategy saw when it sent the order and by how it filled:

- ``lean``: ``with`` when the gap pointed the fill's way (side x gap > 0), ``against`` otherwise;
- ``abs_z``: |gap| over the gap's volatility;
- ``burst``: the Hawkes ratio of the takers on the other side (the sell burst for a buy);
- ``age``: block of the fill less the block the order reached the book;
- ``queue``: ``alone`` when nothing was ahead when the order joined (a new level), else ``behind``;
- ``fill``: ``through`` when the trade went through the price, else ``at``;
- ``inventory``: ``open`` when the fill grew the position, ``close`` when it shrank it.

**Decisions**: side changes per coin and minute, the share of time quoted on both sides, one side or
none (from the minute counters), and the reasons with their numbers taken out. **Pulls**: after each
change that removed a side, the seen mid's move over the next 10 s towards that side (bps; positive
when the side pulled would have been filled and lost). ``hit``: the share of pulls with a positive
move. **Actions**: orders plus cancels a minute, and per USD filled (Hyperliquid allows one request
per 1 USDC traded, after a 10,000-request buffer).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.paper.journal import read

FloatArray = npt.NDArray[np.float64]
BPS = 1e4
HORIZONS_MS = {"1s": 1_000, "10s": 10_000, "60s": 60_000, "300s": 300_000, "900s": 900_000, "end": 1 << 50}
PULL_MS = 10_000
CTX = ("gap", "z", "fc", "m1", "sig", "bb", "sb", "spr")
SPLITS = ("lean", "abs_z", "burst", "age", "queue", "fill", "inventory")
DETAIL = ("touch", "gap@0.25", "gap@0.5", "improve+gap@0.25", "improve+gap@0.5")
NUMBER = re.compile(r"[-+]?\d+(\.\d+)?%?")


def lookup(ts: npt.NDArray[np.int64], px: FloatArray, t: FloatArray, *, before: bool = False, end: bool = True) -> FloatArray:
    """The last value at or before each ``t`` (strictly before with ``before``); NaN before the first.
    Past the last: the last (where the run is marked), or NaN without ``end``."""
    if ts.size == 0:
        return np.full(t.shape, np.nan)
    i = np.searchsorted(ts, t, side="left" if before else "right") - 1
    ok = (i >= 0) & (end | (t <= ts[-1]))
    out: FloatArray = np.where(ok, px[np.clip(i, 0, None)], np.nan)
    return out


def series(df: pd.DataFrame, coin: str, t: str) -> tuple[npt.NDArray[np.int64], FloatArray]:
    m = df[df["c"] == coin].sort_values(t, kind="stable")
    return m[t].to_numpy(np.int64), m["mid"].to_numpy(np.float64)


def run_fills(run: Path, signals: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """The run's fills with their markouts, and where the mids came from."""
    rows = list(read(run / "journal" / "fills.jsonl.gz"))
    if not rows:
        return pd.DataFrame(), "none"
    f = pd.DataFrame(rows)
    ctx = pd.DataFrame([r.get("ctx") or {} for r in rows], index=f.index)
    for k in CTX:
        f[f"ctx_{k}"] = pd.to_numeric(ctx[k], errors="coerce") if k in ctx else np.nan
    f = f.drop(columns=["ctx"])
    if (run / "mids.parquet").exists():
        mids = pq.read_table(run / "mids.parquet").to_pandas().rename(columns={"coin": "c", "t_ms": "blk"})
        source = "mids.parquet"
    else:
        mids = signals[["c", "blk", "mid"]].drop_duplicates(["c", "blk"])
        source = "signals (1 s)"
    parts = []
    for coin, g in f.groupby("c"):
        g = g.copy()
        ts, px = series(mids, str(coin), "blk")
        t = g["blk"].to_numpy(np.float64)
        mid0 = g["mid0"].astype(float).to_numpy()
        for h, ms in HORIZONS_MS.items():
            g[f"mid_{h}"] = lookup(ts, px, t + ms)
        g["mid0"] = np.where(np.isnan(mid0), lookup(ts, px, t, before=True), mid0)
        parts.append(g)
    f = pd.concat(parts, ignore_index=True)
    f["run"] = run.name
    return f, source


def with_markouts(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    px, side = f["px"].astype(float), f["side"].astype(float)
    f["notional"] = px * f["qty"].astype(float)
    f["spread"] = side * (f["mid0"] - px) / px * BPS
    f["fee_bps"] = f["fee"].astype(float) / f["notional"] * BPS
    for h in HORIZONS_MS:
        f[f"move_{h}"] = side * (f[f"mid_{h}"] - f["mid0"]) / px * BPS
        f[f"net_{h}"] = f["spread"] + f[f"move_{h}"] - f["fee_bps"]
    pos_after = f["pos"].astype(float)
    pos_before = pos_after - side * f["qty"].astype(float)
    f["inventory"] = np.where(np.abs(pos_after) > np.abs(pos_before) + 1e-12, "open", "close")
    gap = f["ctx_gap"]
    f["lean"] = np.where(gap.isna(), "none", np.where(side * gap > 0, "with", "against"))
    f["abs_z"] = pd.cut(f["ctx_z"].abs(), [0, 0.5, 1, 2, np.inf], right=False, labels=["<0.5", "0.5-1", "1-2", ">=2"])
    other = np.where(side > 0, f["ctx_sb"], f["ctx_bb"])
    f["burst"] = pd.cut(pd.Series(other, index=f.index), [0, 1, 2, 3, np.inf], right=False, labels=["<1", "1-2", "2-3", ">=3"])
    if "live" in f:
        age = (f["blk"] - f["live"].astype(float)) / 1_000
        f["age"] = pd.cut(age, [-np.inf, 1, 5, 30, np.inf], right=False, labels=["<1s", "1-5s", "5-30s", ">=30s"])
        f["queue"] = np.where(f["q0"].isna(), "unknown", np.where(f["q0"].astype(float) <= 0, "alone", "behind"))
        f["fill"] = np.where(f["through"].astype(bool), "through", "at")
    return f


def table(f: pd.DataFrame) -> dict[str, Any]:
    """Fills, filled USD and the components in bps (notional-weighted), net USD over 60 s."""
    w = f["notional"]
    out: dict[str, Any] = {"fills": int(len(f)), "notional_usd": round(float(w.sum()), 2)}
    for k in ("spread", "move_1s", "move_10s", "move_60s", "move_300s", "fee_bps", "net_1s", "net_10s", "net_60s", "net_300s"):
        ok = f[k].notna()
        out[k] = round(float((f.loc[ok, k] * w[ok]).sum() / w[ok].sum()), 3) if ok.any() and w[ok].sum() > 0 else None
    ok = f["net_60s"].notna()
    out["net_60s_usd"] = round(float((f.loc[ok, "net_60s"] * w[ok]).sum() / BPS), 2)
    out["markout_usd"] = {h: round(float((f[f"move_{h}"].fillna(0) * w).sum() / BPS), 2) for h in HORIZONS_MS}
    out["spread_usd"] = round(float((f["spread"].fillna(0) * w).sum() / BPS), 2)
    out["fee_usd"] = round(float(f["fee"].astype(float).sum()), 2)
    return out


def splits(f: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for col in SPLITS:
        if col not in f:
            continue
        rows = []
        for key, g in f.groupby(col, observed=True):
            rows.append({"bucket": str(key), "share": round(len(g) / len(f), 3), **table(g)})
        out[col] = rows
    return out


def decisions(run: Path, signals: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Per strategy: side changes, reasons, and how the mid moved after each pull."""
    seen = {coin: series(signals, str(coin), "t") for coin in signals["c"].unique()}
    prev: dict[tuple[str, str], str] = {}
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    changes: Counter[str] = Counter()
    pulls: dict[str, list[tuple[str, int, int, float]]] = defaultdict(list)  # coin, local ms, +1 bid / -1 ask pulled, mid
    for d in read(run / "journal" / "decisions.jsonl.gz"):
        key = (d["s"], d["c"])
        old, new = prev.get(key), d["sides"]
        prev[key] = new
        changes[d["s"]] += 1
        reasons[d["s"]][NUMBER.sub("#", d["why"])] += 1
        mid = (d.get("ctx") or {}).get("mid")
        if old is None or mid is None:
            continue
        for side, name in ((1, "bid"), (-1, "ask")):
            if quoted(old, name) and not quoted(new, name):
                pulls[d["s"]].append((d["c"], d["t"], side, float(mid)))
    out: dict[str, dict[str, Any]] = {}
    for s in changes:
        moves: list[float] = []
        for coin in {p[0] for p in pulls[s]} & set(seen):
            rows = [p for p in pulls[s] if p[0] == coin]
            t = np.asarray([p[1] for p in rows], np.float64)
            pulled = np.asarray([p[2] for p in rows], np.float64)
            mid = np.asarray([p[3] for p in rows], np.float64)
            later = lookup(*seen[coin], t + PULL_MS, end=False)
            moves += (-pulled * (later - mid) / mid * BPS)[~np.isnan(later)].tolist()
        m = np.asarray(moves)
        out[s] = {
            "changes": changes[s],
            "pulls": int(m.size),
            "pull_move_10s_bps": round(float(m.mean()), 3) if m.size else None,
            "pull_hit": round(float((m > 0).mean()), 3) if m.size else None,
            "reasons": dict(reasons[s].most_common(8)),
        }
    return out


def quoted(sides: str, side: str) -> bool:
    return sides == "both" or sides == side


def merge_decisions(parts: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for part in parts:
        for s, d in part.items():
            o = out.setdefault(s, {"changes": 0, "pulls": 0, "_move": 0.0, "_hit": 0.0, "reasons": Counter()})
            o["changes"] += d["changes"]
            if d["pulls"]:
                o["_move"] += d["pull_move_10s_bps"] * d["pulls"]
                o["_hit"] += d["pull_hit"] * d["pulls"]
                o["pulls"] += d["pulls"]
            o["reasons"].update(d["reasons"])
    for o in out.values():
        n = o["pulls"]
        o["pull_move_10s_bps"] = round(o.pop("_move") / n, 3) if n else None
        o["pull_hit"] = round(o.pop("_hit") / n, 3) if n else None
        o.pop("_move", None)
        o.pop("_hit", None)
        o["reasons"] = dict(o["reasons"].most_common(8))
    return out


def minutes_table(minutes: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s, g in minutes.groupby("s"):
        ms = pd.DataFrame(list(g["ms"]))
        total = float(ms.to_numpy().sum())
        coin_minutes = max(1, len(g))
        last = g.sort_values("t", kind="stable").groupby(["run", "c"])["equity"].last()
        out[str(s)] = {
            "pnl_usd": round(float(last.sum()), 2),
            "hours": round(float(g.groupby("run")["t"].agg(lambda t: t.max() - t.min()).sum()) / 3.6e6, 3),
            "coin_minutes": int(coin_minutes),
            "time_share": {k: round(float(ms[k].sum()) / total, 3) if total else None for k in ms.columns},
            "changes_per_coin_minute": round(float(g["changes"].sum()) / coin_minutes, 2),
            "actions": int((g["orders"] + g["cancels"]).sum()),
            "actions_per_minute": round(float((g["orders"] + g["cancels"]).sum()) / max(1, g[["run", "t"]].drop_duplicates().shape[0]), 1),
            "budget_drops": int(g["budget"].sum()),
        }
    return out


def score(runs: list[Path], detail: tuple[str, ...]) -> dict[str, Any]:
    fills, minutes, dec, sources = [], [], [], {}
    for run in runs:
        j = run / "journal"
        signals = pd.DataFrame(list(read(j / "signals.jsonl.gz")))
        if signals.empty:
            signals = pd.DataFrame({"t": [], "c": [], "blk": [], "mid": []})
        f, sources[run.name] = run_fills(run, signals)
        if not f.empty:
            fills.append(f)
        m = pd.DataFrame(list(read(j / "minutes.jsonl.gz")))
        if not m.empty:
            m["run"] = run.name
            minutes.append(m)
        dec.append(decisions(run, signals))
    allf = with_markouts(pd.concat(fills, ignore_index=True)) if fills else pd.DataFrame()
    mins = minutes_table(pd.concat(minutes, ignore_index=True)) if minutes else {}
    decs = merge_decisions(dec)
    strategies: dict[str, Any] = {}
    names = sorted(set(mins) | set(decs) | (set(allf["s"]) if not allf.empty else set()))
    for s in names:
        f = allf[allf["s"] == s] if not allf.empty else allf
        row: dict[str, Any] = {"strategy": s, **(table(f) if not f.empty else {"fills": 0})}
        row.update(mins.get(s, {}))
        row.update({k: v for k, v in decs.get(s, {}).items() if k != "reasons"})
        if "pnl_usd" in row and "spread_usd" in row:
            row["inventory_usd"] = round(row["pnl_usd"] - row["spread_usd"] + row["fee_usd"], 2)
        if row.get("notional_usd") and row.get("actions") is not None:
            row["actions_per_usd_filled"] = round(row["actions"] / row["notional_usd"], 3)
        if not f.empty and s in detail:
            row["splits"] = splits(f[f["kind"] == "maker"]) if (f["kind"] == "maker").any() else {}
            row["by_coin"] = {str(c): table(g) for c, g in f.groupby("c")}
        row["reasons"] = decs.get(s, {}).get("reasons", {})
        strategies[s] = row
    return {"runs": [r.name for r in runs], "mids": sources, "strategies": strategies}


def markdown(report: dict[str, Any]) -> str:
    rows = sorted(report["strategies"].values(), key=lambda r: -(r.get("pnl_usd") if r.get("pnl_usd") is not None else -1e18))
    hs = list(HORIZONS_MS)
    out = [
        f"Runs: {', '.join(report['runs'])}. Mids: {', '.join(f'{k} {v}' for k, v in report['mids'].items())}.",
        "",
        "PnL in USD (each run marked to its last mid) = spread - fees + inventory. Per fill, bps of notional: spread, the mid's move after the fill, net = spread + move - fee.",
        "",
        "| strategy | PnL $ | spread $ | fees $ | inventory $ | fills | filled $ | spread | move 1s | move 10s | move 60s | move 300s | net 60s | net 300s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def f(x: Any, d: int = 2) -> str:
        return "" if x is None else f"{x:,.{d}f}" if isinstance(x, float) else f"{x:,}"

    for r in rows:
        out.append(
            f"| `{r['strategy']}` | {f(r.get('pnl_usd'))} | {f(r.get('spread_usd'))} | {f(r.get('fee_usd'))} | {f(r.get('inventory_usd'))} "
            f"| {f(r.get('fills'))} | {f(r.get('notional_usd'), 0)} | {f(r.get('spread'))} | {f(r.get('move_1s'))} | {f(r.get('move_10s'))} "
            f"| {f(r.get('move_60s'))} | {f(r.get('move_300s'))} | {f(r.get('net_60s'))} | {f(r.get('net_300s'))} |"
        )
    out += [
        "",
        "Where the position PnL accrues: the mid's move after each fill, in USD summed over the fills, by horizon (`end`: the run's last mid, which is the inventory PnL).",
        "",
        "| strategy | " + " | ".join(hs) + " |",
        "|---|" + "---:|" * len(hs),
    ]
    for r in rows:
        if "markout_usd" in r:
            out.append(f"| `{r['strategy']}` | " + " | ".join(f(r["markout_usd"][h]) for h in hs) + " |")
    out += [
        "",
        "Decisions. Time quoted both sides / one side / none; side changes per coin and minute; after a pull, the mid's 10 s move towards the pulled side (bps) and the share of pulls it was positive; order actions.",
        "",
        "| strategy | time both / one / none | changes per coin-min | pulls | pull move 10s | pull hit | actions/min | actions per $ filled | budget drops |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        ts = r.get("time_share", {})
        one = (ts.get("bid") or 0) + (ts.get("ask") or 0)
        share = f"{ts.get('both') or 0:.0%} / {one:.0%} / {ts.get('none') or 0:.0%}" if ts and ts.get("both") is not None else ""
        out.append(
            f"| `{r['strategy']}` | {share} | {f(r.get('changes_per_coin_minute'))} | {f(r.get('pulls'))} | {f(r.get('pull_move_10s_bps'))} "
            f"| {f(r.get('pull_hit'))} | {f(r.get('actions_per_minute'), 0)} | {f(r.get('actions_per_usd_filled'))} | {f(r.get('budget_drops'))} |"
        )
    for r in rows:
        if "splits" not in r:
            continue
        out += ["", f"### `{r['strategy']}`: maker fills by split (bps of notional)", ""]
        out += [
            "| split | bucket | share | fills | spread | move 10s | move 60s | move 300s | net 60s | net 300s |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for col, buckets in r["splits"].items():
            for b in buckets:
                out.append(
                    f"| {col} | {b['bucket']} | {b['share']:.0%} | {f(b['fills'])} | {f(b.get('spread'))} | {f(b.get('move_10s'))} "
                    f"| {f(b.get('move_60s'))} | {f(b.get('move_300s'))} | {f(b.get('net_60s'))} | {f(b.get('net_300s'))} |"
                )
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--detail", default=",".join(DETAIL), help="strategies to split by signal, age, queue and inventory")
    args = parser.parse_args(argv)
    runs = [r for r in args.runs if (r / "journal" / "fills.jsonl.gz").exists()]
    report = score(runs, tuple(s for s in args.detail.split(",") if s))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    if args.md is not None:
        args.md.write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
