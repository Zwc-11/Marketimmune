"""Tests for promoted-model scoring of Hyperliquid Gold training rows."""

from __future__ import annotations

from pathlib import Path

import pytest

from marketimmune.ingest.hyperliquid_lake import write_parquet_records
from marketimmune.models.hyperliquid_gold_scoring import (
    GoldFillScore,
    score_gold_training_file,
    score_gold_training_rows,
)
from marketimmune.models.hyperliquid_markout_scorer import MarkoutPrediction


class _FakeScorer:
    model_name = "fake-catboost"

    def __init__(self, score: float = 0.82, action: str = "withhold_quote") -> None:
        self.score = score
        self.action = action
        self.seen: list[dict[str, float]] = []

    def predict(self, features: dict[str, float]) -> MarkoutPrediction:
        self.seen.append(features)
        return MarkoutPrediction(
            raw_score=self.score - 0.05,
            calibrated_score=self.score,
            decision_threshold=0.70,
            action=self.action,
        )


def _row(
    ts_ms: int,
    *,
    toxic: object = True,
    tid: object = 99,
    oid: object = None,
) -> dict[str, object]:
    return {
        "coin": "SOL",
        "ts_ms": ts_ms,
        "px": 101.0,
        "sz": 2.0,
        "side": "B",
        "maker_side": -1,
        "l2_mid": 100.0,
        "l2_spread_bps": 2.0,
        "l2_microprice": 100.5,
        "l2_top_imbalance": 0.2,
        "l2_ofi_event": 0.1,
        "l2_ofi_1s": -0.2,
        "l2_ofi_5s": 0.3,
        "l2_ofi_10s": 0.4,
        "asset_basis_bps": 1.0,
        "asset_funding": 0.0001,
        "asset_open_interest": 10_000.0,
        "asset_premium": 0.001,
        "markout_bps_10s": -4.5,
        "toxic_10s": toxic,
        "tid": tid,
        "oid": oid,
    }


def test_score_gold_training_rows_keeps_latest_and_scores_features() -> None:
    scorer = _FakeScorer()

    scores = score_gold_training_rows(
        [_row(3_000), _row(1_000), _row(2_000)],
        scorer,  # type: ignore[arg-type]
        limit=2,
    )

    assert [score.ts_ms for score in scores] == [2_000.0, 3_000.0]
    assert all(isinstance(score, GoldFillScore) for score in scores)
    assert scores[-1].alert_id == "hl_SOL_3000-99"
    assert scores[-1].action == "withhold_quote"
    assert scores[-1].markout_bps == pytest.approx(-4.5)
    assert scores[-1].toxic is True
    assert scores[-1].top_features(1) == ("asset_open_interest",)
    assert scorer.seen[-1]["l2_microprice_offset_bps"] == pytest.approx(50.0)


def test_score_gold_training_rows_can_keep_head_sample() -> None:
    scorer = _FakeScorer(score=0.35, action="quote")

    scores = score_gold_training_rows(
        [_row(3_000, toxic="yes", tid="101"), _row(1_000, toxic=None, tid=None)],
        scorer,  # type: ignore[arg-type]
        limit=1,
        latest=False,
    )

    assert scores[0].ts_ms == pytest.approx(1_000.0)
    assert scores[0].tid is None
    assert scores[0].toxic is None
    assert scores[0].to_dict()["top_features"][0] == "asset_open_interest"


def test_score_gold_training_rows_limit_zero_scores_every_row() -> None:
    scorer = _FakeScorer()

    scores = score_gold_training_rows(
        [_row(2_000), _row(1_000)],
        scorer,  # type: ignore[arg-type]
        limit=0,
    )

    assert [score.ts_ms for score in scores] == [1_000.0, 2_000.0]
    assert len(scorer.seen) == 2


def test_score_gold_training_file_reads_parquet(tmp_path: Path) -> None:
    path = tmp_path / "SOL-training.parquet"
    write_parquet_records(path, [_row(1_000, toxic="1", tid="77", oid="123")])

    scores = score_gold_training_file(
        path,
        _FakeScorer(),  # type: ignore[arg-type]
        limit=10,
    )

    assert len(scores) == 1
    assert scores[0].tid == 77
    assert scores[0].oid == 123
    assert scores[0].alert_id == "hl_SOL_1000-77-oid123"
    assert scores[0].toxic is True
