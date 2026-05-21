import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
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
const SHORT = {
    RedTeamScenarioAgent: 'RedTeam',
    MarketSimulatorAgent: 'Simulator',
    RiskSentinelAgent: 'Sentinel',
    InvestigatorAgent: 'Investigator',
    PolicyAgent: 'Policy',
    ImmuneMemoryAgent: 'Memory',
    ModelTrainerAgent: 'Trainer',
    BenchmarkJudgeAgent: 'Judge',
};
export function LoopStrip({ runs }) {
    const byName = new Map(runs.map((r) => [r.agent_name, r]));
    return (_jsx("div", { className: "loop-strip", children: ALL_AGENTS.map((name) => {
            const run = byName.get(name);
            const cls = `loop-step${run && !run.success ? ' fail' : ''}`;
            return (_jsxs("div", { className: cls, children: [_jsx("div", { className: "step-name", children: SHORT[name] ?? name }), _jsx("div", { className: "step-time", children: run ? `${run.duration_ms.toFixed(1)} ms` : '—' }), _jsx("div", { className: "step-detail", children: run
                            ? `${run.tool_call_count} tool calls · ${run.trace_count} traces`
                            : 'not run' })] }, name));
        }) }));
}
