"""Score Hyperliquid Gold training rows with the promoted markout scorer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marketimmune.features.hyperliquid_features import prepare_markout_feature_row
from marketimmune.ingest.hyperliquid_lake import read_parquet_records
from marketimmune.models.hyperliquid_markout_scorer import HyperliquidMarkoutScorer


@dataclass(frozen=True, slots=True)
class GoldFillScore:
    """One scored real Hyperliquid maker fill from the Gold feature table."""

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
        ranked = sorted(self.feature_values.items(), key=lambda item: -abs(float(item[1])))
        return tuple(name for name, _value in ranked[:limit])

    def to_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin,
            "ts_ms": self.ts_ms,
            "px": self.px,
            "sz": self.sz,
            "side": self.side,
            "maker_side": self.maker_side,
            "model_name": self.model_name,
            "raw_score": self.raw_score,
            "calibrated_score": self.calibrated_score,
            "decision_threshold": self.decision_threshold,
            "action": self.action,
            "markout_bps": self.markout_bps,
            "toxic": self.toxic,
            "tid": self.tid,
            "oid": self.oid,
            "top_features": list(self.top_features()),
        }


def score_gold_training_rows(
    rows: Sequence[Mapping[str, Any]],
    scorer: HyperliquidMarkoutScorer,
    *,
    horizon: str = "10s",
    limit: int = 0,
    latest: bool = True,
) -> tuple[GoldFillScore, ...]:
    """Score Gold feature rows with the promoted model.

    ``latest=True`` keeps the most recent ``limit`` rows, which is what the app
    wants for replay/live evidence. Set it false for deterministic head samples.
    """
    ordered = sorted(rows, key=lambda row: _float(row["ts_ms"]))
    if limit > 0:
        ordered = ordered[-limit:] if latest else ordered[:limit]
    return tuple(_score_one(row, scorer, horizon=horizon) for row in ordered)


def score_gold_training_file(
    path: Path,
    scorer: HyperliquidMarkoutScorer,
    *,
    horizon: str = "10s",
    limit: int = 100,
    latest: bool = True,
) -> tuple[GoldFillScore, ...]:
    """Load and score a local Gold training parquet artifact."""
    return score_gold_training_rows(
        read_parquet_records(path),
        scorer,
        horizon=horizon,
        limit=limit,
        latest=latest,
    )


def _score_one(
    row: Mapping[str, Any],
    scorer: HyperliquidMarkoutScorer,
    *,
    horizon: str,
) -> GoldFillScore:
    features = prepare_markout_feature_row(row)
    prediction = scorer.predict(features)
    return GoldFillScore(
        coin=str(row.get("coin", "")),
        ts_ms=_float(row["ts_ms"]),
        px=_float(row["px"]),
        sz=_float(row["sz"]),
        side=str(row.get("side", "")),
        maker_side=int(_float(row["maker_side"])),
        model_name=scorer.model_name,
        raw_score=prediction.raw_score,
        calibrated_score=prediction.calibrated_score,
        decision_threshold=prediction.decision_threshold,
        action=prediction.action,
        feature_values=features,
        markout_bps=_optional_float(row.get(f"markout_bps_{horizon}")),
        toxic=_optional_bool(row.get(f"toxic_{horizon}")),
        tid=_optional_int(row.get("tid")),
        oid=_optional_int(row.get("oid")),
    )


def _float(value: object) -> float:
    return float(str(value))


def _optional_float(value: object) -> float | None:
    return None if value is None else _float(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(_float(value))


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}
