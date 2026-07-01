import { useState } from 'react';
import type { CSSProperties } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    LegendItem,
    LoadingState,
    MetricBlock,
    PageHeader,
    StatusBadge,
} from '../components/ui';
import { ProgressBar } from '../components/charts';
import { AgentDetailPanel, AgentOrchestrator } from '../components/agent';
import { clamp, formatClock, formatDuration, shortCycle } from '../lib/format';

export function AgenticLoopScreen({
    data,
    loading,
    runningLoop,
    onRunLoop,
}: {
    data: ProductData;
    loading: boolean;
    runningLoop: boolean;
    onRunLoop: () => void;
}) {
    const loop = data.loopState?.loop ?? null;
    const agentRuns = loop?.agent_runs ?? [];
    const activeAgent = runningLoop
        ? agentRuns[3]
        : agentRuns.find((agent) => agent.agent_name.includes('Investigator')) ?? agentRuns[0];
    const totalTools = agentRuns.reduce((sum, agent) => sum + agent.tool_call_count, 0);
    const completedAgents = agentRuns.filter((agent) => agent.success).length;
    const successRate = agentRuns.length
        ? Math.round((completedAgents / agentRuns.length) * 100)
        : 0;
    const [loopPaused, setLoopPaused] = useState(false);
    const [canvasZoom, setCanvasZoom] = useState(1);
    const [canvasExpanded, setCanvasExpanded] = useState(false);

    if (loading && !loop) return <LoadingState label="Loading agent orchestration" />;

    return (
        <section className="agentic-page">
            <PageHeader
                title="Immune loop"
                subtitle="Agentic defense orchestration with persisted tool traces"
                right={
                    <>
                        <StatusBadge tone="steel">Cycle {shortCycle(loop?.loop_id)}</StatusBadge>
                        <span className="subtle">
                            {loop ? `Started ${formatClock(loop.started_at)}` : 'No persisted cycle'}
                        </span>
                        <a className="outline-action" href="#/audit">
                            <Icon name="trend" /> Audit Trace
                        </a>
                    </>
                }
            />
            <div className="agentic-layout">
                <DataPanel className="orchestrator-panel" title="Agent orchestration">
                    <div className="canvas-tools" role="toolbar" aria-label="Graph view controls">
                        <button
                            type="button"
                            title={canvasExpanded ? 'Collapse graph' : 'Expand graph'}
                            aria-label={canvasExpanded ? 'Collapse graph' : 'Expand graph'}
                            onClick={() => setCanvasExpanded((value) => !value)}
                        >
                            <Icon name="expand" />
                        </button>
                        <button
                            type="button"
                            title="Zoom in"
                            aria-label="Zoom in"
                            onClick={() =>
                                setCanvasZoom((value) => clamp(value + 0.08, 0.82, 1.18))
                            }
                        >
                            +
                        </button>
                        <button
                            type="button"
                            title="Zoom out"
                            aria-label="Zoom out"
                            onClick={() =>
                                setCanvasZoom((value) => clamp(value - 0.08, 0.82, 1.18))
                            }
                        >
                            −
                        </button>
                        <span className="canvas-zoom-label">{Math.round(canvasZoom * 100)}%</span>
                    </div>
                    <div
                        className={`orchestrator-viewport ${canvasExpanded ? 'expanded' : ''}`}
                        style={{ '--zoom': canvasZoom } as CSSProperties}
                    >
                        <AgentOrchestrator
                            agents={agentRuns}
                            activeName={activeAgent?.agent_name ?? ''}
                            running={runningLoop && !loopPaused}
                        />
                    </div>
                    <div className="legend-row">
                        <LegendItem tone="green" label="Completed" />
                        <LegendItem tone="green" hollow label="Running" />
                        <LegendItem tone="amber" label="Queued" />
                        <LegendItem tone="red" label="Failed" />
                        <LegendItem tone="steel" label="Idle" />
                    </div>
                </DataPanel>
                <AgentDetailPanel agent={activeAgent} running={runningLoop} />
            </div>
            <div className="agent-bottom-bar">
                <MetricBlock
                    icon="pulse"
                    label="Loop status"
                    value={runningLoop ? 'Running' : loop ? 'Completed' : 'Ready'}
                    helper={loop ? `${formatDuration(loop.duration_ms)} elapsed` : 'Run to persist agents'}
                    tone="green"
                />
                <div className="bottom-progress">
                    <span>Agent progress</span>
                    <ProgressBar
                        value={agentRuns.length ? (completedAgents / agentRuns.length) * 100 : 0}
                        tone="green"
                    />
                    <small>
                        {completedAgents} of {agentRuns.length} agents succeeded · {totalTools} tool
                        calls
                    </small>
                </div>
                <MetricBlock
                    icon="check"
                    label="Success rate"
                    value={`${successRate}%`}
                    helper={`${completedAgents} / ${agentRuns.length} agents`}
                    tone="green"
                />
                <button
                    className="secondary-action"
                    type="button"
                    onClick={() => setLoopPaused((value) => !value)}
                >
                    <Icon name={loopPaused ? 'play' : 'pause'} />{' '}
                    {loopPaused ? 'Resume Animation' : 'Pause Animation'}
                </button>
                <button
                    className="primary-action"
                    type="button"
                    onClick={onRunLoop}
                    disabled={runningLoop}
                >
                    <Icon name="play" /> {runningLoop ? 'Running Loop…' : 'Run Immune Loop'}
                </button>
            </div>
        </section>
    );
}
