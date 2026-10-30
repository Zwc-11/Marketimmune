"""Regenerate the fixtures that pin the TypeScript feature/model code to Python.

The web terminal recomputes OFI windows and evaluates the exported CatBoost trees in
the browser. ``frontend/src/lib/parity.test.ts`` replays these Python outputs, so a
drift between the two implementations fails ``npm test``.

    python -m marketimmune.cli.make_parity_fixtures
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from marketimmune.features.training_rows import l2_rows_with_ofi
from marketimmune.serving.oblivious_trees import compact_from_catboost_json
from marketimmune.serving.scorer import IsotonicCalibrator

OUT = Path("frontend/src/lib/__fixtures__/parity.json")


def ofi_fixture(rng: np.random.Generator) -> dict[str, object]:
    ts = np.cumsum(rng.choice([0, 1, 120, 400, 900, 2_500], size=80)) + 1_000
    mid = 94.0 + np.cumsum(rng.choice([-0.001, 0.0, 0.001], size=80))
    rows = [
        {
            "coin": "SOL",
            "ts_ms": float(ts[i]),
            "bid_px": round(float(mid[i] - 0.0005), 4),
            "ask_px": round(float(mid[i] + 0.0005), 4),
            "bid_sz": float(rng.choice([0.0, 3.5, 40.0, 766.78])),
            "ask_sz": float(rng.choice([0.0, 1.0, 90.31, 300.0])),
        }
        for i in range(ts.size)
    ]
    enriched = l2_rows_with_ofi(rows)
    return {
        "rows": rows,
        "expected": [
            {key: row[key] for key in ("ts_ms", "ofi_event", "ofi_1s", "ofi_5s", "ofi_10s")}
            for row in enriched
        ],
    }


def model_fixture(rng: np.random.Generator) -> dict[str, object]:
    from catboost import CatBoostClassifier

    x = rng.normal(size=(1_500, 5))
    y = (x[:, 0] - 0.5 * x[:, 2] + rng.normal(size=1_500) > 0).astype(int)
    model = CatBoostClassifier(
        iterations=12, depth=3, verbose=False, random_seed=4, allow_writing_files=False
    )
    model.fit(x, y)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.json"
        model.save_model(str(path), format="json")
        exported = json.loads(path.read_text(encoding="utf-8"))
    probe = rng.normal(size=(40, 5))
    probe[3, 1] = np.nan
    calibrator = IsotonicCalibrator(
        enabled=True,
        x_thresholds=(0.0, 0.2, 0.2, 0.45, 0.6, 1.0),
        y_thresholds=(0.02, 0.1, 0.18, 0.4, 0.55, 0.97),
        feature_columns=tuple(f"f{i}" for i in range(5)),
        deployment_decision_threshold=0.3,
    )
    raw = model.predict_proba(probe)[:, 1]
    return {
        "model": compact_from_catboost_json(
            exported, feature_columns=[f"f{i}" for i in range(5)]
        ),
        "rows": [[None if np.isnan(v) else float(v) for v in row] for row in probe],
        "expected_raw": raw.tolist(),
        "calibrator": {"enabled": True, "x": list(calibrator.x_thresholds),
                       "y": list(calibrator.y_thresholds)},
        "expected_calibrated": [calibrator.transform_one(float(p)) for p in raw],
    }


def main() -> int:
    rng = np.random.default_rng(20260601)
    payload = {"ofi": ofi_fixture(rng), "model": model_fixture(rng)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
