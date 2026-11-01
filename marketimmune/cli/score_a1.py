"""Score the pre-registered A1 hypotheses (priority fees, 2026) from ``compare_rungs`` reports.

    python -m marketimmune.cli.score_a1 --dir eval/a1/confirmation --coins BTC,ETH,SOL --out eval/a1/a1_verdicts.json

Rules: ``docs/preregistration/a1-speed-bids-2026.md``. Per metric (Brier; pinball at tau 0.1),
each of A1-A4 for each coin needs:

- the stated sign;
- a Diebold-Mariano p below 0.05 after Holm across the 12 tests (4 hypotheses x 3 coins);
- a bootstrap 95% interval above zero.

A1 and A2 also need the placebo (``l3_fee_placebo`` vs ``l2_trade``) to be insignificant (raw
p > 0.10) in every regime. A hypothesis holds for a coin when it holds on both metrics.

Claims:

- **Fees** if A2 holds in at least two coins and its point estimate is not negative in the
  third, on either metric.
- **The plan's gate** if A1 holds in at least two coins.

Reports are read as ``<dir>/<prefix>a1_<coin>_<challenger>_vs_<prefix>a1_<coin>_<base>.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from marketimmune.cli.score_ladder import ALPHA, METRICS, PLACEBO_ALPHA, _test, holm
from marketimmune.utils import parse_symbol_spec

TESTS = {
    "A1": ("l3_fee", "l2_trade", "cex_move"),
    "A2": ("l3_fee", "l2_trade", "all"),
    "A3": ("l1_trade", "l0_trade", "all"),
    "A4": ("l2_trade", "l1_trade", "all"),
}
PLACEBO = ("l3_fee_placebo", "l2_trade")
NEEDS_PLACEBO = ("A1", "A2")


def report_name(prefix: str, coin: str, challenger: str, base: str) -> str:
    name = f"a1_{coin.lower()}"
    return f"{prefix}{name}_{challenger}_vs_{prefix}{name}_{base}.json"


def _read(directory: Path, prefix: str, coin: str, challenger: str, base: str) -> dict[str, Any]:
    out: dict[str, Any] = json.loads((directory / report_name(prefix, coin, challenger, base)).read_text(encoding="utf-8"))
    return out


def score_metric(directory: Path, metric: str, coins: tuple[str, ...]) -> dict[str, dict[str, dict[str, Any]]]:
    prefix = METRICS[metric][0]
    rows: dict[str, dict[str, dict[str, Any]]] = {c: {} for c in coins}
    p: dict[str, float] = {}
    for coin in coins:
        placebo = _read(directory, prefix, coin, *PLACEBO)
        placebo_p = {k: v["diebold_mariano"]["p_value"] for k, v in placebo.items() if isinstance(v, dict) and v.get("diebold_mariano")}
        for h, (challenger, base, regime) in TESTS.items():
            row = {"regime": regime, **_test(_read(directory, prefix, coin, challenger, base)[regime])}
            if h in NEEDS_PLACEBO:
                row["placebo_p"] = placebo_p
            rows[coin][h] = row
            p[f"{coin}/{h}"] = row["p"]
    for key, p_holm in holm(p).items():
        coin, h = key.split("/")
        row = rows[coin][h]
        row["p_holm"] = p_holm
        ok = row["improvement"] > 0 and row["ci"][0] > 0 and p_holm < ALPHA
        if h in NEEDS_PLACEBO:
            ok = ok and min(row["placebo_p"].values()) > PLACEBO_ALPHA
        row["supported"] = ok
    return rows


def score(directory: Path, coins: tuple[str, ...]) -> dict[str, Any]:
    metrics = {m: score_metric(directory, m, coins) for m in METRICS}
    held = {h: {c: all(metrics[m][c][h]["supported"] for m in METRICS) for c in coins} for h in TESTS}
    a2_holds = [c for c in coins if held["A2"][c]]
    others = [c for c in coins if c not in a2_holds]
    fees = len(a2_holds) >= 2 and all(metrics[m][c]["A2"]["improvement"] >= 0 for m in METRICS for c in others)
    return {
        "dir": str(directory),
        "metrics": metrics,
        "held": held,
        "claims": {
            "fees_beyond_cex_gap_and_wallet": fees,
            "gate_a1_passes": sum(held["A1"].values()) >= 2,
            "replication_a3_coins": sum(held["A3"].values()),
            "replication_a4_coins": sum(held["A4"].values()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--out", type=Path, default=Path("eval/a1/a1_verdicts.json"))
    args = parser.parse_args(argv)
    result = score(args.dir, parse_symbol_spec(args.coins))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for h in TESTS:
        print(f"{h}: held in {[c for c, ok in result['held'][h].items() if ok]}")
        for metric, coins in result["metrics"].items():
            for coin, rows in coins.items():
                r = rows[h]
                lo, hi = r["ci"]
                extra = f"; placebo min p {min(r['placebo_p'].values()):.3g}" if "placebo_p" in r else ""
                print(
                    f"  {coin} {metric}: {'yes' if r['supported'] else 'no '} {r['regime']}: {r['improvement']:+.5f}/day, "
                    f"{r['days_improved']}/{r['days']} days, p {r['p']:.3g} (Holm {r['p_holm']:.3g}), CI [{lo:.5f}, {hi:.5f}]{extra}"
                )
    print(json.dumps(result["claims"]))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
