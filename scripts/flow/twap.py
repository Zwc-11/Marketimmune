"""Clock-driven flow on Hyperliquid: TWAP child orders in the public trade prints.

usage: twap.py PRINTS_DIR OUT_PREFIX

Reads the *.prints.parquet / *.mids.parquet pairs written by prints.py. A print whose hash is all zeros
is a TWAP slice (checked by the 30 s spacing of same-wallet prints). Writes:
- OUT_PREFIX_markouts.csv: the maker's markout against the fill price (bp, + is good for the maker),
  by flow class (TWAP slice or signed order), coin and horizon, weighted by $;
- OUT_PREFIX_orders.csv: one row per TWAP (wallet, coin, side, a new one after 150 s of silence);
- OUT_PREFIX_drift.csv: the mid's move in the TWAP's direction while it runs and after it ends;
- OUT_PREFIX_signal.csv: on a 30 s grid, the net $ of TWAP slices expected in the next 30 s (from
  TWAPs with at least 2 slices seen, causal) against the mid's next move.
Prints the main tables."""

import glob
import sys

import numpy as np
import pandas as pd

H = [1, 10, 30, 60, 300, 900]


def mid_at(M: pd.DataFrame, t: np.ndarray, before: bool = False) -> np.ndarray:
    """Mid from the last quote at or before t (strictly before if `before`)."""
    tq = M.t_ms.to_numpy()
    mid = ((M.bid + M.ask) / 2).to_numpy()
    i = np.searchsorted(tq, t, side="left" if before else "right") - 1
    out = mid[np.clip(i, 0, len(mid) - 1)]
    return np.where(i < 0, np.nan, out)


def load(d: str) -> tuple[pd.DataFrame, dict[tuple[str, str], pd.DataFrame]]:
    parts, mids = [], {}
    for f in sorted(glob.glob(d + "/*.prints.parquet")):
        seg = f.split("/")[-1].split(".")[0]
        P = pd.read_parquet(f)
        M = pd.read_parquet(f.replace(".prints.", ".mids."))
        end = M.t_ms.max()
        for coin, m in M.groupby("coin"):
            mids[(seg, coin)] = m.reset_index(drop=True)
        cols = {f"m{h}": np.full(len(P), np.nan) for h in H} | {"pre": np.full(len(P), np.nan)}
        for coin, idx in P.groupby("coin").indices.items():
            m = mids.get((seg, coin))
            if m is None:
                continue
            t = P.t_ms.to_numpy()[idx]
            cols["pre"][idx] = mid_at(m, t, before=True)
            for h in H:
                v = mid_at(m, t + h * 1000)
                v[t + h * 1000 > end] = np.nan  # no look past the recording's end
                cols[f"m{h}"][idx] = v
        parts.append(P.assign(seg=seg, **cols))
    P = pd.concat(parts, ignore_index=True)
    P["usd"] = P.px * P.sz
    for h in H:
        P[f"mk{h}"] = -P.side * (P[f"m{h}"] / P.px - 1) * 1e4
    P["spread"] = P.side * (P.px / P.pre - 1) * 1e4
    return P, mids


def wmean(g: pd.DataFrame, col: str) -> float:
    ok = g[col].notna()
    return float((g.loc[ok, col] * g.loc[ok, "usd"]).sum() / g.loc[ok, "usd"].sum()) if ok.any() else np.nan


