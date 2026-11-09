"""Event studies on the prints: who earns as a maker, when, and two ways to use the TWAP clock.

usage: study.py PRINTS_DIR OUT_PREFIX [FEE_MAKER_BPS FEE_TAKER_BPS]

1. hours:  market-wide maker markout by clock hour (every print, weighted by $).
2. makers: the largest maker wallets: share, markouts, and their share of TWAP slices.
3. jit:    a quote posted just before each predicted TWAP slice, one tick inside the spread.
4. follow: a position taken in a TWAP's direction once it is known, closed after it stops.
All of it is causal: a TWAP is "known" from its second slice, and the next slice is predicted at
the last one + 30 s."""

import sys

import numpy as np
import pandas as pd
from twap import load, mid_at

LEAD_MS, TAIL_MS = 1500, 1500  # the JIT quote rests from 1.5 s before the predicted slice to 1.5 s after


def quote_at(M: pd.DataFrame, t: np.ndarray, col: str, before: bool = True) -> np.ndarray:
    tq = M.t_ms.to_numpy()
    i = np.searchsorted(tq, t, side="left" if before else "right") - 1
    return np.where(i < 0, np.nan, M[col].to_numpy()[np.clip(i, 0, len(M) - 1)])


def tick_of(M: pd.DataFrame) -> float:
    px = np.unique(np.concatenate([M.bid.to_numpy(), M.ask.to_numpy()]))
    d = np.diff(px)
    return float(np.round(d[d > 1e-12].min(), 10))


def slices(P: pd.DataFrame) -> pd.DataFrame:
    """One row per TWAP slice (prints of one wallet, coin, side at one time), with its TWAP id and index."""
    Z = P[P.zero]
    S = Z.groupby(["seg", "taker", "coin", "side", "t_ms"], as_index=False).agg(
        usd=("usd", "sum"), px_first=("px", "first"), px_mean=("px", "mean")
    )
    S = S.sort_values(["seg", "taker", "coin", "side", "t_ms"]).reset_index(drop=True)
    gap = S.groupby(["seg", "taker", "coin", "side"]).t_ms.diff()
    S["gap"] = gap
    S["oid"] = (gap.isna() | (gap > 150_000)).cumsum()
    S["k"] = S.groupby("oid").cumcount()
    S["prev_usd"] = S.groupby("oid").usd.shift()
    S["prev_t"] = S.groupby("oid").t_ms.shift()
    return S


def hours(P: pd.DataFrame, out: str) -> None:
    P = P.assign(hour=pd.to_datetime(P.t_ms, unit="ms", utc=True).dt.floor("h"))
    rows = []
    for (hour, flow), g in P.groupby(["hour", "flow"]):
        w = g.usd
        rows.append(
            {"hour": hour, "flow": flow, "usd_m": w.sum() / 1e6}
            | {c: float((g[c] * w).sum() / w[g[c].notna()].sum()) for c in ("spread", "mk1", "mk10", "mk60")}
        )
    T = pd.DataFrame(rows).round(3)
    T.to_csv(out + "_hours.csv", index=False)
    print(T[T.flow == "signed order"].drop(columns="flow").to_string(index=False))


def makers(P: pd.DataFrame, out: str) -> None:
    tot, tw = P.usd.sum(), P[P.zero].usd.sum()
    rows = []
    for mk, g in P.groupby("maker"):
        w = g.usd
        rows.append(
            {"maker": mk[:10], "share": w.sum() / tot, "twap_share": g[g.zero].usd.sum() / max(tw, 1), "prints": len(g)}
            | {c: float((g[c] * w).sum() / w[g[c].notna()].sum()) for c in ("spread", "mk1", "mk10", "mk60", "mk300")}
        )
    T = pd.DataFrame(rows).sort_values("share", ascending=False)
    T.to_csv(out + "_makers.csv", index=False)
    top = T.head(12)
    print(top.round(3).to_string(index=False))
    print(f"makers {len(T)}; top 5 share {T.share.head(5).sum():.2f}; top 5 share of TWAP slices {T.twap_share.head(5).sum():.2f}")
    rest = P[~P.maker.str[:10].isin(top.maker.head(5))]
    print(
        "everyone outside the top 5: "
        + " ".join(
            f"{c} {float((rest[c] * rest.usd).sum() / rest.usd[rest[c].notna()].sum()):+.2f}" for c in ("spread", "mk1", "mk10", "mk60")
        )
    )


