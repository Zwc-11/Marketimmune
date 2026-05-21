import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchLLMStatus, fetchState, runLoop } from './api';
import type { LLMStatus, LoopState } from './types';
import { LoopStrip } from './components/LoopStrip';
import { InvestigationCaseCard } from './components/InvestigationCaseCard';
import { PromotionPanel } from './components/PromotionPanel';
import { MemoryShelf } from './components/MemoryShelf';
import { SimulatorView } from './components/SimulatorView';

type Difficulty = 'easy' | 'medium' | 'hard';

export function App() {
    if (window.location.pathname.startsWith('/dashboard/agentic/v2/simulator/')) {
        return <SimulatorView />;
    }
    return <ImmuneLoopApp />;
}

function ImmuneLoopApp() {
    const [state, setState] = useState<LoopState | null>(null);
    const [llm, setLlm] = useState<LLMStatus | null>(null);
    const [error, setError] = useState<string>('');
    const [running, setRunning] = useState(false);
    const [runStatus, setRunStatus] = useState<string>('');
    const [difficulty, setDifficulty] = useState<Difficulty>('easy');

    const refresh = useCallback(async () => {
        try {
            const [s, l] = await Promise.all([fetchState(), fetchLLMStatus()]);
            setState(s);
            setLlm(l);
            setError('');
        } catch (e) {
            setError((e as Error).message);
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
            setRunStatus(
                `loop ${r.loop_id.slice(0, 18)} - posture=${r.aggregate_posture} - ` +
                    `${r.alert_count} alerts - ${r.case_count} cases - ${r.new_memory_count} new memories`,
            );
            await refresh();
        } catch (e) {
            setRunStatus(`Error: ${(e as Error).message}`);
        } finally {
            setRunning(false);
        }
    }, [difficulty, refresh]);

    const decisionByCase = useMemo(() => {
        const map = new Map<string, NonNullable<LoopState['loop']>['decisions'][number]>();
        for (const d of state?.loop?.decisions ?? []) map.set(d.case_id, d);
        return map;
    }, [state]);

    const redTeamWon = Boolean(
        state?.loop?.proposal && state.loop.case_count === 0,
    );

    return (
        <div className="shell">
            <Header llm={llm} />
            <RealityCallout />

            <div className="row" style={{ marginTop: 14, marginBottom: 18 }}>
                <button className="btn" onClick={handleRun} disabled={running}>
                    {running ? 'Running...' : 'Run a new loop'}
                </button>
                <select
                    value={difficulty}
                    onChange={(e) => setDifficulty(e.target.value as Difficulty)}
                    disabled={running}
                >
                    <option value="easy">easy (detector wins)</option>
                    <option value="medium">medium</option>
                    <option value="hard">hard (red team wins)</option>
                </select>
                <span className="muted" style={{ fontSize: 12 }}>{runStatus}</span>
            </div>

            {error && <div className="empty error">Could not load: {error}</div>}

            {state?.loop ? (
                <>
                    <LoopStrip runs={state.loop.agent_runs} />

                    <div className="kpi-grid">
                        <Kpi value={state.loop.alert_count} label="Sentinel alerts" />
                        <Kpi value={state.loop.case_count} label="Investigation cases" cls="amber" />
                        <Kpi value={state.loop.new_memory_count} label="New memories" cls="blue" />
                        <Kpi value={state.loop.aggregate_posture} label="Aggregate posture" cls="green" small />
                    </div>

                    {state.promotion && <PromotionPanel promotion={state.promotion} />}

                    <div className="grid-2">
                        <div>
                            {state.loop.proposal && (
                                <div className="panel blue">
                                    <div className="row">
                                        <h2 style={{ margin: 0 }}>
                                            Red-Team Proposal - {state.loop.proposal.name}
                                        </h2>
                                        <div className="spacer" />
                                        <span
                                            className={`pill ${state.loop.proposal.rationale_source === 'llm' ? 'blue' : 'muted'}`}
                                        >
                                            {state.loop.proposal.rationale_source === 'llm'
                                                ? 'Narrative rationale'
                                                : 'deterministic'}
                                        </span>
                                    </div>
                                    <p className="muted">{state.loop.proposal.rationale}</p>
                                    <div className="row">
                                        <span className="pill blue">{state.loop.proposal.base_scenario}</span>
                                        {state.loop.proposal.cover_scenario && (
                                            <span className="pill amber">
                                                cover: {state.loop.proposal.cover_scenario}
                                            </span>
                                        )}
                                        <span className="pill muted">{state.loop.proposal.difficulty}</span>
                                    </div>
                                    <p className="mono muted" style={{ marginTop: 8 }}>
                                        Evasion: {state.loop.proposal.evasion_strategy}
                                    </p>
                                </div>
                            )}

                            {redTeamWon && state.loop.proposal && (
                                <RedTeamOutcome proposal={state.loop.proposal} />
                            )}

                            <h2>Investigation cases ({state.loop.cases.length})</h2>
                            {state.loop.cases.length === 0 ? (
                                <div className="empty">
                                    No cases for this loop. Try easy difficulty to watch the detector win.
                                </div>
                            ) : (
                                state.loop.cases.map((c) => (
                                    <InvestigationCaseCard
                                        key={c.case_id}
                                        caseFile={c}
                                        decision={decisionByCase.get(c.case_id)}
                                    />
                                ))
                            )}
                        </div>

                        <div>
                            <h2>Immune memory shelf ({state.memories.length})</h2>
                            <MemoryShelf memories={state.memories} />

                            <h2 style={{ marginTop: 18 }}>Recent loops</h2>
                            {state.recent_loops.map((l) => (
                                <div className="recent-row" key={l.loop_id}>
                                    <span className="mono">{l.loop_id.slice(0, 18)}</span>
                                    <span
                                        className={`pill ${
                                            l.aggregate_posture.includes('block')
                                                ? 'red'
                                                : l.aggregate_posture.includes('alert')
                                                ? 'amber'
                                                : 'blue'
                                        }`}
                                    >
                                        {l.aggregate_posture}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </>
            ) : (
                !error && <div className="empty">No loops persisted yet. Click Run a new loop.</div>
            )}
        </div>
    );
}

function RealityCallout() {
    return (
        <section className="reality-callout" aria-labelledby="reality-title">
            <div>
            <div className="eyebrow">Real vs simulated</div>
                <h2 id="reality-title">Demo boundary is explicit</h2>
            </div>
            <div className="reality-grid">
                <div>
                    <strong>Real</strong>
                    <p>
                        Binance market-data background, Django persistence, React + TypeScript UI,
                        REST API contracts, trained risk-head artifacts, and persisted agent traces.
                    </p>
                </div>
                <div>
                    <strong>Simulated</strong>
                    <p>
                        Adversarial order behavior, red-team scenarios, policy outcomes, and memory
                        updates generated by the local immune-loop services for recruiter-safe demos.
                    </p>
                </div>
            </div>
        </section>
    );
}

function RedTeamOutcome({
    proposal,
}: {
    proposal: NonNullable<NonNullable<LoopState['loop']>['proposal']>;
}) {
    return (
        <div className="panel red outcome-panel">
            <div className="row">
                <h2 style={{ margin: 0 }}>Red Team won this round</h2>
                <div className="spacer" />
                <span className="pill red">no cases opened</span>
            </div>
            <p className="muted">
                The detector saw the proposal but opened zero investigation cases. That is the
                adversarial-agent failure mode the loop is designed to capture, remember, and train
                against on the next iteration.
            </p>
            <p className="mono muted">Scenario: {proposal.name} / {proposal.difficulty}</p>
        </div>
    );
}

function Header({ llm }: { llm: LLMStatus | null }) {
    return (
        <header>
            <nav className="top-nav" aria-label="Primary">
                <a className="brand-link" href="/dashboard/agentic/v2/">
                    MarketImmune
                </a>
                <div className="nav-links">
                    <a aria-current="page" href="/dashboard/agentic/v2/">
                        Immune Loop V2
                    </a>
                    <a href="/dashboard/agentic/v2/simulator/">Simulator</a>
                    <a href="/simulator/risk/">Risk</a>
                    <a href="/simulator/data/">Data</a>
                    <a href="/simulator/audit/">Audit</a>
                    <a href="/dashboard/agentic/">Classic Loop</a>
                </div>
            </nav>
            <div className="eyebrow">Market defense console</div>
            <h1>Immune Loop V2</h1>
            <p className="muted" style={{ maxWidth: 880 }}>
                A clean control surface for the red-team simulation, detector output, investigation cases,
                memory shelf, and promotion verdicts persisted in Django via{' '}
                <code>/api/agentic/state/</code>.
            </p>
            <div className="row" style={{ marginTop: 8 }}>
                <span className={`pill ${llm?.enabled ? 'blue' : 'muted'}`}>
                    {llm?.enabled
                        ? 'Narrative engine: enabled'
                        : 'Narrative engine: deterministic'}
                </span>
            </div>
        </header>
    );
}

interface KpiProps {
    value: string | number;
    label: string;
    cls?: string;
    small?: boolean;
}

function Kpi({ value, label, cls, small }: KpiProps) {
    return (
        <div className={`kpi ${cls ?? ''}`}>
            <strong style={small ? { fontSize: 16 } : undefined}>{value}</strong>
            <span>{label}</span>
        </div>
    );
}