def main() -> None:
    P, mids = load(sys.argv[1])
    out = sys.argv[2]
    P["flow"] = np.where(P.zero, "TWAP slice", "signed order")

    rows = []
    for (flow, coin), g in list(P.groupby(["flow", "coin"])) + [((f, "ALL"), g) for f, g in P.groupby("flow")]:
        rows.append(
            {"flow": flow, "coin": coin, "prints": len(g), "usd_m": g.usd.sum() / 1e6, "spread": wmean(g, "spread")}
            | {f"mk{h}": wmean(g, f"mk{h}") for h in H}
        )
    T = pd.DataFrame(rows).round(3)
    T.to_csv(out + "_markouts.csv", index=False)
    print(T[T.coin == "ALL"].to_string(index=False))
    print(T[T.coin != "ALL"].pivot(index="coin", columns="flow", values=["usd_m", "mk1", "mk60", "mk300"]).round(2).to_string())

    # TWAP orders: same wallet, coin, side; a new one after 150 s of silence
    Z = P[P.zero].sort_values("t_ms")
    S = Z.groupby(["seg", "taker", "coin", "side", "t_ms"], as_index=False).agg(usd=("usd", "sum"), px=("px", "mean"), pre=("pre", "first"))
    S = S.sort_values(["seg", "taker", "coin", "side", "t_ms"])
    gap = S.groupby(["seg", "taker", "coin", "side"]).t_ms.diff()
    S["gap_s"] = gap / 1000
    S["oid"] = ((gap.isna()) | (gap > 150_000)).cumsum()
    S["k"] = S.groupby("oid").cumcount()
    orders = (
        S.groupby("oid")
        .agg(
            seg=("seg", "first"),
            taker=("taker", "first"),
            coin=("coin", "first"),
            side=("side", "first"),
            t0=("t_ms", "min"),
            t1=("t_ms", "max"),
            slices=("usd", "size"),
            usd=("usd", "sum"),
            slice_usd=("usd", "median"),
            pre0=("pre", "first"),
        )
        .reset_index()
    )
    orders["minutes"] = (orders.t1 - orders.t0) / 60000
    orders.to_csv(out + "_orders.csv", index=False)
    g = S.gap_s.dropna()
    g = g[(g > 20) & (g < 40)]
    print(
        f"\nTWAPs {len(orders)} wallets {orders.taker.nunique()} with >=3 slices {int((orders.slices >= 3).sum())}; slice gap near 30 s: mean {g.mean():.2f} sd {g.std():.2f} within +-1 s {((g - 30).abs() <= 1).mean():.3f}"
    )
    print(
        orders[orders.slices >= 3]
        .groupby("coin")
        .agg(
            twaps=("usd", "size"),
            usd_m=("usd", lambda x: x.sum() / 1e6),
            median_usd=("usd", "median"),
            median_min=("minutes", "median"),
            median_slice=("slice_usd", "median"),
            max_usd_m=("usd", lambda x: x.max() / 1e6),
        )
        .round(2)
        .to_string()
    )

    # drift while a TWAP runs, and after it ends (in the TWAP's direction, bp)
    rows = []
    for o in orders[orders.slices >= 6].itertuples():
        m = mids.get((o.seg, o.coin))
        if m is None or o.t1 + 900_000 > m.t_ms.max():
            continue
        a, b = mid_at(m, np.array([o.t0]), before=True)[0], mid_at(m, np.array([o.t1 + 1000]))[0]
        after = {f"after{h}": o.side * (mid_at(m, np.array([o.t1 + h * 1000]))[0] / b - 1) * 1e4 for h in (60, 300, 900)}
        rows.append({"coin": o.coin, "usd": o.usd, "minutes": o.minutes, "slices": o.slices, "during": o.side * (b / a - 1) * 1e4} | after)
    D = pd.DataFrame(rows)
    D.to_csv(out + "_drift.csv", index=False)
    D["size"] = pd.cut(D.usd, [0, 1e4, 1e5, 1e6, 1e9], labels=["<$10k", "$10k-100k", "$100k-1M", ">$1M"])
    print("\ndrift in the TWAP's direction, bp (mean; t-stat)")
    for name, g in D.groupby("size", observed=True):
        print(
            f"  {name:10s} n {len(g):5d}  "
            + "  ".join(
                f"{c} {g[c].mean():+6.2f} ({g[c].mean() / (g[c].std() / np.sqrt(len(g))):+.1f})"
                for c in ["during", "after60", "after300", "after900"]
            )
        )

    # causal signal: net $ of slices expected in the next 30 s, per coin, on a 30 s grid
    rows = []
    for (seg, coin), m in mids.items():
        s = S[(S.seg == seg) & (S.coin == coin) & (S.k >= 1)]  # a TWAP is known from its second slice
        if s.empty:
            continue
        t0, t1 = m.t_ms.min(), m.t_ms.max()
        grid = np.arange(t0 + 60_000, t1 - 900_000, 30_000)
        ts, v = s.t_ms.to_numpy(), (s.side * s.usd).to_numpy()
        order = np.argsort(ts)
        ts, c = ts[order], np.cumsum(v[order])
        # slices seen in the last 30 s stand in for the next 30 s
        hi, lo = np.searchsorted(ts, grid, side="right"), np.searchsorted(ts, grid - 30_000, side="right")
        net = np.where(hi > 0, c[np.clip(hi - 1, 0, None)], 0.0) - np.where(lo > 0, c[np.clip(lo - 1, 0, None)], 0.0)
        now = mid_at(m, grid)
        f = {f"r{h}": (mid_at(m, grid + h * 1000) / now - 1) * 1e4 for h in (30, 60, 300, 900)}
        rows.append(pd.DataFrame({"seg": seg, "coin": coin, "t_ms": grid, "net": net} | f))
    G = pd.concat(rows, ignore_index=True)
    G.to_csv(out + "_signal.csv", index=False)
    print("\nnet TWAP $ in the last 30 s -> the mid's next move in that direction, bp (mean; t-stat; n)")
    A = G[G.net != 0].copy()
    A["size"] = pd.cut(A.net.abs(), [0, 1e3, 1e4, 5e4, 2e5, 1e9], labels=["<$1k", "$1k-10k", "$10k-50k", "$50k-200k", ">$200k"])
    sgn = np.sign(A.net)
    for name, g in A.groupby("size", observed=True):
        s = sgn.loc[g.index]
        print(
            f"  {name:10s} n {len(g):6d}  "
            + "  ".join(
                f"{h}s {(s * g[f'r{h}']).mean():+6.2f} ({(s * g[f'r{h}']).mean() / ((s * g[f'r{h}']).std() / np.sqrt(len(g))):+.1f})"
                for h in (30, 60, 300, 900)
            )
        )


if __name__ == "__main__":
    main()
