"""Export a promoted CatBoost markout model for the web terminal and CatBoost-free serving.

Writes one compact JSON (trees + isotonic calibrator + policy threshold) that both
``frontend/src/lib/obliviousTrees.ts`` and ``marketimmune.serving.oblivious_trees``
evaluate. Run after training:

    python -m marketimmune.cli.export_web_model \\
        --model data/models/hyperliquid_catboost_SOL_10s.cbm \\
        --report eval/hyperliquid_markout_SOL_panel.json
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from marketimmune.serving.oblivious_trees import compact_from_catboost_json

DEFAULT_OUT = Path("frontend/public/model/markout.json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, required=True, help="CatBoost .cbm file")
    parser.add_argument(
        "--calibrator",
        type=Path,
        default=None,
        help="Isotonic JSON; defaults to <model>.isotonic.json",
    )
    parser.add_argument("--report", type=Path, required=True, help="Training report JSON")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def build_web_artifact(
    catboost_json: dict[str, Any],
    calibrator: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    feature_columns = calibrator.get("feature_columns") or report.get("feature_columns")
    if not feature_columns:
        raise ValueError("feature_columns missing from calibrator and report")
    holdout = report.get("holdout_split") or {}
    holdout_delta = (holdout.get("baseline_comparison") or {}).get("event_ofi", {})
    return compact_from_catboost_json(
        catboost_json,
        feature_columns=[str(name) for name in feature_columns],
        metadata={
            "model_name": report.get("model_name"),
            "coin": report.get("coin"),
            "horizon": report.get("horizon"),
            "dataset_label": report.get("dataset_label"),
            "cv_scheme": report.get("cv_scheme", "purged_kfold"),
            "decision_threshold": calibrator.get("deployment_decision_threshold"),
            "calibrator": {
                "enabled": bool(calibrator.get("enabled", False)),
                "x": [float(v) for v in calibrator.get("x_thresholds", [])],
                "y": [float(v) for v in calibrator.get("y_thresholds", [])],
            },
            "holdout": {
                "pr_auc": holdout.get("pr_auc"),
                "markout_lift_bps": holdout.get("markout_lift_bps"),
                "lift_vs_event_ofi_bps": holdout_delta.get("markout_lift_bps"),
            },
        },
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from catboost import CatBoostClassifier
    except ImportError as exc:  # pragma: no cover - environment boundary.
        raise SystemExit("Install the training extra: pip install -e '.[training]'") from exc
    model = CatBoostClassifier()
    model.load_model(str(args.model))
    with tempfile.TemporaryDirectory() as tmp:
        exported = Path(tmp) / "model.json"
        model.save_model(str(exported), format="json")
        catboost_json = json.loads(exported.read_text(encoding="utf-8"))
    calibrator_path = args.calibrator or args.model.with_suffix(".isotonic.json")
    artifact = build_web_artifact(
        catboost_json,
        json.loads(calibrator_path.read_text(encoding="utf-8")),
        json.loads(args.report.read_text(encoding="utf-8")),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {args.out} ({len(artifact['trees'])} trees, {args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
