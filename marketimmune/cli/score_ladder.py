"""Score the pre-registered ladder hypotheses H1-H5 from ``compare_rungs`` and ``mcs_rungs`` reports.

    python -m marketimmune.cli.score_ladder --runs eval/sol_dec_registered,eval/sol_dec_corrected

Rules (docs/preregistration/sol-dec-2025-ladder.md). Per metric (Brier; pinball at tau 0.1),
H1-H4 need the stated sign, a Diebold-Mariano p below 0.05 after Holm across H1-H4, and a
bootstrap 95% interval above zero. H3 also needs the placebo vs L2 to be insignificant (raw
p > 0.10) in every regime. H5 needs L0 and L1 outside the model confidence set. A hypothesis
holds in a run when it holds on both metrics, and is claimed only when it holds in every run
given (Deviations, 2026-10-31).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from marketimmune.utils import split_csv

# metric -> (report prefix, MCS report)
METRICS = {"brier": ("", "mcs_brier.json"), "pinball_q10": ("q_", "mcs_pinball_q10.json")}
# hypothesis -> (challenger, base, regimes that can support it)
TESTS = {
    "H1": ("l1", "l0", ("all",)),
    "H2": ("l2", "l1", ("all",)),
    "H3": ("l3a", "l2", ("cex_move",)),
    "H4": ("l3b", "l2", ("forced_60s", "all")),
}
ALPHA = 0.05
PLACEBO_ALPHA = 0.10


def holm(p: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values."""
    out: dict[str, float] = {}
    running = 0.0
    for k, (name, value) in enumerate(sorted(p.items(), key=lambda item: item[1])):
        running = max(running, min(1.0, (len(p) - k) * value))
        out[name] = running
    return out


def _compare(run: Path, prefix: str, name: str, challenger: str, base: str) -> dict[str, Any]:
    path = run / f"{prefix}{name}_{challenger}_book_vs_{prefix}{name}_{base}_book.json"
    report: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return report


def _test(regime: dict[str, Any]) -> dict[str, Any]:
    dm = regime["diebold_mariano"]
    assert dm is not None, f"no DM test: {regime['days']=}"
    return {
        "improvement": regime["mean_daily_improvement"],
        "days": regime["days"],
        "days_improved": regime["days_improved"],
        "t": dm["t_stat"],
        "p": dm["p_value"],
        "ci": regime["bootstrap_ci_95"],
    }


def score_metric(run: Path, metric: str, name: str) -> dict[str, dict[str, Any]]:
    prefix, mcs_report = METRICS[metric]
    rows: dict[str, dict[str, Any]] = {}
    for h, (challenger, base, regimes) in TESTS.items():
        report = _compare(run, prefix, name, challenger, base)
        routes = {r: _test(report[r]) for r in regimes}
        # NOTE: H4 has two registered routes (forced_60s or overall). The one with the smaller p
        # enters Holm with that p multiplied by the number of routes, so H4 gets no extra chance.
        best = min(regimes, key=lambda r: routes[r]["p"])
        rows[h] = {"regime": best, **routes[best], "p_family": min(1.0, len(regimes) * routes[best]["p"]), "routes": routes}
    for h, p_holm in holm({h: row["p_family"] for h, row in rows.items()}).items():
        row = rows[h]
        row["p_holm"] = p_holm
        row["supported"] = row["improvement"] > 0 and row["ci"][0] > 0 and p_holm < ALPHA
    placebo = _compare(run, prefix, name, "l3a_placebo", "l2")
    placebo_p = {k: v["diebold_mariano"]["p_value"] for k, v in placebo.items() if isinstance(v, dict) and v.get("diebold_mariano")}
    rows["H3"]["placebo_p"] = placebo_p
    rows["H3"]["supported"] = rows["H3"]["supported"] and min(placebo_p.values()) > PLACEBO_ALPHA
    mcs = json.loads((run / mcs_report).read_text(encoding="utf-8"))
    included = [m.removeprefix(f"{prefix}{name}_").removesuffix("_book") for m in mcs["included"]]
    rows["H5"] = {"mcs": included, "days": mcs["days"], "supported": "l0" not in included and "l1" not in included}
    return rows


def score(runs: list[Path], name: str) -> dict[str, Any]:
    per_run = {str(run): {metric: score_metric(run, metric, name) for metric in METRICS} for run in runs}
    verdicts = {}
    for h in (*TESTS, "H5"):
        held = {run: all(metrics[m][h]["supported"] for m in METRICS) for run, metrics in per_run.items()}
        verdicts[h] = {"per_run": held, "claimed": all(held.values())}
    return {"runs": per_run, "verdicts": verdicts}


def _line(h: str, row: dict[str, Any]) -> str:
    if h == "H5":
        return f"MCS {{{', '.join(row['mcs'])}}} over {row['days']} days"
    lo, hi = row["ci"]
    line = (
        f"{row['regime']}: {row['improvement']:+.4f}/day, {row['days_improved']}/{row['days']} days, t {row['t']:.1f}, "
        f"p {row['p']:.3g} (Holm {row['p_holm']:.3g}), CI [{lo:.4f}, {hi:.4f}]"
    )
    if "placebo_p" in row:
        line += f"; placebo min p {min(row['placebo_p'].values()):.3g}"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", required=True, help="comma-separated eval directories")
    parser.add_argument("--name", default="sol_dec", help="report name between the q_ prefix and the rung")
    parser.add_argument("--out", type=Path, default=Path("eval/ladder_verdicts.json"))
    args = parser.parse_args(argv)
    result = score([Path(run) for run in split_csv(args.runs)], args.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for h, verdict in result["verdicts"].items():
        print(f"{h}: {'CLAIMED' if verdict['claimed'] else 'not claimed'}")
        for run, metrics in result["runs"].items():
            for metric, rows in metrics.items():
                print(f"  {Path(run).name} {metric}: {'yes' if rows[h]['supported'] else 'no '} {_line(h, rows[h])}")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
