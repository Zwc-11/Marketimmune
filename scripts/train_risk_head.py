"""Train the gradient-boosting risk head and produce a benchmark report.

Usage:
    python scripts/train_risk_head.py
        [--samples-per-scenario 800]
        [--seed 42]
        [--out data/models/risk_head.joblib]
        [--report reports/risk_head_benchmark.json]

Idempotent and side-effect-free except for the two written artifacts.
A second invocation with the same seed produces byte-identical outputs.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from marketimmune.models import RiskScorer, build_dataset


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-scenario", type=int, default=800)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-std", type=float, default=0.55)
    parser.add_argument("--contamination", type=float, default=0.18)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/models/risk_head.joblib"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/risk_head_benchmark.json"),
    )
    parser.add_argument(
        "--latency-samples",
        type=int,
        default=1000,
        help="Number of single-row predictions used to measure latency.",
    )
    parser.add_argument(
        "--holdout-scenarios",
        nargs="*",
        default=["momentum_ignition", "twap_execution"],
        help=(
            "Scenarios to hold out for the honest family-aware split. "
            "Pass an empty list to skip the held-out evaluation."
        ),
    )
    return parser.parse_args()


def measure_latency(scorer: RiskScorer, n: int = 1000) -> dict[str, float]:
    """Return p50 / p95 / p99 single-prediction latency in milliseconds."""
    rng = np.random.default_rng(0)
    times: list[float] = []
    sample = {name: float(rng.random() * 5) for name in scorer.feature_order}
    for _ in range(n):
        start = time.perf_counter()
        scorer.predict(sample)
        times.append((time.perf_counter() - start) * 1000.0)
    arr = np.asarray(times)
    return {
        "p50_ms": float(np.percentile(arr, 50)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "mean_ms": float(arr.mean()),
        "samples": int(n),
    }


def main() -> None:
    args = _parse_args()
    print(
        "Building synthetic labelled dataset "
        f"(samples_per_scenario={args.samples_per_scenario}, seed={args.seed})..."
    )
    X, y, names = build_dataset(
        n_per_scenario=args.samples_per_scenario,
        noise_std=args.noise_std,
        contamination=args.contamination,
        seed=args.seed,
    )
    print(f"  -> X shape {X.shape}, hostile fraction {y.mean():.2f}")

    print("Training gradient-boosting risk head (random row split)...")
    scorer, report = RiskScorer.train(X, y, seed=args.seed)
    print(
        f"  -> PR-AUC {report.pr_auc:.3f} | ROC-AUC {report.roc_auc:.3f} | "
        f"F1 {report.f1:.3f} | precision@50 {report.precision_at_50:.3f}"
    )

    holdout_report = None
    if args.holdout_scenarios:
        print(
            "Training honest benchmark (scenario-family held-out: "
            f"{args.holdout_scenarios})..."
        )
        try:
            _, holdout_report = RiskScorer.train(
                X, y,
                seed=args.seed,
                scenario_names=names,
                held_out_scenarios=args.holdout_scenarios,
            )
            print(
                f"  -> PR-AUC {holdout_report.pr_auc:.3f} | "
                f"F1 {holdout_report.f1:.3f} | "
                f"n_train={holdout_report.n_train} n_test={holdout_report.n_test}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  -> held-out split skipped: {exc}")

    print(f"Saving model artifact -> {args.out}")
    scorer.save(args.out)

    print(f"Measuring inference latency ({args.latency_samples} predictions)...")
    latency = measure_latency(scorer, n=args.latency_samples)
    print(
        f"  -> p50 {latency['p50_ms']:.3f} ms | "
        f"p95 {latency['p95_ms']:.3f} ms | "
        f"p99 {latency['p99_ms']:.3f} ms"
    )

    # Write a single canonical benchmark report consumed by the dashboard.
    payload = {
        **report.to_dict(),
        "latency": latency,
        "feature_importances": scorer.feature_importances,
        "seed": args.seed,
        "samples_per_scenario": args.samples_per_scenario,
        "noise_std": args.noise_std,
        "contamination": args.contamination,
        "scenarios_seen": sorted(set(names)),
        # Honest in-distribution disclaimer baked into the JSON so the
        # dashboard can always surface it.
        "split_method": "random row split (in-distribution)",
        "holdout_split": (
            holdout_report.to_dict() | {
                "split_method": "scenario-family held-out (out-of-distribution)",
                "held_out_scenarios": args.holdout_scenarios,
            }
            if holdout_report is not None else None
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote benchmark report -> {args.report}")


if __name__ == "__main__":
    main()
