"""Score the newest Gold training rows with the promoted markout scorer (the server's decision feed)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.features.training_rows import prepare_markout_feature_row
from marketimmune.lake.tables import read_parquet_window
from marketimmune.serving.scorer import HyperliquidMarkoutScorer


@dataclass(frozen=True, slots=True)
class GoldFillScore:
    """One scored maker fill from a Gold training partition."""

    coin: str
    ts_ms: float
    px: float
    sz: float
    side: str
    maker_side: int
    model_name: str
    raw_score: float
    calibrated_score: float
    decision_threshold: float | None
    action: str
    feature_values: Mapping[str, float]
    markout_bps: float | None = None
    toxic: bool | None = None
    tid: int | None = None
    oid: int | None = None

    @property
    def alert_id(self) -> str:
        trade_id = f"-{self.tid}" if self.tid is not None else ""
        order_id = f"-oid{self.oid}" if self.oid is not None else ""
        return f"hl_{self.coin}_{int(self.ts_ms)}{trade_id}{order_id}"

    def top_features(self, limit: int = 3) -> tuple[str, ...]:
        """Feature names by descending absolute value."""
        ranked = sorted(self.feature_values.items(), key=lambda item: -abs(float(item[1])))
        return tuple(name for name, _value in ranked[:limit])


def score_gold_training_file(
    path: Path,
    scorer: HyperliquidMarkoutScorer,
    *,
    horizon: str = "10s",
    limit: int = 100,
    latest: bool = True,
) -> tuple[GoldFillScore, ...]:
    """Score the newest (or, with ``latest=False``, oldest) ``limit`` rows in one model call;
    ``limit <= 0`` scores every row. Only those rows become Python dicts."""
    rows = read_parquet_window(path, limit=limit, latest=latest)
    features = [prepare_markout_feature_row(row) for row in rows]
    predictions = scorer.predict_batch(features)
    return tuple(
        GoldFillScore(
            coin=str(row.get("coin", "")),
            ts_ms=float(row["ts_ms"]),
            px=float(row["px"]),
            sz=float(row["sz"]),
            side=str(row.get("side", "")),
            maker_side=int(row["maker_side"]),
            model_name=scorer.model_name,
            raw_score=prediction.raw_score,
            calibrated_score=prediction.calibrated_score,
            decision_threshold=prediction.decision_threshold,
            action=prediction.action,
            feature_values=feature_row,
            markout_bps=_optional(float, row.get(f"markout_bps_{horizon}")),
            toxic=_optional(bool, row.get(f"toxic_{horizon}")),
            tid=_optional(int, row.get("tid")),
            oid=_optional(int, row.get("oid")),
        )
        for row, feature_row, prediction in zip(rows, features, predictions, strict=True)
    )


def _optional[T](kind: Callable[[Any], T], value: Any) -> T | None:
    return None if value is None else kind(value)
