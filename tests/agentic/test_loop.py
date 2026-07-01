"""Tests for ImmuneLoop orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from marketimmune.agentic.judge import BenchmarkJudgeAgent, JudgeVerdict
from marketimmune.agentic.loop import ImmuneLoop, LoopResult
from marketimmune.agentic.market_simulator import MarketSimulatorAgent
from marketimmune.agentic.trainer import HyperliquidTrainingSpec, ModelTrainerAgent
from marketimmune.models.hyperliquid_gold_scoring import GoldFillScore

from .conftest import _make_training_job


def _write_kline_parquet(lake_root: Path, symbol: str = "BTCUSDT") -> None:
    out_dir = lake_root / "klines" / symbol / "1m"
    out_dir.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "event_id": ["ev1", "ev2", "ev3"],
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:01:00Z",
                "2026-01-01T00:02:00Z",
            ],
            "open_price": [100.0, 101.0, 102.0],
            "high_price": [105.0, 106.0, 107.0],
            "low_price": [99.0, 100.0, 101.0],
            "close_price": [101.0, 102.0, 103.0],
            "volume": [1000.0, 2000.0, 3000.0],
            "trade_count": [10, 20, 30],
        }
    )
    pq.write_table(table, out_dir / f"{symbol}-klines-1m-2026-01-01.parquet")


def _gold_score() -> GoldFillScore:
    return GoldFillScore(
        coin="SOL",
        ts_ms=1_780_272_011_755.0,
        px=101.0,
        sz=2.0,
        side="B",
        maker_side=-1,
        model_name="fake-catboost",
        raw_score=0.77,
        calibrated_score=0.82,
        decision_threshold=0.70,
        action="withhold_quote",
        feature_values={"asset_open_interest": 10_000.0, "l2_top_imbalance": 0.2},
        markout_bps=-4.5,
        toxic=True,
        tid=123,
    )


# ---------------------------------------------------------------------------
# Basic loop test with a real lake (test parquet data)
# ---------------------------------------------------------------------------


def test_loop_full_run(tmp_path: Path) -> None:
    """Run the complete immune loop with minimal parquet lake data."""
    _write_kline_parquet(tmp_path)
    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        enable_self_improvement=False,
    )
    result = loop.run(difficulty="medium", tick_limit=3)
    assert isinstance(result, LoopResult)
    assert result.proposal is not None
    # At least one agent run was recorded.
    assert len(result.agent_runs) > 0


def test_loop_disables_self_improvement(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        enable_self_improvement=False,
    )
    result = loop.run(tick_limit=3)
    assert result.training_job is None
    assert result.judge_verdict is None


def test_loop_returns_early_on_redteam_failure() -> None:
    """When the RedTeam agent fails, the loop returns early with no proposal."""
    from collections.abc import Mapping

    from marketimmune.agentic.redteam import RedTeamScenarioAgent

    class _FailRedTeam(RedTeamScenarioAgent):
        def _execute(self, **_: Any) -> Mapping[str, Any]:
            raise RuntimeError("redteam failed")

    loop = ImmuneLoop(
        redteam=_FailRedTeam(),
        enable_self_improvement=False,
    )
    result = loop.run()
    assert result.proposal is None
    assert result.alerts == ()


def test_loop_returns_early_on_simulator_failure() -> None:
    """When the Simulator agent fails, the loop returns early after proposal."""
    from collections.abc import Mapping

    from marketimmune.agentic.market_simulator import MarketSimulatorAgent

    class _FailSimulator(MarketSimulatorAgent):
        def _execute(self, **_: Any) -> Mapping[str, Any]:
            raise RuntimeError("simulator failed")

    loop = ImmuneLoop(
        simulator=_FailSimulator(),
        enable_self_improvement=False,
    )
    result = loop.run()
    assert result.proposal is not None
    assert result.alerts == ()
    assert result.cases == ()


def test_loop_with_llm_factory() -> None:
    """with_llm() correctly wires the same LLM into every agent."""
    from marketimmune.agentic.base import NullLLMClient
    llm = NullLLMClient()
    loop = ImmuneLoop.with_llm(llm)
    assert loop.sentinel.llm is llm
    assert loop.investigator.llm is llm
    assert loop.policy.llm is llm


def test_loop_with_hyperliquid_training_factory() -> None:
    from marketimmune.agentic.base import NullLLMClient

    llm = NullLLMClient()
    spec = HyperliquidTrainingSpec(coin="SOL", date="20260601", max_rows=100)
    loop = ImmuneLoop.with_hyperliquid_training(spec, llm=llm)

    assert loop.trainer.training_mode == "hyperliquid_markout"
    assert loop.trainer.hyperliquid_spec is spec
    assert loop.trainer.llm is llm
    assert loop.judge.llm is llm


def test_loop_with_hyperliquid_training_factory_without_llm() -> None:
    spec = HyperliquidTrainingSpec(coin="SOL", date="20260601")
    loop = ImmuneLoop.with_hyperliquid_training(spec)

    assert loop.trainer.training_mode == "hyperliquid_markout"
    assert loop.trainer.hyperliquid_spec is spec


def test_loop_result_fields(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        enable_self_improvement=False,
    )
    result = loop.run(tick_limit=3)
    # All collections should be tuples.
    assert isinstance(result.alerts, tuple)
    assert isinstance(result.cases, tuple)
    assert isinstance(result.decisions, tuple)
    assert isinstance(result.new_memories, tuple)
    assert isinstance(result.agent_runs, tuple)


def test_loop_with_self_improvement_trainer_skips(tmp_path: Path) -> None:
    """enable_self_improvement=True with high threshold skips retraining."""
    _write_kline_parquet(tmp_path)
    # Set a very high min_new_memories so the trainer always skips.
    from marketimmune.agentic.trainer import ModelTrainerAgent as _Trainer
    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        trainer=_Trainer(min_new_memories=9999),
        enable_self_improvement=True,
    )
    result = loop.run(tick_limit=3, retrain_pending=False, force_retrain=False)
    assert isinstance(result, LoopResult)
    trainer_runs = [r for r in result.agent_runs if r.agent_name == "ModelTrainerAgent"]
    assert len(trainer_runs) == 1
    assert result.training_job is None


def test_loop_with_self_improvement_judges_candidate(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    job = _make_training_job(success=True)

    class _FastTrainer(ModelTrainerAgent):
        def _execute(self, *, goal: str, **_: Any) -> dict[str, object]:
            return {
                "output": {"ran_training": True, "job": job.to_dict()},
                "artifacts": {"job": job},
            }

    class _FastJudge(BenchmarkJudgeAgent):
        def _execute(self, *, goal: str, **_: Any) -> dict[str, object]:
            verdict = JudgeVerdict(
                decision_id="judge_test",
                verdict="promote",
                candidate_model=job.candidate_model,
                incumbent_model=job.incumbent_model,
                promote_votes=5,
                reject_votes=0,
                rationale="test",
                metrics={},
                criteria={},
            )
            return {
                "output": {"verdict": verdict.to_dict()},
                "artifacts": {"verdict": verdict},
            }

    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        trainer=_FastTrainer(),
        judge=_FastJudge(),
        enable_self_improvement=True,
    )
    result = loop.run(tick_limit=3, force_retrain=True)
    assert result.training_job is job
    assert result.judge_verdict is not None
    assert result.judge_verdict.verdict == "promote"


def test_loop_passes_significant_drift_to_trainer(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)

    class _CaptureTrainer(ModelTrainerAgent):
        def _execute(
            self,
            *,
            goal: str,
            retrain_pending: bool = False,
            **_: Any,
        ) -> dict[str, object]:
            return {
                "output": {"saw_retrain_pending": retrain_pending},
                "artifacts": {"job": None},
            }

    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        trainer=_CaptureTrainer(),
        enable_self_improvement=True,
    )
    result = loop.run(
        tick_limit=3,
        drift_reference_scores=[float(i) for i in range(100)],
        drift_current_scores=[float(i) + 50.0 for i in range(100)],
    )
    trainer_runs = [r for r in result.agent_runs if r.agent_name == "ModelTrainerAgent"]
    assert result.drift_report is not None
    assert result.drift_report.retrain_recommended is True
    assert trainer_runs[-1].output["saw_retrain_pending"] is True


def test_loop_routes_gold_fill_scores_to_policy(tmp_path: Path) -> None:
    _write_kline_parquet(tmp_path)
    loop = ImmuneLoop(
        simulator=MarketSimulatorAgent(lake_root=tmp_path, model_path=None),
        enable_self_improvement=False,
    )

    result = loop.run(tick_limit=1, gold_fill_scores=[_gold_score()])

    assert any(alert.source == "hyperliquid_gold" for alert in result.alerts)
    assert any(
        case.suspected_behavior == "Adverse-selection markout risk"
        for case in result.cases
    )
    assert result.decisions
