import { useMemo, useState } from 'react';
import { Empty, Panel } from '../components/Panel';
import DecryptedText from '../components/reactbits/DecryptedText';
import { useDjango } from '../data/django';
import { clockTime, durationMs, percent } from '../lib/format';

interface AuditEvent {
    id: string;
    at: string;
    agent: string;
    kind: 'Tool call' | 'Decision';
    summary: string;
    detail: string;
    metric: string;
    payload: Record<string, unknown>;
}

export default function AuditPage() {
    const api = useDjango();
    const view = api.loopView;
    const [selected, setSelected] = useState<string | null>(null);

    const events = useMemo<AuditEvent[]>(() => {
        const runs = view?.state.loop?.agent_runs ?? [];
        return runs
            .flatMap((run) => [
                ...run.tool_calls.map((call, i) => ({
                    id: `${run.run_id}/tool/${i}`,
                    at: call.occurred_at,
                    agent: run.agent_name,
                    kind: 'Tool call' as const,
                    summary: call.tool,
                    detail: call.result_summary,
                    metric: durationMs(call.duration_ms),
                    payload: call.arguments,
                })),
                ...run.decision_traces.map((trace, i) => ({
                    id: `${run.run_id}/decision/${i}`,
                    at: trace.occurred_at,
                    agent: run.agent_name,
                    kind: 'Decision' as const,
                    summary: trace.decision,
                    detail: trace.observation,
                    metric: percent(trace.confidence, 0),
                    payload: trace.evidence,
                })),
            ])
            .sort((a, b) => a.at.localeCompare(b.at));
    }, [view]);

    const active = events.find((event) => event.id === selected) ?? null;

    if (!view) {
        return (
            <div className="report">
                <header className="report-head">
                    <h1>Decision audit trail</h1>
                    <p className="muted">Every agent tool call and decision, in the order it happened.</p>
                </header>
                <Panel>
                    <Empty title={api.status === 'online' ? 'Nothing recorded yet' : 'The Django API is not running'}>
                        <button type="button" className="button-quiet" onClick={() => api.requestSample(true)}>
                            Show a sample run
                        </button>
                    </Empty>
                </Panel>
            </div>
        );
    }

    return (
        <div className="report">
            <header className="report-head with-actions">
                <div>
                    <h1>Decision audit trail</h1>
                    <p className="muted">
                        Loop <code>{view.state.loop?.loop_id}</code>. Records are append-only; select one to see its
                        arguments or evidence.
                    </p>
                </div>
                <span className={`chip ${view.source === 'api' ? 'chip-live' : 'chip-warn'}`}>
                    {view.source === 'api' ? 'From the Django API' : 'Sample run, not live output'}
                </span>
            </header>
            <div className="audit-layout">
                <Panel className="audit-list">
                    <table className="grid-table selectable">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Agent</th>
                                <th>Kind</th>
                                <th>Record</th>
                                <th className="num">Duration / confidence</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events.map((event) => (
                                <tr
                                    key={event.id}
                                    aria-selected={event.id === selected}
                                    tabIndex={0}
                                    onClick={() => setSelected(event.id)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' || e.key === ' ') {
                                            e.preventDefault();
                                            setSelected(event.id);
                                        }
                                    }}
                                >
                                    <td className="num muted">{clockTime(Date.parse(event.at))}</td>
                                    <td>{event.agent}</td>
                                    <td className={event.kind === 'Decision' ? 'warn' : 'muted'}>{event.kind}</td>
                                    <td className="truncate">
                                        <span>{event.summary}</span>
                                        <span className="faint"> {event.detail}</span>
                                    </td>
                                    <td className="num">{event.metric}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </Panel>
                <Panel className="audit-detail" title="Record">
                    {active ? (
                        <div className="record">
                            <p className="record-id">
                                <DecryptedText key={active.id} text={active.id} animateOn="view" speed={18} maxIterations={8} sequential revealDirection="start" />
                            </p>
                            <dl className="kv">
                                <dt>Agent</dt><dd>{active.agent}</dd>
                                <dt>Kind</dt><dd>{active.kind}</dd>
                                <dt>At</dt><dd className="num">{active.at}</dd>
                                <dt>Record</dt><dd>{active.summary}</dd>
                                <dt>Detail</dt><dd>{active.detail}</dd>
                            </dl>
                            <pre className="payload">{JSON.stringify(active.payload, null, 2)}</pre>
                        </div>
                    ) : (
                        <Empty title="Select a record" />
                    )}
                </Panel>
            </div>
        </div>
    );
}
