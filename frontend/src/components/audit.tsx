import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import type { AuditRow } from '../lib/derive';
import { toneForDecision, toneTextClass } from '../lib/derive';
import { Icon } from './Icon';
import { EmptyState, StatusBadge } from './ui';

export function AuditTreeView({ rows }: { rows: AuditRow[] }) {
    const [selected, setSelected] = useState(0);
    if (!rows.length) {
        return (
            <EmptyState
                title="No trace tree"
                body="No persisted audit rows are available for the current filter."
            />
        );
    }
    return (
        <div className="audit-tree" role="listbox" aria-label="Audit trace nodes">
            {rows.map((row, index) => (
                <button
                    key={`${row.agent}-${index}`}
                    type="button"
                    className={`audit-tree-node ${selected === index ? 'active' : ''}`}
                    role="option"
                    aria-selected={selected === index}
                    onClick={() => setSelected(index)}
                >
                    <span>{index + 1}</span>
                    <strong>{row.agent}</strong>
                    <em>{row.title}</em>
                    <StatusBadge tone={toneForDecision(row.decision)}>
                        {row.decision}
                    </StatusBadge>
                </button>
            ))}
        </div>
    );
}

export function TraceCard({
    row,
    index,
    forceOpen = false,
}: {
    row: AuditRow;
    index: number;
    forceOpen?: boolean;
}) {
    const [open, setOpen] = useState(false);
    useEffect(() => {
        setOpen(forceOpen);
    }, [forceOpen]);
    return (
        <div
            className={`trace-card ${open ? 'open' : ''}`}
            style={{ '--delay': `${index * 70}ms` } as CSSProperties}
        >
            <div className="trace-index">
                <span>{index + 1}</span>
            </div>
            <div className="trace-time">
                <time>{row.time}</time>
                <strong>Agent: {row.agent}</strong>
                <span>{row.step}</span>
            </div>
            <button
                className="trace-main"
                type="button"
                aria-expanded={open}
                aria-controls={`trace-panel-${index}`}
                onClick={() => setOpen((value) => !value)}
            >
                <strong>{row.title}</strong>
                <StatusBadge tone="green">Tool Calls ({row.tools})</StatusBadge>
            </button>
            <div className="trace-field">
                <span>Policy Decision</span>
                <strong className={toneTextClass(toneForDecision(row.decision))}>
                    {row.decision}
                </strong>
            </div>
            <div className="trace-field">
                <span>Recommended Control</span>
                <strong>{row.control}</strong>
            </div>
            <div className="trace-field">
                <span>Confidence</span>
                <strong>
                    {row.confidence.toFixed(2)} <span className="status-dot green" />
                </strong>
            </div>
            <div className="trace-field">
                <span>Linked Artifacts</span>
                <strong>
                    <Icon name="file" /> {row.artifacts}
                </strong>
            </div>
            <Icon name="chevron" />
            <div
                className={`trace-expanded ${open ? 'open' : ''}`}
                id={`trace-panel-${index}`}
                hidden={!open}
            >
                <div className="t-panel-slide t-reveal" data-open={open ? 'true' : 'false'}>
                <div className="trace-obs">
                    <span className="trace-label">Observation</span>
                    <p>{row.observation}</p>
                </div>
                <div className="trace-meta-row">
                    <span>
                        <em>Run</em> <span className="mono">{row.runId}</span>
                    </span>
                    <span>
                        <em>Duration</em>{' '}
                        <span className="mono">{(row.durationMs / 1000).toFixed(2)}s</span>
                    </span>
                </div>
                {row.toolCalls.length > 0 && (
                    <ol className="trace-tools">
                        {row.toolCalls.map((call, callIndex) => (
                            <li key={`${call.tool}-${callIndex}`} className="trace-tool">
                                <span className="trace-tool-index mono">
                                    {String(callIndex + 1).padStart(2, '0')}
                                </span>
                                <code className="trace-tool-name">{call.tool}</code>
                                <span className="trace-tool-summary">{call.result_summary}</span>
                                <span className="trace-tool-ms mono">{call.duration_ms}ms</span>
                            </li>
                        ))}
                    </ol>
                )}
                {row.artifactEntries.length > 0 && (
                    <div className="trace-artifacts">
                        <span className="trace-label">Linked artifacts</span>
                        <div className="trace-artifact-tags">
                            {row.artifactEntries.map(([key, value]) => (
                                <span key={key} className="trace-artifact-tag">
                                    <em>{key}</em>
                                    <span className="mono">{value}</span>
                                </span>
                            ))}
                        </div>
                    </div>
                )}
                </div>
            </div>
        </div>
    );
}
