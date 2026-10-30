"""Time the markout pipeline's hot paths on a synthetic panel shaped like the SOL run.

The real Gold partitions are local-only, so this generates the same shapes instead:
724,150 fill rows over five days, a 91-point threshold grid, a 400K-snapshot L2 day,
190K fills to label, and a 150-tree depth-6 model. Every stage is timed through the
public API the trainer uses, and the JSON it writes is what docs/performance.md
quotes.

    python eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from marketimmune.features.training_rows import (
    HYPERLIQUID_MARKOUT_FEATURE_COLUMNS,
    build_hyperliquid_training_rows,
    l2_rows_with_ofi,
)
from marketimmune.lake.gold import build_markout_gold_rows
from marketimmune.models.cross_validation import temporal_fold_arrays
from marketimmune.models.evaluation import (
    evaluate_markout_predictions,
    fold_local_markout_thresholds,
    select_markout_threshold,
)
from marketimmune.serving.oblivious_trees import ObliviousEnsemble, ObliviousTree
from marketimmune.sources.hyperliquid_l2_archive import BookSnapshot, L2Level
from marketimmune.sources.hyperliquid_node_fills import NodeFill

DAY_MS = 86_400_000
T0 = 1_779_840_000_000.0
GRID = tuple(round(0.05 + 0.01 * i, 10) for i in range(91))


def timed(fn: Callable[[], Any], repeats: int) -> tuple[float, Any]:
    """Median wall time over ``repeats`` runs (seconds) and the last result."""
    samples: list[float] = []
    result: Any = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), result


def evaluation_stages(rng: np.random.Generator, rows: int, repeats: int) -> dict[str, float]:
    ts = np.sort(T0 + rng.uniform(0, 5 * DAY_MS, rows)).round()
    labels = rng.random(rows) < 0.45
    probs = np.clip(rng.beta(2, 3, rows) + 0.12 * labels, 0, 1)
    markouts = rng.normal(0.4, 3.0, rows) - 2.5 * labels
    out: dict[str, float] = {}
    for scheme in ("purged_kfold", "walk_forward"):
        out[f"temporal_folds_{scheme}"], _ = timed(
            lambda scheme=scheme: temporal_fold_arrays(
                ts, n_splits=5, purge_ms=60_000, embargo_ms=60_000, scheme=scheme
            ),
            repeats,
        )
    out["fold_local_thresholds"], (thresholds, _) = timed(
        lambda: fold_local_markout_thresholds(
            ts, probs, markouts, n_splits=5, purge_ms=60_000, embargo_ms=60_000,
            threshold_grid=GRID, min_quote_rate=0.2, max_quote_rate=0.95,
            scheme="purged_kfold",
        ),
        repeats,
    )
    out["select_threshold"], _ = timed(
        lambda: select_markout_threshold(
            probs, markouts, GRID, min_quote_rate=0.2, max_quote_rate=0.95
        ),
        repeats,
    )
    out["evaluate_oof_report"], _ = timed(
        lambda: evaluate_markout_predictions(
            ts, labels, probs, markouts, model_name="bench", n_splits=5, purge_ms=60_000,
            embargo_ms=60_000, decision_threshold=None, decision_thresholds=thresholds,
            scheme="purged_kfold",
        ),
        repeats,
    )
    return out


def feature_stages(rng: np.random.Generator, snapshots: int, fills: int) -> dict[str, float]:
    l2_ts = np.sort(T0 + rng.uniform(0, DAY_MS, snapshots)).round()
    mid = 150 + np.cumsum(rng.normal(0, 0.01, snapshots))
    spread = rng.uniform(0.01, 0.03, snapshots)
    sizes = rng.uniform(1, 50, (snapshots, 2))
    l2_rows = [
        {
            "coin": "SOL", "ts_ms": float(l2_ts[i]), "mid": float(mid[i]),
            "spread_bps": float(spread[i] / mid[i] * 1e4), "microprice": float(mid[i]),
            "top_imbalance": 0.0, "bid_px": float(mid[i] - spread[i] / 2),
            "ask_px": float(mid[i] + spread[i] / 2), "bid_sz": float(sizes[i, 0]),
            "ask_sz": float(sizes[i, 1]),
        }
        for i in range(snapshots)
    ]
    fill_ts = np.sort(T0 + rng.uniform(0, DAY_MS, fills)).round()
    label_rows = [
        {"coin": "SOL", "ts_ms": int(fill_ts[i]), "px": 150.0, "sz": 1.0, "maker_side": 1}
        for i in range(fills)
    ]
    asset_rows = [
        {"coin": "SOL", "ts_ms": T0 + k * 60_000, "basis_bps": 0.5, "funding": 1e-5,
         "open_interest": 1e6, "premium": 1e-4}
        for k in range(1_440)
    ]
    books = [
        BookSnapshot(
            ts_ms=int(l2_ts[i]), coin="SOL",
            bids=(L2Level(px=float(mid[i] - 0.01), sz=10.0, n=1),),
            asks=(L2Level(px=float(mid[i] + 0.01), sz=12.0, n=1),),
        )
        for i in range(snapshots)
    ]
    node_fills = [
        NodeFill(coin="SOL", ts_ms=int(fill_ts[i]), px=150.0, sz=1.0,
                 side="B" if i % 2 else "A", crossed=bool(i % 3))
        for i in range(fills)
    ]
    out: dict[str, float] = {}
    out["l2_rows_with_ofi"], _ = timed(lambda: l2_rows_with_ofi(l2_rows), 1)
    out["training_rows_asof_join"], _ = timed(
        lambda: build_hyperliquid_training_rows(label_rows, l2_rows, asset_rows), 1
    )
    out["gold_markout_labels"], _ = timed(lambda: build_markout_gold_rows(node_fills, books), 1)
    return out


def scoring_stages(rng: np.random.Generator, rows: int, repeats: int) -> dict[str, float]:
    n_features = len(HYPERLIQUID_MARKOUT_FEATURE_COLUMNS)
    trees = tuple(
        ObliviousTree(
            features=tuple(int(f) for f in rng.integers(0, n_features, 6)),
            borders=tuple(float(b) for b in rng.normal(size=6)),
            leaves=tuple(float(v) for v in rng.normal(scale=0.05, size=64)),
        )
        for _ in range(150)
    )
    model = ObliviousEnsemble(trees=trees, n_features=n_features)
    matrix = rng.normal(size=(rows, n_features))
    out: dict[str, float] = {}
    out[f"oblivious_trees_batch_{rows}"], _ = timed(lambda: model.predict_proba(matrix), repeats)
    single = matrix[:1]
    per_row, _ = timed(lambda: model.predict_proba(single), max(repeats, 200))
    out["oblivious_trees_single_row"] = per_row
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=724_150)
    parser.add_argument("--snapshots", type=int, default=400_000)
    parser.add_argument("--fills", type=int, default=190_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    rng = np.random.default_rng(args.seed)

    stages: dict[str, float] = {}
    stages.update(evaluation_stages(rng, args.rows, args.repeats))
    stages.update(feature_stages(rng, args.snapshots, args.fills))
    stages.update(scoring_stages(rng, 100_000, args.repeats))
    payload = {
        "config": vars(args) | {"out": str(args.out) if args.out else None},
        "machine": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
        },
        "seconds": {name: round(value, 5) for name, value in stages.items()},
    }
    for name, value in stages.items():
        print(f"{name:<36} {value * 1000:>10.2f} ms")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