def jit(P: pd.DataFrame, mids: dict, out: str, fee_m: float, fee_t: float) -> None:
    """For each slice of a known TWAP: our quote sits one tick inside the spread seen LEAD before the
    predicted time (or joins a one-tick spread and is skipped), for LEAD + TAIL. It fills against the
    first taker print on that side in the window at or through its price: the slice (good) or a
    signed order that came first (the exposure). Markouts are against our fill price."""
    S = slices(P)
    S = S[(S.k >= 2) & (S.prev_t.notna())]  # predictable: at least two earlier slices
    rows = []
    for (seg, coin), s in S.groupby(["seg", "coin"]):
        M = mids.get((seg, coin))
        if M is None:
            continue
        tick = tick_of(M)
        pr = P[(P.seg == seg) & (P.coin == coin)].sort_values("t_ms")
        pt, pside, ppx, pzero, ptaker = pr.t_ms.to_numpy(), pr.side.to_numpy(), pr.px.to_numpy(), pr.zero.to_numpy(), pr.taker.to_numpy()
        end = M.t_ms.max()
        for r in s.itertuples():
            t_pred = r.prev_t + 30_000
            t_on, t_off = t_pred - LEAD_MS, t_pred + TAIL_MS
            if t_off + 60_000 > end:
                continue
            bid, ask = quote_at(M, np.array([t_on]), "bid")[0], quote_at(M, np.array([t_on]), "ask")[0]
            if not np.isfinite(bid) or ask - bid < 2 * tick - 1e-12:
                rows.append({"coin": coin, "state": "one-tick spread"})
                continue
            # TWAP buys (side +1) lift asks: we offer one tick under the best ask
            px = ask - tick if r.side > 0 else bid + tick
            a, b = np.searchsorted(pt, t_on, side="left"), np.searchsorted(pt, t_off, side="right")
            hit = None
            for i in range(a, b):
                if pside[i] == r.side and (ppx[i] >= px if r.side > 0 else ppx[i] <= px):
                    hit = i
                    break
            if hit is None:
                rows.append({"coin": coin, "state": "no fill"})
                continue
            by_slice = bool(pzero[hit] and ptaker[hit] == r.taker)
            mid_pre = (bid + ask) / 2
            res = {
                "coin": coin,
                "state": "slice" if by_slice else "other taker",
                "usd": min(r.usd, 250.0) if by_slice else 250.0,
                "half_spread": r.side * (px / mid_pre - 1) * 1e4,
            }
            for h in (10, 30, 60, 300):
                m = mid_at(M, np.array([pt[hit] + h * 1000]))[0]
                res[f"mk{h}"] = -r.side * (m / px - 1) * 1e4
            # leaving by crossing the spread 30 s later: the far touch, plus the taker fee
            bid2, ask2 = (
                quote_at(M, np.array([pt[hit] + 30_000]), "bid", before=False)[0],
                quote_at(M, np.array([pt[hit] + 30_000]), "ask", before=False)[0],
            )
            res["cross30"] = -r.side * ((ask2 if r.side > 0 else bid2) / px - 1) * 1e4 - fee_t - fee_m
            rows.append(res)
    J = pd.DataFrame(rows)
    J.to_csv(out + "_jit.csv", index=False)
    print(J.state.value_counts().to_dict())
    F = J[J.state.isin(["slice", "other taker"])]
    for name, g in list(F.groupby("state")) + [("all fills", F)]:
        w = g.usd
        print(
            f"  {name:12s} n {len(g):6d} $ {w.sum():10.0f}  "
            + " ".join(
                f"{c} {float((g[c] * w).sum() / w.sum()):+6.2f}" for c in ("half_spread", "mk10", "mk30", "mk60", "mk300", "cross30")
            )
            + f"  | net of the {fee_m} bp maker fee at 30 s: {float((g.mk30 * w).sum() / w.sum()) - fee_m:+.2f}"
        )
    by = F.groupby("coin").apply(
        lambda g: pd.Series(
            {
                "fills": len(g),
                "usd": g.usd.sum(),
                "slice_share": (g.state == "slice").mean(),
                "mk30": (g.mk30 * g.usd).sum() / g.usd.sum(),
                "mk300": (g.mk300 * g.usd).sum() / g.usd.sum(),
                "net30_usd": ((g.mk30 - fee_m) * g.usd).sum() / 1e4,
            }
        ),
        include_groups=False,
    )
    print(by.sort_values("net30_usd", ascending=False).round(2).head(12).to_string())
    print(f"  total at 30 s after the maker fee: ${by.net30_usd.sum():.2f} on ${by.usd.sum():,.0f} filled")


