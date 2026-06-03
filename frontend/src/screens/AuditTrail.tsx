import { useState } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    EmptyState,
    KeyValueList,
    LoadingState,
    PageHeader,
    StatusLine,
} from '../components/ui';
import { AuditTreeView, TraceCard } from '../components/audit';
import { auditRowsFrom, exportTrace, shareCurrentLink } from '../lib/derive';
import { formatDuration, formatTimestamp, sentenceCase, shortId } from '../lib/format';

export function AuditTrailScreen({ data, loading }: { data: ProductData; loading: boolean }) {
    const loop = data.loopState?.loop ?? null;
    const auditRows = auditRowsFrom(loop ?? null);
    const [query, setQuery] = useState('');
    const [expandAll, setExpandAll] = useState(false);
    const [notice, setNotice] = useState('');
    const [auditView, setAuditView] = useState<'timeline' | 'tree'>('timeline');
    const filteredRows = auditRows.filter((row) =>
        `${row.agent} ${row.title} ${row.decision} ${row.control}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
    );

    if (loading && !loop) return <LoadingState label="Loading audit trail" />;

    return (
        <section className="screen-stack">
            <PageHeader
                title="Decision Audit Trail"
                subtitle="Full traceability of Immune Loop decisions and agent actions"
                right={
                    <>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => exportTrace(loop, auditRows, setNotice)}
                        >
                            <Icon name="download" /> Export Trace
                        </button>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => shareCurrentLink(setNotice)}
                        >
                            <Icon name="link" /> Share Link
                        </button>
                    </>
                }
            />
            <DataPanel className="audit-meta">
                <KeyValueList
                    rows={[
                        ['Loop ID', shortId(loop?.loop_id)],
                        ['Agent Run ID', shortId(loop?.agent_runs[0]?.run_id)],
                        ['Loop Type', 'Immune Loop'],
                        [
                            'Scenario',
                            sentenceCase(loop?.proposal?.name ?? loop?.proposal_name ?? 'unknown'),
                        ],
                        ['Started', formatTimestamp(loop?.started_at)],
                        ['Status', loop ? 'Completed' : 'No data'],
                        [
                            'Duration',
                            loop ? formatDuration(loop.duration_ms) : '-',
                        ],
                        ['Posture', sentenceCase(loop?.aggregate_posture ?? '-')],
                    ]}
                />
            </DataPanel>
            <DataPanel className="audit-panel">
                <div className="audit-toolbar">
                    <div className="tabs">
                        <button
                            className={auditView === 'timeline' ? 'active' : ''}
                            type="button"
                            onClick={() => setAuditView('timeline')}
                        >
                            Timeline View
                        </button>
                        <button
                            className={auditView === 'tree' ? 'active' : ''}
                            type="button"
                            onClick={() => setAuditView('tree')}
                        >
                            Tree View
                        </button>
                    </div>
                    <div className="toolbar-actions">
                        <label className="search-box">
                            <Icon name="search" />{' '}
                            <input
                                value={query}
                                onChange={(event) => setQuery(event.target.value)}
                                placeholder="Search in trace..."
                            />
                        </label>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => setQuery('')}
                        >
                            <Icon name="filter" /> Clear
                        </button>
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => setExpandAll((value) => !value)}
                        >
                            <Icon name="expand" /> {expandAll ? 'Collapse All' : 'Expand All'}
                        </button>
                    </div>
                </div>
                <div className="audit-timeline">
                    {auditView === 'tree' ? (
                        <AuditTreeView rows={filteredRows} />
                    ) : filteredRows.length ? (
                        filteredRows.map((row, index) => (
                            <TraceCard
                                key={`${row.agent}-${index}`}
                                row={row}
                                index={index}
                                forceOpen={expandAll}
                            />
                        ))
                    ) : (
                        <EmptyState
                            title="No trace rows"
                            body="No persisted audit trace rows match this filter."
                        />
                    )}
                </div>
                <div className="audit-summary">
                    <StatusLine icon="check" label="Loop Completed" tone="green" />
                    <span>{formatTimestamp(loop?.started_at)}</span>
                    <span>Total Duration: {formatDuration(loop?.duration_ms ?? 0)}</span>
                    <span>Total Steps: {filteredRows.length}</span>
                    <span>
                        Tools Called:{' '}
                        {loop?.agent_runs.reduce((sum, agent) => sum + agent.tool_call_count, 0) ??
                            0}
                    </span>
                    <span>Artifacts Generated: {loop?.case_count ?? 0}</span>
                    <a className="secondary-action" href="#/agentic">
                        View Loop Summary <Icon name="chevron" />
                    </a>
                </div>
            </DataPanel>
            {notice && <div className="run-message">{notice}</div>}
            <div className="audit-footer">
                <span>All timestamps in UTC</span>
                <span>
                    <Icon name="shield" /> Append-only event log · One row per agent run, tool call,
                    and decision trace
                </span>
                <span>Loop ID: {loop?.loop_id ?? '-'}</span>
            </div>
        </section>
    );
}
