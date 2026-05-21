import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchLLMStatus, fetchState, runLoop } from './api';
import { LoopStrip } from './components/LoopStrip';
import { InvestigationCaseCard } from './components/InvestigationCaseCard';
import { PromotionPanel } from './components/PromotionPanel';
import { MemoryShelf } from './components/MemoryShelf';
import { SimulatorView } from './components/SimulatorView';
export function App() {
    if (window.location.pathname.startsWith('/dashboard/agentic/v2/simulator/')) {
        return _jsx(SimulatorView, {});
    }
    return _jsx(ImmuneLoopApp, {});
}
function ImmuneLoopApp() {
    const [state, setState] = useState(null);
    const [llm, setLlm] = useState(null);
    const [error, setError] = useState('');
    const [running, setRunning] = useState(false);
    const [runStatus, setRunStatus] = useState('');
    const [difficulty, setDifficulty] = useState('easy');
    const refresh = useCallback(async () => {
        try {
            const [s, l] = await Promise.all([fetchState(), fetchLLMStatus()]);
            setState(s);
            setLlm(l);
            setError('');
        }
        catch (e) {
            setError(e.message);
        }
    }, []);
    useEffect(() => {
        refresh();
    }, [refresh]);
    const handleRun = useCallback(async () => {
        setRunning(true);
        setRunStatus('Running immune loop...');
        try {
            const r = await runLoop(difficulty, 30);
            setRunStatus(`loop ${r.loop_id.slice(0, 18)} - posture=${r.aggregate_posture} - ` +
                `${r.alert_count} alerts - ${r.case_count} cases - ${r.new_memory_count} new memories`);
            await refresh();
        }
        catch (e) {
            setRunStatus(`Error: ${e.message}`);
        }
        finally {
            setRunning(false);
        }
    }, [difficulty, refresh]);
    const decisionByCase = useMemo(() => {
        const map = new Map();
        for (const d of state?.loop?.decisions ?? [])
            map.set(d.case_id, d);
        return map;
    }, [state]);
    const redTeamWon = Boolean(state?.loop?.proposal && state.loop.case_count === 0);
    return (_jsxs("div", { className: "shell", children: [_jsx(Header, { llm: llm }), _jsx(RealityCallout, {}), _jsxs("div", { className: "row", style: { marginTop: 14, marginBottom: 18 }, children: [_jsx("button", { className: "btn", onClick: handleRun, disabled: running, children: running ? 'Running...' : 'Run a new loop' }), _jsxs("select", { value: difficulty, onChange: (e) => setDifficulty(e.target.value), disabled: running, children: [_jsx("option", { value: "easy", children: "easy (detector wins)" }), _jsx("option", { value: "medium", children: "medium" }), _jsx("option", { value: "hard", children: "hard (red team wins)" })] }), _jsx("span", { className: "muted", style: { fontSize: 12 }, children: runStatus })] }), error && _jsxs("div", { className: "empty error", children: ["Could not load: ", error] }), state?.loop ? (_jsxs(_Fragment, { children: [_jsx(LoopStrip, { runs: state.loop.agent_runs }), _jsxs("div", { className: "kpi-grid", children: [_jsx(Kpi, { value: state.loop.alert_count, label: "Sentinel alerts" }), _jsx(Kpi, { value: state.loop.case_count, label: "Investigation cases", cls: "amber" }), _jsx(Kpi, { value: state.loop.new_memory_count, label: "New memories", cls: "blue" }), _jsx(Kpi, { value: state.loop.aggregate_posture, label: "Aggregate posture", cls: "green", small: true })] }), state.promotion && _jsx(PromotionPanel, { promotion: state.promotion }), _jsxs("div", { className: "grid-2", children: [_jsxs("div", { children: [state.loop.proposal && (_jsxs("div", { className: "panel blue", children: [_jsxs("div", { className: "row", children: [_jsxs("h2", { style: { margin: 0 }, children: ["Red-Team Proposal - ", state.loop.proposal.name] }), _jsx("div", { className: "spacer" }), _jsx("span", { className: `pill ${state.loop.proposal.rationale_source === 'llm' ? 'blue' : 'muted'}`, children: state.loop.proposal.rationale_source === 'llm'
                                                            ? 'Narrative rationale'
                                                            : 'deterministic' })] }), _jsx("p", { className: "muted", children: state.loop.proposal.rationale }), _jsxs("div", { className: "row", children: [_jsx("span", { className: "pill blue", children: state.loop.proposal.base_scenario }), state.loop.proposal.cover_scenario && (_jsxs("span", { className: "pill amber", children: ["cover: ", state.loop.proposal.cover_scenario] })), _jsx("span", { className: "pill muted", children: state.loop.proposal.difficulty })] }), _jsxs("p", { className: "mono muted", style: { marginTop: 8 }, children: ["Evasion: ", state.loop.proposal.evasion_strategy] })] })), redTeamWon && state.loop.proposal && (_jsx(RedTeamOutcome, { proposal: state.loop.proposal })), _jsxs("h2", { children: ["Investigation cases (", state.loop.cases.length, ")"] }), state.loop.cases.length === 0 ? (_jsx("div", { className: "empty", children: "No cases for this loop. Try easy difficulty to watch the detector win." })) : (state.loop.cases.map((c) => (_jsx(InvestigationCaseCard, { caseFile: c, decision: decisionByCase.get(c.case_id) }, c.case_id))))] }), _jsxs("div", { children: [_jsxs("h2", { children: ["Immune memory shelf (", state.memories.length, ")"] }), _jsx(MemoryShelf, { memories: state.memories }), _jsx("h2", { style: { marginTop: 18 }, children: "Recent loops" }), state.recent_loops.map((l) => (_jsxs("div", { className: "recent-row", children: [_jsx("span", { className: "mono", children: l.loop_id.slice(0, 18) }), _jsx("span", { className: `pill ${l.aggregate_posture.includes('block')
                                                    ? 'red'
                                                    : l.aggregate_posture.includes('alert')
                                                        ? 'amber'
                                                        : 'blue'}`, children: l.aggregate_posture })] }, l.loop_id)))] })] })] })) : (!error && _jsx("div", { className: "empty", children: "No loops persisted yet. Click Run a new loop." }))] }));
}
function RealityCallout() {
    return (_jsxs("section", { className: "reality-callout", "aria-labelledby": "reality-title", children: [_jsxs("div", { children: [_jsx("div", { className: "eyebrow", children: "Real vs simulated" }), _jsx("h2", { id: "reality-title", children: "Demo boundary is explicit" })] }), _jsxs("div", { className: "reality-grid", children: [_jsxs("div", { children: [_jsx("strong", { children: "Real" }), _jsx("p", { children: "Binance market-data background, Django persistence, React + TypeScript UI, REST API contracts, trained risk-head artifacts, and persisted agent traces." })] }), _jsxs("div", { children: [_jsx("strong", { children: "Simulated" }), _jsx("p", { children: "Adversarial order behavior, red-team scenarios, policy outcomes, and memory updates generated by the local immune-loop services for recruiter-safe demos." })] })] })] }));
}
function RedTeamOutcome({ proposal, }) {
    return (_jsxs("div", { className: "panel red outcome-panel", children: [_jsxs("div", { className: "row", children: [_jsx("h2", { style: { margin: 0 }, children: "Red Team won this round" }), _jsx("div", { className: "spacer" }), _jsx("span", { className: "pill red", children: "no cases opened" })] }), _jsx("p", { className: "muted", children: "The detector saw the proposal but opened zero investigation cases. That is the adversarial-agent failure mode the loop is designed to capture, remember, and train against on the next iteration." }), _jsxs("p", { className: "mono muted", children: ["Scenario: ", proposal.name, " / ", proposal.difficulty] })] }));
}
function Header({ llm }) {
    return (_jsxs("header", { children: [_jsxs("nav", { className: "top-nav", "aria-label": "Primary", children: [_jsx("a", { className: "brand-link", href: "/dashboard/agentic/v2/", children: "MarketImmune" }), _jsxs("div", { className: "nav-links", children: [_jsx("a", { "aria-current": "page", href: "/dashboard/agentic/v2/", children: "Immune Loop V2" }), _jsx("a", { href: "/dashboard/agentic/v2/simulator/", children: "Simulator" }), _jsx("a", { href: "/simulator/risk/", children: "Risk" }), _jsx("a", { href: "/simulator/data/", children: "Data" }), _jsx("a", { href: "/simulator/audit/", children: "Audit" }), _jsx("a", { href: "/dashboard/agentic/", children: "Classic Loop" })] })] }), _jsx("div", { className: "eyebrow", children: "Market defense console" }), _jsx("h1", { children: "Immune Loop V2" }), _jsxs("p", { className: "muted", style: { maxWidth: 880 }, children: ["A clean control surface for the red-team simulation, detector output, investigation cases, memory shelf, and promotion verdicts persisted in Django via", ' ', _jsx("code", { children: "/api/agentic/state/" }), "."] }), _jsx("div", { className: "row", style: { marginTop: 8 }, children: _jsx("span", { className: `pill ${llm?.enabled ? 'blue' : 'muted'}`, children: llm?.enabled
                        ? 'Narrative engine: enabled'
                        : 'Narrative engine: deterministic' }) })] }));
}
function Kpi({ value, label, cls, small }) {
    return (_jsxs("div", { className: `kpi ${cls ?? ''}`, children: [_jsx("strong", { style: small ? { fontSize: 16 } : undefined, children: value }), _jsx("span", { children: label })] }));
}