def follow(P: pd.DataFrame, mids: dict, out: str, fee_m: float, fee_t: float) -> None:
    """Enter in the TWAP's direction 1 s after its Kth slice, at the far touch (taker). Leave 45 s after
    the last slice seen (the TWAP has stopped), or after 30 minutes, at the far touch (taker)."""
    S = slices(P)
    rows = []
    for _, s in S.groupby("oid"):
        if len(s) < 4:
            continue
        seg, coin, side = s.seg.iloc[0], s.coin.iloc[0], s.side.iloc[0]
        M = mids.get((seg, coin))
        if M is None:
            continue
        t = s.t_ms.to_numpy()
        rate = float(s.usd.iloc[:3].mean())  # $ per slice, from the first three
        t_in = t[2] + 1000
        # the stop is seen 45 s after the last slice; a gap of 95 s inside the TWAP also stops it
        gaps = np.diff(t)
        cut = np.argmax(gaps[2:] > 95_000) + 2 if (gaps[2:] > 95_000).any() else len(t) - 1
        t_out = min(t[cut] + 45_000, t_in + 1_800_000)
        if t_out + 1000 > M.t_ms.max():
            continue
        ask_in, bid_in = quote_at(M, np.array([t_in]), "ask", before=False)[0], quote_at(M, np.array([t_in]), "bid", before=False)[0]
        ask_out, bid_out = quote_at(M, np.array([t_out]), "ask", before=False)[0], quote_at(M, np.array([t_out]), "bid", before=False)[0]
        px_in, px_out = (ask_in, bid_out) if side > 0 else (bid_in, ask_out)
        gross = side * (px_out / px_in - 1) * 1e4
        mid = side * (((ask_out + bid_out) / 2) / ((ask_in + bid_in) / 2) - 1) * 1e4
        rows.append(
            {
                "seg": seg,
                "coin": coin,
                "side": side,
                "t_in": t_in,
                "minutes": (t_out - t_in) / 60000,
                "rate": rate,
                "slices": len(s),
                "mid_move": mid,
                "net_taker": gross - 2 * fee_t,
                "net_maker": mid - 2 * fee_m,
            }
        )
    F = pd.DataFrame(rows)
    F.to_csv(out + "_follow.csv", index=False)
    F["size"] = pd.cut(F.rate, [0, 100, 1000, 5000, 1e9], labels=["<$100", "$100-1k", "$1k-5k", ">$5k"])
    print("per TWAP, bp, in its direction (mean; t-stat over TWAPs; share > 0)")
    for name, g in F.groupby("size", observed=True):
        print(
            f"  slice {name:8s} n {len(g):4d} coins {g.coin.nunique():2d} min {g.minutes.median():5.1f}  "
            + "  ".join(
                f"{c} {g[c].mean():+7.2f} ({g[c].mean() / (g[c].std() / np.sqrt(len(g))):+.1f}; {(g[c] > 0).mean():.2f})"
                for c in ("mid_move", "net_taker", "net_maker")
            )
        )


def main() -> None:
    P, mids = load(sys.argv[1])
    out = sys.argv[2]
    fee_m, fee_t = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) > 4 else (0.3, 0.9)
    P["flow"] = np.where(P.zero, "TWAP slice", "signed order")
    for name, fn in (
        ("hours", lambda: hours(P, out)),
        ("makers", lambda: makers(P, out)),
        ("jit", lambda: jit(P, mids, out, fee_m, fee_t)),
        ("follow", lambda: follow(P, mids, out, fee_m, fee_t)),
    ):
        print(f"\n== {name}")
        fn()


if __name__ == "__main__":
    main()
