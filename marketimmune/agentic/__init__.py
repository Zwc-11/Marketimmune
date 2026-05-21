"""Agentic immune-loop core.

Public surface:

* :class:`Agent`, :class:`AgentRun`, :class:`ToolCall`,
  :class:`DecisionTrace`, :class:`LLMClient`, :class:`NullLLMClient`
* The six Day-1 agents
* :class:`ImmuneLoop` + :class:`LoopResult` orchestrator
* Value objects each agent emits
"""

from marketimmune.agentic.base import (
    Agent,
    AgentRun,
    DecisionTrace,
    LLMClient,
    NullLLMClient,
    ToolCall,
)
from marketimmune.agentic.investigator import InvestigationCase, InvestigatorAgent
from marketimmune.agentic.judge import BenchmarkJudgeAgent, JudgeVerdict
from marketimmune.agentic.llm import AnthropicLLMClient, build_default_llm
from marketimmune.agentic.loop import ImmuneLoop, LoopResult
from marketimmune.agentic.market_simulator import MarketSimulatorAgent
from marketimmune.agentic.memory import ImmuneMemory, ImmuneMemoryAgent
from marketimmune.agentic.policy import PolicyAgent, PolicyDecision
from marketimmune.agentic.redteam import RedTeamScenarioAgent, ScenarioProposal
from marketimmune.agentic.sentinel import RiskSentinelAgent, SentinelAlert
from marketimmune.agentic.trainer import ModelTrainerAgent, TrainingJob

__all__ = [
    "Agent",
    "AgentRun",
    "AnthropicLLMClient",
    "BenchmarkJudgeAgent",
    "DecisionTrace",
    "ImmuneLoop",
    "ImmuneMemory",
    "ImmuneMemoryAgent",
    "InvestigationCase",
    "InvestigatorAgent",
    "JudgeVerdict",
    "LLMClient",
    "LoopResult",
    "MarketSimulatorAgent",
    "ModelTrainerAgent",
    "NullLLMClient",
    "PolicyAgent",
    "PolicyDecision",
    "RedTeamScenarioAgent",
    "RiskSentinelAgent",
    "ScenarioProposal",
    "SentinelAlert",
    "ToolCall",
    "TrainingJob",
    "build_default_llm",
]
