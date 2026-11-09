"""$ an hour by strategy in clock windows across replayed segments, and without some markets.

usage: windows.py OUT.csv CUT_UTC_HHMM EXCLUDE_COINS SEG_DIR [SEG_DIR ...]

Each segment's equity.jsonl starts at zero; PnL in a window is the change in summed equity over the
part of the window inside the segment. CUT_UTC_HHMM splits each UTC day (e.g. 1430 for the US open).
EXCLUDE_COINS is a comma list dropped for the "without" column (or "-")."""

import sys

import pandas as pd


def main() -> None:
    out, cut, excl, segs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    excl = set() if excl == "-" else set(excl.split(","))
    h, m = int(cut[:2]), int(cut[2:])
    rows = []
    for seg in segs:
        E = pd.read_json(seg + "/equity.jsonl", lines=True)
        t = pd.to_datetime(E.t_ms, unit="ms", utc=True)
        E["after"] = (t.dt.hour * 60 + t.dt.minute) >= h * 60 + m
        for (s, c), g in E.groupby(["strategy", "coin"]):
            g = g.sort_values("t_ms")
            eq = g.equity.to_numpy()
            dt = g.t_ms.diff().fillna(0).to_numpy() / 3.6e6
            d_eq = pd.Series(eq).diff().fillna(eq[0]).to_numpy()
            for part in (False, True):
                mask = (g.after == part).to_numpy()
                rows.append({"segment": seg, "strategy": s, "coin": c, "after_cut": part, "usd": d_eq[mask].sum(), "hours": dt[mask].sum()})
    R = pd.DataFrame(rows)
    R.to_csv(out, index=False)
    hours = R.groupby(["strategy", "coin", "after_cut"]).hours.sum().groupby(["strategy", "after_cut"]).max()
    usd = R.groupby(["strategy", "after_cut"]).usd.sum()
    usd_wo = R[~R.coin.isin(excl)].groupby(["strategy", "after_cut"]).usd.sum()
    T = pd.DataFrame({"hours": hours, "usd_per_hour": usd / hours, "usd_per_hour_without": usd_wo / hours}).round(2)
    allh = R.groupby(["strategy", "coin"]).hours.sum().groupby("strategy").max()
    T2 = pd.DataFrame(
        {
            "hours": allh,
            "usd_per_hour": R.groupby("strategy").usd.sum() / allh,
            "usd_per_hour_without": R[~R.coin.isin(excl)].groupby("strategy").usd.sum() / allh,
        }
    ).round(2)
    print(T.to_string())
    print(T2.to_string())


if __name__ == "__main__":
    main()
