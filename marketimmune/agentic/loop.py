"""ImmuneLoop — orchestrates one full agentic cycle.

Strings the five Day-1 agents into one explicit pipeline:

    RedTeam → Simulator → Sentinel → Investigator → Policy → Memory

The orchestrator itself is data-only: it holds no business logic
beyond wiring agent outputs into the next agent's inputs. That makes
it easy to swap a deterministic agent for an LLM-driven one later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from marketimmune.agentic.base import AgentRun, LLMClient
from marketimmune.agentic.investigator import InvestigationCase, InvestigatorAgent
from marketimmune.agentic.judge import BenchmarkJudgeAgent, JudgeVerdict
from marketimmune.agentic.market_simulator import MarketSimulatorAgent
from marketimmune.agentic.memory import ImmuneMemory, ImmuneMemoryAgent
from marketimmune.agentic.policy import PolicyAgent, PolicyDecision
from marketimmune.agentic.redteam import RedTeamScenarioAgent, ScenarioProposal
from marketimmune.agentic.sentinel import RiskSentinelAgent, SentinelAlert
from marketimmune.agentic.trainer import ModelTrainerAgent, TrainingJob


@dataclass(frozen=True, slots=True)
class LoopResult:
    """Everything one loop iteration produced."""

    proposal: ScenarioProposal | None
    alerts: tuple[SentinelAlert, ...]
    cases: tuple[InvestigationCase, ...]
    decisions: tuple[PolicyDecision, ...]
    new_memories: tuple[ImmuneMemory, ...]
    aggregate_posture: str
    agent_runs: tuple[AgentRun, ...]
    training_job: TrainingJob | None = None
    judge_verdict: JudgeVerdict | None = None


@dataclass
class ImmuneLoop:
    """Strings the seven agents into one full agentic cycle."""

    redteam: RedTeamScenarioAgent = field(default_factory=RedTeamScenarioAgent)
    simulator: MarketSimulatorAgent = field(default_factory=MarketSimulatorAgent)
    sentinel: RiskSentinelAgent = field(default_factory=RiskSentinelAgent)
    investigator: InvestigatorAgent = field(default_factory=InvestigatorAgent)
    policy: PolicyAgent = field(default_factory=PolicyAgent)
    memory: ImmuneMemoryAgent = field(default_factory=ImmuneMemoryAgent)
    trainer: ModelTrainerAgent = field(default_factory=ModelTrainerAgent)
    judge: BenchmarkJudgeAgent = field(default_factory=BenchmarkJudgeAgent)
    # Whether to run trainer + judge each loop. Disabled in tests and
    # in the demo's "fast" mode because the trainer subprocess takes
    # ~3-5 seconds (acceptable in a recorded demo, slow in unit tests).
    enable_self_improvement: bool = True

    @classmethod
    def with_llm(cls, llm: LLMClient) -> "ImmuneLoop":
        """Convenience constructor that wires the same LLM into every agent."""
        return cls(
            redteam=RedTeamScenarioAgent(llm=llm),
            simulator=MarketSimulatorAgent(llm=llm),
            sentinel=RiskSentinelAgent(llm=llm),
            investigator=InvestigatorAgent(llm=llm),
            policy=PolicyAgent(llm=llm),
            memory=ImmuneMemoryAgent(llm=llm),
            trainer=ModelTrainerAgent(llm=llm),
            judge=BenchmarkJudgeAgent(llm=llm),
        )

    def run(
        self,
        *,
        difficulty: str = "medium",
        tick_limit: int = 60,
        existing_memories: Sequence[ImmuneMemory] = (),
        retrain_pending: bool = False,
        force_retrain: bool = False,
    ) -> LoopResult:
        runs: list[AgentRun] = []

        # 1. RedTeam proposes a fresh adversarial scenario.
        rt_run = self.redteam.run(
            goal="propose adversarial scenario",
            difficulty=difficulty,
        )
        runs.append(rt_run)
        if not rt_run.success:
            return LoopResult(
                proposal=None, alerts=(), cases=(), decisions=(),
                new_memories=(), aggregate_posture="no_action",
                agent_runs=tuple(runs),
            )
        proposal_dict = dict(rt_run.output)
        proposal = ScenarioProposal(
            **{k: v for k, v in proposal_dict.items()
               if k in ScenarioProposal.__annotations__}
        )

        # 2. Simulator runs the proposal through the parquet replay.
        sim_run = self.simulator.run(
            goal="simulate red-team proposal",
            proposal=proposal,
            limit=tick_limit,
        )
        runs.append(sim_run)
        plan = sim_run.linked_artifacts.get("plan") if sim_run.success else None
        if plan is None:
            return LoopResult(
                proposal=proposal, alerts=(), cases=(), decisions=(),
                new_memories=(), aggregate_posture="no_action",
                agent_runs=tuple(runs),
            )

        # 3. Sentinel filters the tick stream into alerts.
        sent_run = self.sentinel.run(
            goal="surface high-risk events",
            plan=plan,
        )
        runs.append(sent_run)
        alerts: list[SentinelAlert] = (
            sent_run.linked_artifacts.get("alerts", []) if sent_run.success else []
        )

        # 4. Investigator builds a case file per alert.
        inv_run = self.investigator.run(
            goal="build evidence case files",
            plan=plan,
            alerts=alerts,
        )
        runs.append(inv_run)
        cases: list[InvestigationCase] = (
            inv_run.linked_artifacts.get("cases", []) if inv_run.success else []
        )

        # 5. Policy maps each case to a recommended control action.
        pol_run = self.policy.run(
            goal="recommend control actions",
            cases=cases,
        )
        runs.append(pol_run)
        decisions: list[PolicyDecision] = (
            pol_run.linked_artifacts.get("decisions", []) if pol_run.success else []
        )
        posture = pol_run.output.get("aggregate_posture", "no_action")

        # 6. Memory remembers any novel patterns we saw.
        mem_run = self.memory.run(
            goal="decide what to remember",
            cases=cases,
            decisions=decisions,
            existing_memories=list(existing_memories),
            scenario_source=proposal.name,
        )
        runs.append(mem_run)
        new_memories: list[ImmuneMemory] = (
            mem_run.linked_artifacts.get("new_memories", []) if mem_run.success else []
        )

        # 7. Trainer (optional) — retrain when memory grew or pending.
        training_job: TrainingJob | None = None
        verdict: JudgeVerdict | None = None
        if self.enable_self_improvement:
            train_run = self.trainer.run(
                goal="decide whether to retrain",
                new_memories=new_memories,
                retrain_pending=retrain_pending,
                force=force_retrain,
            )
            runs.append(train_run)
            training_job = (
                train_run.linked_artifacts.get("job") if train_run.success else None
            )

            # 8. Judge — only votes when there's a candidate.
            if training_job is not None:
                judge_run = self.judge.run(
                    goal="vote on candidate promotion",
                    job=training_job,
                )
                runs.append(judge_run)
                verdict = (
                    judge_run.linked_artifacts.get("verdict") if judge_run.success else None
                )

        return LoopResult(
            proposal=proposal,
            alerts=tuple(alerts),
            cases=tuple(cases),
            decisions=tuple(decisions),
            new_memories=tuple(new_memories),
            aggregate_posture=posture,
            agent_runs=tuple(runs),
            training_job=training_job,
            judge_verdict=verdict,
        )
