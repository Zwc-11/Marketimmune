from __future__ import annotations

import json
from pathlib import Path

from aegisbench.leaderboard.csv import write_leaderboard


def load(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    phase7 = load("reports/phase7/benchmark_report.json")
    phase8 = load("reports/phase8/metrics.json")
    phase9 = load("reports/phase9/order_s2p2_metrics.json")
    metrics = {
        "phase7": {
            "tasks": len(phase7["tasks"]),  # type: ignore[arg-type]
            "scenario_leakage": phase7["scenario_leakage"],
            "benchmark_report_json": True,
            "markdown_report": Path("reports/phase7/benchmark_report.md").exists(),
            "leaderboard_csv": Path("reports/phase7/leaderboard.csv").exists(),
        },
        "phase8": phase8,
        "phase9": phase9,
    }
    phase9["ood_passes_threshold"] = (  # type: ignore[index]
        phase9["s2p2_architecture"]["ood_auroc"] >= 0.60  # type: ignore[index]
    )
    leaderboard_path = Path("reports/phase7/leaderboard.csv")
    benchmark_rows = [
        {"model": "RuleEngine", "task": task, **values}
        for task, values in phase7["tasks"].items()  # type: ignore[union-attr]
    ]
    model_rows = [
        {"model": "GRU-MTPP", "task": "event_detection", **phase8["metrics"]},  # type: ignore[arg-type]
        {
            "model": "S2P2-NHP",
            "task": "event_detection",
            **phase9["models"]["S2P2-NHP"],  # type: ignore[index]
        },
    ]
    write_leaderboard(leaderboard_path, benchmark_rows + model_rows)
    Path("reports/phase7_9_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    Path("reports/phase7_9_proof.md").write_text(
        _proof_markdown(phase7, phase8, phase9),
        encoding="utf-8",
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))
    assert metrics["phase7"]["tasks"] >= 3  # type: ignore[index,operator]
    assert metrics["phase7"]["scenario_leakage"] is False  # type: ignore[index]
    assert phase7["examples"] >= 15000  # type: ignore[index,operator]
    assert phase7["tasks"]["event_detection"]["auroc"] >= 0.70  # type: ignore[index]
    assert phase7["tasks"]["harm_estimation"]["mae"] <= 0.50  # type: ignore[index]
    assert phase8["metrics"]["auroc"] >= 0.70  # type: ignore[index]
    assert phase8["model"] == "GRU-MTPP"
    assert phase8["p95_inference_latency_ms"] < 30  # type: ignore[operator]
    assert phase9["models"]["S2P2-NHP"]["auroc"] >= 0.70  # type: ignore[index]
    assert phase9["s2p2_architecture"]["nll_integral_approx"] == "Monte Carlo n_mc=50"  # type: ignore[index]
    assert phase9["s2p2_architecture"]["p95_inference_latency_ms"] < 20  # type: ignore[index]
    assert len(phase9["ablation_report"]) == 3  # type: ignore[arg-type]
    return 0


def _proof_markdown(
    phase7: dict[str, object],
    phase8: dict[str, object],
    phase9: dict[str, object],
) -> str:
    event_detection = phase7["tasks"]["event_detection"]  # type: ignore[index]
    action_selection = phase7["tasks"]["action_selection"]  # type: ignore[index]
    return (
        "# Phase 7-9 Proof\n\n"
        "This file is generated from JSON artifacts by `scripts/phase79_metrics.py`.\n\n"
        "## Phase 7\n\n"
        f"- Examples: {phase7['examples']}\n"
        f"- Splits: {phase7['splits']}\n"
        f"- Scenario leakage: {phase7['scenario_leakage']}\n"
        f"- Event detection PR-AUC: {event_detection['pr_auc']}\n"
        f"- Event detection AUROC: {event_detection['auroc']}\n"
        f"- False blocks per 100k: {action_selection['false_blocks_per_100k']}\n\n"
        "## Phase 8\n\n"
        f"- Model: {phase8['model']}\n"
        f"- Metrics: {phase8['metrics']}\n"
        f"- Eval sequences: {phase8['eval_sequences']}\n\n"
        "## Phase 9\n\n"
        f"- Models: {phase9['models']}\n"
        f"- Architecture: {phase9['s2p2_architecture']}\n"
        f"- Ablations: {phase9['ablation_report']}\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
