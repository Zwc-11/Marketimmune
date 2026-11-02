"""Render the A1 results (``scripts/run_a1.ps1`` outputs) as Markdown tables.

    python -m marketimmune.cli.a1_report --dir eval/a1 --out eval/a1/a1_tables.md

Reads, under ``--dir``:

- ``a1_verdicts.json`` (confirmation, ``score_a1``) and ``a1_discovery_exploratory.json``;
- ``<period>/<prefix>a1_<coin>_<challenger>_vs_<prefix>a1_<coin>_<base>.json``
  (``compare_rungs``) for every regime of the fee rung and its placebo;
- ``<period>/mcs_brier_a1_<coin>.json`` and ``mcs_pinball_q10_a1_<coin>.json`` (``mcs_rungs``);
- ``<prefix>a1_<coin>_<rung>.json`` (``a1_ladder`` summaries: tested days, rows, leakage).

Numbers are copied, not recomputed: brier in units of 1e-3 per day, pinball in bps per day.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from marketimmune.cli.score_a1 import PLACEBO, TESTS, report_name
from marketimmune.cli.score_ladder import METRICS
from marketimmune.utils import parse_symbol_spec

RUNGS = ("l0_trade", "l1_trade", "l2_trade", "l3_fee", "l3_fee_placebo")
SCALE = {"brier": 1e3, "pinball_q10": 1.0}
UNIT = {"brier": "Brier ×1e-3", "pinball_q10": "pinball τ=0.1, bps"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("eval/a1"))
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _p(x: float) -> str:
    return f"{x:.2g}" if x >= 1e-4 else "<1e-4"


def _cell(row: dict[str, Any], metric: str) -> str:
    s = SCALE[metric]
    lo, hi = row["ci"]
    text = f"{row['improvement'] * s:+.3f} [{lo * s:+.3f}, {hi * s:+.3f}], {row['days_improved']}/{row['days']}, p {_p(row['p'])}"
    if "p_holm" in row:
        text += f" (Holm {_p(row['p_holm'])})"
    if "placebo_p" in row:
        text += f", placebo min p {_p(min(row['placebo_p'].values()))}"
    return f"**{text}**" if row.get("supported") else text


def verdict_tables(verdicts: dict[str, Any], coins: tuple[str, ...], title: str) -> list[str]:
    out = [f"### {title}", ""]
    claims = verdicts["claims"]
    out += [f"- `{k}`: {v}" for k, v in claims.items()]
    out += ["", "| Test | Coin | Held | " + " | ".join(UNIT[m] for m in METRICS) + " |", "|---|---|---|" + "---|" * len(METRICS)]
    for h, (c, b, regime) in TESTS.items():
        for coin in coins:
            cells = [_cell(verdicts["metrics"][m][coin][h], m) for m in METRICS]
            held = "yes" if verdicts["held"][h][coin] else "no"
            out.append(f"| {h}: `{c}` vs `{b}`, {regime} | {coin} | {held} | " + " | ".join(cells) + " |")
    out += ["", "Cells: mean daily improvement [bootstrap 95%], days improved / days, DM p. Bold: the cell meets the rule.", ""]
    return out


def regime_table(directory: Path, coins: tuple[str, ...], pair: tuple[str, str], title: str) -> list[str]:
    out = [f"### {title}", "", "| Coin | Metric | Regime | Improvement [95%] | Days improved | DM p |", "|---|---|---|---|---|---|"]
    for coin in coins:
        for metric, (prefix, _mcs) in METRICS.items():
            rep = _load(directory / report_name(prefix, coin, *pair))
            if rep is None:
                continue
            s = SCALE[metric]
            for regime, r in rep.items():
                if not isinstance(r, dict) or "mean_daily_improvement" not in r or not r.get("diebold_mariano"):
                    continue
                lo, hi = r["bootstrap_ci_95"]
                out.append(
                    f"| {coin} | {metric} | {regime} | {r['mean_daily_improvement'] * s:+.3f} [{lo * s:+.3f}, {hi * s:+.3f}] | "
                    f"{r['days_improved']}/{r['days']} | {_p(r['diebold_mariano']['p_value'])} |"
                )
    return [*out, ""]


def mcs_table(directory: Path, coins: tuple[str, ...]) -> list[str]:
    out = ["| Coin | Metric | In the set (p) | Out (p) |", "|---|---|---|---|"]
    for coin in coins:
        for metric in METRICS:
            rep = _load(directory / f"mcs_{'brier' if metric == 'brier' else 'pinball_q10'}_a1_{coin.lower()}.json")
            if rep is None:
                continue
            ins = [f"`{m['name'].split(f'a1_{coin.lower()}_')[-1]}` ({m['mcs_p_value']:.2f})" for m in rep["models"] if m["in_mcs"]]
            outs = [f"`{m['name'].split(f'a1_{coin.lower()}_')[-1]}` ({m['mcs_p_value']:.2f})" for m in rep["models"] if not m["in_mcs"]]
            out.append(f"| {coin} | {metric} | {', '.join(ins)} | {', '.join(outs) or '-'} |")
    return [*out, ""]


def data_table(directory: Path, coins: tuple[str, ...]) -> list[str]:
    out = ["| Coin | Model | Rung | Tested days | Rows tested | Leakage-safe |", "|---|---|---|---|---|---|"]
    for coin in coins:
        for model, prefix in (("classifier", ""), ("quantile", "q_")):
            for rung in RUNGS:
                s = _load(directory / f"{prefix}a1_{coin.lower()}_{rung}.json")
                if s is not None:
                    out.append(f"| {coin} | {model} | `{rung}` | {s['tested_days']} | {s['rows_tested']:,} | {s['leakage_safe']} |")
    return [*out, ""]


SECONDARY_LOSSES = (
    ("log", "", "log loss ×1e-3", 1e3),
    ("pinball50", "q_", "pinball τ=0.5, bps", 1.0),
    ("pinball90", "q_", "pinball τ=0.9, bps", 1.0),
)
PAIRS = (("l1_trade", "l0_trade"), ("l2_trade", "l1_trade"), ("l3_fee", "l2_trade"), PLACEBO)


def secondary_table(directory: Path, coins: tuple[str, ...]) -> list[str]:
    head = "| Coin | Comparison | Regime | " + " | ".join(label for _n, _p, label, _s in SECONDARY_LOSSES) + " |"
    out = [head, "|---|---|---|" + "---|" * len(SECONDARY_LOSSES)]
    found = False
    for coin in coins:
        for c, b in PAIRS:
            for regime in ("all", "cex_move") if (c, b) == ("l3_fee", "l2_trade") else ("all",):
                cells = []
                for name, prefix, _label, scale in SECONDARY_LOSSES:
                    rep = _load(directory / f"{report_name(prefix, coin, c, b).removesuffix('.json')}.{name}.json")
                    r = rep.get(regime) if rep else None
                    if not r or not r.get("diebold_mariano"):
                        cells.append("-")
                        continue
                    found = True
                    lo, hi = r["bootstrap_ci_95"]
                    cells.append(
                        f"{r['mean_daily_improvement'] * scale:+.3f} [{lo * scale:+.3f}, {hi * scale:+.3f}], "
                        f"{r['days_improved']}/{r['days']}, p {_p(r['diebold_mariano']['p_value'])}"
                    )
                out.append(f"| {coin} | `{c}` vs `{b}` | {regime} | " + " | ".join(cells) + " |")
    return [*out, ""] if found else ["(not run yet: `scripts/run_a1_secondary.ps1`)", ""]


def lead_time_table(path: Path) -> list[str]:
    rep = _load(path)
    if rep is None:
        return ["(not run yet: `python -m marketimmune.cli.a1_lead_time`)", ""]
    labels = rep["buckets_blocks"]
    out = ["| Coin | Period | ms per block | " + " | ".join(labels) + " |", "|---|---|---|" + "---|" * len(labels)]
    for coin, periods in rep["coins"].items():
        for period, x in periods.items():
            cells = [f"{x[b]['markout_bps_1s']:+.2f} ({x[b]['share']:.1%})" if x[b]["markout_bps_1s"] is not None else "-" for b in labels]
            out.append(f"| {coin} | {period} | {x['ms_per_block_median']:.0f} | " + " | ".join(cells) + " |")
    return [
        *out,
        "",
        "Cells: mean of daily mean 1 s markout from the pre-fill mid, bps (share of fills); columns: blocks since a fee-paying taker hit the same side.",
        "",
    ]


def render(directory: Path, coins: tuple[str, ...]) -> str:
    lines = ["# A1 results tables (generated by `cli.a1_report`)", ""]
    conf = _load(directory / "a1_verdicts.json")
    disc = _load(directory / "a1_discovery_exploratory.json")
    lines += ["## Confirmation (Sep 1 - Oct 31, the pre-registered test)", ""]
    lines += verdict_tables(conf, coins, "Verdicts") if conf else ["(no `a1_verdicts.json` yet)", ""]
    lines += regime_table(directory / "confirmation", coins, ("l3_fee", "l2_trade"), "Fee rung against `l2_trade`, every regime")
    lines += regime_table(directory / "confirmation", coins, PLACEBO, "Placebo (opposite-side fees) against `l2_trade`, every regime")
    lines += ["### Model confidence set (α = 0.10)", "", *mcs_table(directory / "confirmation", coins)]
    lines += ["## Discovery (Wednesdays May 6 - Aug 26; exploratory)", ""]
    lines += verdict_tables(disc, coins, "Same rules, not a test") if disc else ["(no discovery scoring yet)", ""]
    lines += ["### Model confidence set (α = 0.10)", "", *mcs_table(directory / "discovery", coins)]
    lines += ["## Secondary (pre-registered as secondary; confirmation months)", ""]
    lines += ["### Other losses on the 10 s runs", "", *secondary_table(directory / "secondary", coins)]
    lines += ["### Lead time (plan A.5 test 4)", "", *lead_time_table(directory / "lead_time.json")]
    for h in ("1s", "60s"):
        scored = _load(directory / f"h{h}" / "a1_secondary_scored.json")
        if scored:
            lines += verdict_tables(scored, coins, f"{h} horizon, the same rules (secondary)")
    lines += ["## Runs", "", *data_table(directory, coins)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = render(args.dir, parse_symbol_spec(args.coins))
    if args.out is None:
        print(text)
    else:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
