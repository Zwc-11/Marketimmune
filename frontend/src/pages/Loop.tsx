import { Empty, Panel } from '../components/Panel';
import StatusMark from '../components/reactbits/StatusMark';
import { useDjango } from '../data/django';
import { durationMs, fixed, integer, percent } from '../lib/format';
import type { LoopState } from '../types';

function SourceBadge({ source }: { source: 'api' | 'sample' }) {
    return source === 'api' ? (
        <span className="chip chip-live">From the Django API</span>
    ) : (
        <span className="chip chip-warn">Sample run, not live output</span>
    );
}

function AgentRuns({ loop }: { loop: NonNullable<LoopState['loop']> }) {
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Status</th>
                    <th>Agent</th>
                    <th>Goal</th>
                    <th>Last tool result</th>
                    <th className="num">Tool calls</th>
                    <th className="num">Duration</th>
                </tr>
            </thead>
            <tbody>
                {loop.agent_runs.map((run) => (
                    <tr key={run.run_id}>
                        <td>
                            <span className="inline-status">
                                <StatusMark status={run.success ? 'done' : 'failed'} size={12} doneColor="var(--bid)" errorColor="var(--ask)" />
                                {run.success ? 'Done' : 'Failed'}
                            </span>
                        </td>
                        <td>{run.agent_name}</td>
                        <td className="muted">{run.goal}</td>
                        <td className="muted truncate">{run.error || run.tool_calls[run.tool_calls.length - 1]?.result_summary || '–'}</td>
                        <td className="num">{integer(run.tool_call_count)}</td>
                        <td className="num">{durationMs(run.duration_ms)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

function Cases({ loop }: { loop: NonNullable<LoopState['loop']> }) {
    if (!loop.cases.length) return <Empty title="This loop opened no investigation cases" />;
    return (
        <div className="cases">
            {loop.cases.map((item) => {
                const decision = loop.decisions.find((d) => d.case_id === item.case_id);
                return (
                    <article key={item.case_id} className="case">
                        <header className="case-head">
                            <span className={`severity sev-${item.severity}`}>{item.severity}</span>
                            <h3>{item.suspected_behavior}</h3>
                            <span className="num faint">{percent(item.confidence, 0)} confidence</span>
                        </header>
                        <p>{item.narrative || item.explanation}</p>
                        <dl className="evidence">
                            {Object.entries(item.feature_evidence).map(([name, value]) => (
                                <div key={name}>
                                    <dt><code>{name}</code></dt>
                                    <dd className="num">{fixed(value, 3)}</dd>
                                </div>
                            ))}
                        </dl>
                        <p className="case-next">
                            <span className="faint">Recommended </span>
                            {decision ? `${decision.recommended_action.replace(/_/g, ' ')}: ${decision.rationale}` : item.recommended_next_step}
                        </p>
                    </article>
                );
            })}
        </div>
    );
}

function Memories({ state }: { state: LoopState }) {
    if (!state.memories.length) return <Empty title="No immune memories yet" />;
    return (
        <table className="grid-table">
            <thead>
                <tr>
                    <th>Pattern</th>
                    <th>Key signals</th>
                    <th>Best detector</th>
                    <th className="num">Seen</th>
                    <th className="num">Novelty</th>
                </tr>
            </thead>
            <tbody>
                {state.memories.map((memory) => (
                    <tr key={memory.memory_id}>
                        <td title={memory.description}>{memory.threat_name}</td>
                        <td className="muted">{memory.key_signals.join(', ')}</td>
                        <td className="muted"><code>{memory.best_detector}</code></td>
                        <td className="num">{integer(memory.times_seen)}</td>
                        <td className="num">{fixed(memory.novelty_score, 2)}</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export default function LoopPage() {
    const api = useDjango();
    const view = api.loopView;

    return (
        <div className="report">
            <header className="report-head with-actions">
                <div>
                    <h1>Immune loop</h1>
                    <p className="muted">
                        Red-team, sentinel, investigator, policy, and memory agents run over replayed SOL
                        flow. Every tool call and decision is written to an append-only audit trail.
                    </p>
                </div>
                <div className="head-actions">
                    {view && <SourceBadge source={view.source} />}
                    <button
                        type="button"
                        className="button-primary"
                        onClick={() => void api.runLoop()}
                        disabled={api.status !== 'online' || api.running}
                        title={api.status === 'online' ? undefined : 'Needs the Django API'}
                    >
                        {api.running ? 'Running…' : 'Run loop'}
                    </button>
                </div>
            </header>
            {api.runMessage && <p className="notice">{api.runMessage}</p>}

            {!view ? (
                <Panel>
                    <Empty title={api.status === 'online' ? 'No loop has run yet' : 'The Django API is not running'}>
                        <p>
                            {api.status === 'online'
                                ? 'Run the loop to persist agent traces, cases, and memories.'
                                : <>Start it with <code>python manage.py runserver</code> to run and persist loops.</>}
                        </p>
                        <button type="button" className="button-quiet" onClick={() => api.requestSample(true)}>
                            Show a sample run
                        </button>
                    </Empty>
                </Panel>
            ) : (
                view.state.loop && (
                    <div className="report-grid">
                        <Panel className="span-2" title="Agent runs" actions={<span className="faint num">{durationMs(view.state.loop.duration_ms)} total</span>}>
                            <AgentRuns loop={view.state.loop} />
                        </Panel>
                        <Panel className="span-2" title={`Investigation cases (${view.state.loop.case_count})`}>
                            <Cases loop={view.state.loop} />
                        </Panel>
                        <Panel className="span-2" title="Immune memory">
                            <Memories state={view.state} />
                        </Panel>
                    </div>
                )
            )}
        </div>
    );
}
