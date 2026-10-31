"""Maker PnL by day under quoting policies (fill-filter approximation).

    python -m marketimmune.cli.simulate_policy --coin SOL --dates 20251201..20251211
    python -m marketimmune.cli.simulate_policy --coin SOL --dates 20251201..20251231 \\
        --oof eval/q_sol_dec_l3_book.oof.parquet --policy quantile --column q10 --limit-bps 2
    python -m marketimmune.cli.simulate_policy --coin SOL --dates 20251201..20251231 \\
        --policy rule --column cex_gap_maker_bps --op le --threshold -2

Without ``--oof`` it reports S1 (quote every opportunity) over all Gold rows: the
spread a maker earns, the adverse selection it pays at 1/10/60 s, and fees and
hedge costs. With ``--oof`` it scores S1 and the policy on the rows that have a
prediction (the test days) and compares them by day. ``--policy rule`` needs no
model: it pulls the quote when one pre-trade Gold column crosses a threshold (a
stale quote by the CEX gap, forecast or realised forced flow on the quoted side)
and is scored against S1 on the rows where that column is present. See
``marketimmune.sim.pnl`` for the approximation and the accounting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from marketimmune.cli._train_data import parse_date_spec
from marketimmune.cli.build_albers_gold import PREV_DAY_SPAN_MS, _shift, load_mids
from marketimmune.cli.compare_rungs import KEY
from marketimmune.features.cex_gap import (
    CEX_FEATURE_COLUMNS,
    PriceSeries,
    cex_gap_features,
    read_binance_aggtrades_zip,
)
from marketimmune.lake.tables import HyperliquidLakeLayout
from marketimmune.sim.pnl import (
    CostModel,
    compare_policies,
    daily_policy_pnl,
    fill_components,
    policy_mask,
    summarise,
)

GOLD_COLUMNS = ("ts_ms", "px", "sz", "maker_side", "mid_before", "oid", "tid",
                "markout_bps_1s", "markout_bps_10s", "markout_bps_60s")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coin", default="SOL")
    parser.add_argument("--dates", default="20251201..20251231")
    parser.add_argument("--lake-root", type=Path, default=Path("data"))
    parser.add_argument("--horizons", default="1s,10s,60s")
    parser.add_argument("--maker-fee-bps", type=float, default=0.0)
    parser.add_argument("--hedge-cost-bps", type=float, default=0.0)
    parser.add_argument("--notional-usd", type=float, default=1_000.0)
    parser.add_argument("--oof", type=Path, default=None)
    parser.add_argument("--policy", choices=["quantile", "prob", "rule"], default="quantile")
    parser.add_argument("--op", choices=["le", "ge"], default="le",
                        help="rule: pull when the column is at or below (le) / above (ge)")
    parser.add_argument("--cex-latency-ms", type=float, default=None,
                        help="rule on a cex_* column: recompute it with this total delay "
                             "(feed + cancel) instead of Gold's 300 ms feed latency")
    parser.add_argument("--binance-dir", type=Path,
                        default=Path("data/bronze/binance/aggTrades"))
    parser.add_argument("--column", default="q10")
    parser.add_argument("--limit-bps", type=float, default=2.0)
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--out", type=Path, default=Path("eval/policy_pnl.json"))
    return parser.parse_args(argv)


def load_gold(layout: HyperliquidLakeLayout, coin: str, dates: tuple[str, ...],
              extra: tuple[str, ...] = ()) -> pd.DataFrame:
    frames = []
    for date in dates:
        path = layout.gold_training_path(coin, date)
        if not path.exists():
            continue
        names = set(pq.read_schema(path).names)
        frame = pq.read_table(path, columns=[c for c in (*GOLD_COLUMNS, *extra)
                                             if c in names]).to_pandas()
        frame["partition_date"] = date
        frames.append(frame)
    if not frames:
        raise SystemExit("no Gold training partitions for those dates")
    return pd.concat(frames, ignore_index=True)


def recompute_cex(gold: pd.DataFrame, layout: HyperliquidLakeLayout, coin: str,
                  binance_dir: Path, latency_ms: float) -> pd.DataFrame:
    """Replace the CEX-gap columns with ones read ``latency_ms`` before each fill.

    Gold's columns assume the maker sees Binance 300 ms late and can still cancel
    at the fill's time; a larger total delay asks whether the stale-quote rule
    survives a cancel that needs time to land."""
    out = gold.copy()
    symbol = f"{coin}USDT"
    for date, idx in out.groupby("partition_date").groups.items():
        zips = [binance_dir / symbol / f"{symbol}-aggTrades-{d[:4]}-{d[4:6]}-{d[6:]}.zip"
                for d in (_shift(str(date), -1), str(date))]
        if not zips[1].exists():
            out.loc[idx, list(CEX_FEATURE_COLUMNS)] = np.nan
            continue
        cex = PriceSeries.concat([read_binance_aggtrades_zip(z) for z in zips if z.exists()])
        hl_ts, hl_mid = load_mids(layout, coin, str(date), prev_tail_ms=PREV_DAY_SPAN_MS)
        rows = out.loc[idx]
        feats = cex_gap_features(rows["ts_ms"].to_numpy(np.float64),
                                 rows["maker_side"].to_numpy(np.float64), hl_ts, hl_mid, cex,
                                 latency_ms=latency_ms)
        for name, values in feats.items():
            out.loc[idx, name] = values
    return out


def attach_predictions(gold: pd.DataFrame, oof: pd.DataFrame, column: str) -> pd.DataFrame:
    """Gold rows that have a prediction, with that prediction (matched on the fill key)."""
    key = [c for c in KEY if c in gold.columns and c in oof.columns]
    g, o = gold.copy(), oof[[*key, column]].copy()
    for frame in (g, o):
        for col in key:
            frame[f"_k_{col}"] = frame[col].astype(str)
        frame["_dup"] = frame.groupby([f"_k_{c}" for c in key], sort=False).cumcount()
    joined = g.merge(o.drop(columns=key), on=[*(f"_k_{c}" for c in key), "_dup"])
    return joined.drop(columns=[c for c in joined.columns if c.startswith("_")])


def run(args: argparse.Namespace) -> dict[str, Any]:
    layout = HyperliquidLakeLayout(args.lake_root)
    rule = args.oof is None and args.policy == "rule"
    gold = load_gold(layout, args.coin.upper(), parse_date_spec(args.dates),
                     (args.column,) if rule else ())
    costs = CostModel(args.maker_fee_bps, args.hedge_cost_bps, args.notional_usd)
    spec: dict[str, Any] = {"kind": "all"}
    if rule:
        if args.cex_latency_ms is not None and args.column in CEX_FEATURE_COLUMNS:
            gold = recompute_cex(gold, layout, args.coin.upper(), args.binance_dir,
                                 args.cex_latency_ms)
        if args.column not in gold.columns:
            raise SystemExit(f"Gold has no column {args.column!r}")
        gold = gold[gold[args.column].notna()].reset_index(drop=True)
        spec = {"kind": "rule", "column": args.column, "op": args.op,
                "threshold": args.threshold, "cex_latency_ms": args.cex_latency_ms}
    elif args.oof is not None:
        gold = attach_predictions(gold, pd.read_parquet(args.oof), args.column)
        spec = ({"kind": "quantile", "column": args.column, "limit_bps": args.limit_bps}
                if args.policy == "quantile"
                else {"kind": "prob", "column": args.column, "threshold": args.threshold})
    days = gold["partition_date"].to_numpy()
    result: dict[str, Any] = {
        "coin": args.coin.upper(), "dates": args.dates, "rows": len(gold),
        "costs": {"maker_fee_bps": costs.maker_fee_bps, "hedge_cost_bps": costs.hedge_cost_bps,
                  "notional_usd": costs.notional_usd},
        "policy": spec, "approximation": "fill filter (queue position ignored)",
    }
    for h in [x.strip() for x in args.horizons.split(",") if x.strip()]:
        if f"markout_bps_{h}" not in gold.columns:
            continue
        valid = gold[f"markout_bps_{h}"].notna() & gold["mid_before"].notna()
        comps = fill_components(gold.loc[valid], h, costs)
        s1 = daily_policy_pnl(comps, days[valid.to_numpy()], [True] * len(comps), costs)
        entry: dict[str, Any] = {"S1_quote_all": summarise(s1),
                                 "S1_daily": s1.to_dict(orient="records")}
        if spec["kind"] != "all":
            take = policy_mask(gold.loc[valid], spec)
            pol = daily_policy_pnl(comps, days[valid.to_numpy()], take, costs)
            entry["policy"] = summarise(pol)
            entry["policy_quote_rate"] = float(take.mean()) if len(take) else None
            entry["policy_vs_S1"] = compare_policies(s1, pol)
        result[h] = entry
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    for h in ("1s", "10s", "60s"):
        if h in result:
            s = result[h]["S1_quote_all"]
            line = (f"{h}: S1 fills={s['fills']:,} spread={s['spread_bps']:+.2f} "
                    f"adverse={s['adverse_bps']:+.2f} total={s['total_bps']:+.2f} bps/$")
            if "policy" in result[h]:
                p, c = result[h]["policy"], result[h]["policy_vs_S1"]
                line += (f" | policy quote_rate={result[h]['policy_quote_rate']:.2f} "
                         f"total={p.get('total_bps', float('nan')):+.2f} "
                         f"vs S1 mean/day=${c['mean_daily_usd']:+,.0f}")
            print(line)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
