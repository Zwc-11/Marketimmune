import type { AgentRunSummary } from '../types';

const ALL_AGENTS = [
    'RedTeamScenarioAgent',
    'MarketSimulatorAgent',
    'RiskSentinelAgent',
    'InvestigatorAgent',
    'PolicyAgent',
    'ImmuneMemoryAgent',
    'ModelTrainerAgent',
    'BenchmarkJudgeAgent',
];

const SHORT: Record<string, string> = {
    RedTeamScenarioAgent: 'RedTeam',
    MarketSimulatorAgent: 'Simulator',
    RiskSentinelAgent: 'Sentinel',
    InvestigatorAgent: 'Investigator',
    PolicyAgent: 'Policy',
    ImmuneMemoryAgent: 'Memory',
    ModelTrainerAgent: 'Trainer',
    BenchmarkJudgeAgent: 'Judge',
};

export function LoopStrip({ runs }: { runs: AgentRunSummary[] }) {
    const byName = new Map(runs.map((r) => [r.agent_name, r]));
    return (
        <div className="loop-strip">
            {ALL_AGENTS.map((name) => {
                const run = byName.get(name);
                const cls = `loop-step${run && !run.success ? ' fail' : ''}`;
                return (
                    <div className={cls} key={name}>
                        <div className="step-name">{SHORT[name] ?? name}</div>
                        <div className="step-time">
                            {run ? `${run.duration_ms.toFixed(1)} ms` : '—'}
                        </div>
                        <div className="step-detail">
                            {run
                                ? `${run.tool_call_count} tool calls · ${run.trace_count} traces`
                                : 'not run'}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
