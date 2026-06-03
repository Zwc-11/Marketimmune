import { useState } from 'react';
import type { AgentRunSummary } from '../types';
import type { Tone } from '../routes';
import { BrandMark, Icon, iconForAgent } from './Icon';
import { DataPanel, EmptyState, KeyValueList, MiniMetric, StatusBadge } from './ui';
import { SlidingTabs } from './motion/SlidingTabs';
import { formatClock, formatDuration, formatNumber } from '../lib/format';

type AgentTab = 'overview' | 'output' | 'tools' | 'telemetry' | 'logs';

export function AgentOrchestrator({
    agents,
    activeName,
    running,
}: {
    agents: AgentRunSummary[];
    activeName: string;
    running: boolean;
}) {
    if (!agents.length) {
        return (
            <div className="agent-orchestrator empty">
                <EmptyState
                    title="No agent runs"
                    body="Run the immune loop to persist agent execution nodes."
                />
            </div>
        );
    }
    return (
        <div className="agent-orchestrator">
            <svg viewBox="0 0 850 610" aria-hidden="true">
                <path
                    className="agent-orbit"
                    d="M 425 78 C 668 78 770 235 688 420 C 610 595 250 595 162 420 C 70 238 182 78 425 78"
                />
                <path
                    className="agent-orbit active"
                    d="M 425 78 C 668 78 770 235 688 420 C 610 595 250 595 162 420 C 70 238 182 78 425 78"
                />
                <polygon
                    className="orchestrator-hex"
                    points="425,210 515,262 515,365 425,418 335,365 335,262"
                />
            </svg>
            <div className="orchestrator-core">
                <BrandMark />
                <strong>IMMUNE LOOP</strong>
                <span>Orchestrator</span>
                <StatusBadge tone="green">{running ? 'Running' : 'Completed'}</StatusBadge>
            </div>
            {agents.slice(0, 8).map((agent, index) => (
                <AgentNode
                    key={`${agent.agent_name}-${index}`}
                    agent={agent}
                    index={index}
                    active={agent.agent_name === activeName}
                />
            ))}
        </div>
    );
}

function AgentNode({
    agent,
    index,
    active,
}: {
    agent: AgentRunSummary;
    index: number;
    active: boolean;
}) {
    const queued = index >= 6;
    const status = active ? 'Running' : queued ? 'Queued' : agent.success ? 'Completed' : 'Failed';
    const tone: Tone = status === 'Queued' ? 'amber' : status === 'Failed' ? 'red' : 'green';
    return (
        <div className={`agent-node node-${index} ${active ? 'active' : ''}`}>
            <div className="agent-node-title">
                <Icon name={iconForAgent(agent.agent_name)} />
                <strong>
                    {index + 1}. {agent.agent_name}
                </strong>
                <Icon name="more" />
            </div>
            <StatusBadge tone={tone}>{status}</StatusBadge>
            <KeyValueList
                rows={[
                    ['Latency', queued ? '-' : formatDuration(agent.duration_ms)],
                    ['Success', queued ? '-' : agent.success ? '100%' : '0%'],
                ]}
            />
        </div>
    );
}

export function AgentDetailPanel({
    agent,
    running,
}: {
    agent: AgentRunSummary | undefined;
    running: boolean;
}) {
    const traces = agent?.decision_traces ?? [];
    const tools = agent?.tool_calls ?? [];
    const [tab, setTab] = useState<AgentTab>('overview');
    const tabs: Array<{ id: AgentTab; label: string }> = [
        { id: 'overview', label: 'Overview' },
        { id: 'output', label: 'Output' },
        { id: 'tools', label: 'Tool Calls' },
        { id: 'telemetry', label: 'Telemetry' },
        { id: 'logs', label: 'Logs' },
    ];
    return (
        <DataPanel className="agent-detail">
            <div className="detail-heading">
                <h3>{agent ? agent.agent_name : 'Agent Detail'}</h3>
                <StatusBadge tone="green">{running ? 'Running' : 'Completed'}</StatusBadge>
                <Icon name="close" />
            </div>
            <SlidingTabs tabs={tabs} value={tab} onChange={setTab} />
            {tab === 'overview' && (
                <div className="t-reveal">
                    <h4>Latest Output Summary</h4>
                    <p>
                        {traces[0]?.observation ?? agent?.goal ?? 'No persisted trace for this agent.'}
                    </p>
                    <div className="detail-stats">
                        <MiniMetric label="Findings" value={formatNumber(traces.length)} helper="traces" />
                        <MiniMetric
                            label="Critical"
                            value={String(tools.length > 0 ? 3 : 0)}
                            helper="signals"
                        />
                        <MiniMetric
                            label="Evidence Items"
                            value={formatNumber(tools.length + traces.length)}
                            helper="items"
                        />
                        <MiniMetric label="Cases Opened" value={String(tools.length)} helper="linked" />
                    </div>
                </div>
            )}
            {tab === 'tools' && (
                <div className="t-reveal">
                    <div className="trace-heading">
                        <strong>Tool Calls Trace</strong>
                        <span>{tools.length} calls</span>
                    </div>
                    <div className="tool-call-list">
                        {tools.length ? (
                            tools.slice(0, 6).map((tool, index) => (
                                <div key={`${tool.tool}-${index}`}>
                                    <Icon name={index < 5 ? 'check' : 'clock'} />
                                    <div>
                                        <strong>{tool.tool}</strong>
                                        <span>
                                            {tool.result_summary || 'No summary persisted'} ·{' '}
                                            {formatDuration(tool.duration_ms)}
                                        </span>
                                    </div>
                                </div>
                            ))
                        ) : (
                            <EmptyState
                                title="No tool calls"
                                body="This agent run did not persist tool-call records."
                            />
                        )}
                    </div>
                </div>
            )}
            {(tab === 'telemetry' || tab === 'logs' || tab === 'output') && (
                <div className="t-reveal">
                    <h4>Agent Stats</h4>
                    <div className="detail-stats">
                        <MiniMetric label="Started" value={formatClock(agent?.started_at)} helper="UTC" />
                        <MiniMetric
                            label="Elapsed"
                            value={formatDuration(agent?.duration_ms ?? 0)}
                            helper="duration"
                        />
                        <MiniMetric
                            label="Latency (p95)"
                            value={formatDuration(agent?.duration_ms ?? 0)}
                            helper="trace"
                        />
                        <MiniMetric label="Success" value={agent?.success ? '100%' : '-'} helper="rate" />
                    </div>
                    {tab === 'output' && (
                        <p style={{ marginTop: 16 }}>
                            {agent?.output && Object.keys(agent.output).length > 0
                                ? JSON.stringify(agent.output, null, 2)
                                : traces[0]?.observation ?? 'No output persisted.'}
                        </p>
                    )}
                </div>
            )}
        </DataPanel>
    );
}
