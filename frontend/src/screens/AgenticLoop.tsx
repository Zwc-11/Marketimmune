import { useState } from 'react';
import type { CSSProperties } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    LegendItem,
    LoadingState,
    MetricCard,
    PageHeader,
    StatusBadge,
} from '../components/ui';
import { ProgressBar } from '../components/charts';
import { LazyImmuneCore as ImmuneCore } from '../components/three/LazyImmuneCore';
import { AgentDetailPanel, AgentOrchestrator } from '../components/agent';
import { formatClock, formatDuration } from '../lib/format';
import { clamp } from '../lib/derive';
import { shortCycle } from '../lib/format';

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
    const [loopPaused, setLoopPaused] = useState(false);
    const [canvasZoom, setCanvasZoom] = useState(1);
    const [canvasExpanded, setCanvasExpanded] = useState(false);
    const [showCanvasSettings, setShowCanvasSettings] = useState(false);

    if (loading && !loop) return <LoadingState label="Loading agent orchestration" />;

    return (
        <section className="agentic-page">
            <PageHeader
                title="Immune Loop"
                subtitle="Agentic defense orchestration in progress"
                right={
                    <>
                        <StatusBadge tone="steel">Cycle {shortCycle(loop?.loop_id)}</StatusBadge>
                        <span className="subtle">Started {formatClock(loop?.started_at)}</span>
                        <a className="outline-action" href="#/audit">
                            <Icon name="trend" /> View Loop Telemetry
                        </a>
                    </>
                }
            />
            <DataPanel className="agentic-hero">
                <ImmuneCore compact>
                    <div className="hero-overlay">
                        <div className="hero-readout tone-green">
                            <strong>{agentRuns.filter((a) => a.success).length}/{agentRuns.length}</strong>
                            <span>Agents Online · {totalTools} tools called</span>
                        </div>
                    </div>
                </ImmuneCore>
            </DataPanel>
            <div className="agentic-layout">
                <DataPanel className="orchestrator-panel">
                    <div className="canvas-tools">
                        <button
                            type="button"
                            aria-label="Toggle canvas size"
                            onClick={() => setCanvasExpanded((value) => !value)}
                        >
                            <Icon name="expand" />
                        </button>
                        <button
                            type="button"
                            aria-label="Zoom in"
                            onClick={() =>
                                setCanvasZoom((value) => clamp(value + 0.08, 0.82, 1.18))
                            }
                        >
                            +
                        </button>
                        <button
                            type="button"
                            aria-label="Zoom out"
                            onClick={() =>
                                setCanvasZoom((value) => clamp(value - 0.08, 0.82, 1.18))
                            }
                        >
                            -
                        </button>
                        <button
                            type="button"
                            aria-label="Canvas settings"
                            onClick={() => setShowCanvasSettings((value) => !value)}
                        >
                            <Icon name="settings" />
                        </button>
                    </div>
                    {showCanvasSettings && (
                        <div className="canvas-settings">
                            Zoom {Math.round(canvasZoom * 100)}% · persisted agent graph
                        </div>
                    )}
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
                <MetricCard
                    label="Loop Status"
                    value={runningLoop ? 'Running' : loop ? 'Completed' : 'Ready'}
                    caption={loop ? `${formatDuration(loop.duration_ms)} elapsed` : 'No loop found'}
                    tone="green"
                />
                <div className="bottom-progress">
                    <span>Progress</span>
                    <ProgressBar
                        value={
                            agentRuns.length
                                ? (agentRuns.filter((a) => a.success).length / agentRuns.length) * 100
                                : 0
                        }
                        tone="green"
                    />
                    <small>
                        {agentRuns.filter((a) => a.success).length} of {agentRuns.length} agents
                        completed
                    </small>
                </div>
                <MetricCard
                    label="Success Rate"
                    value={`${agentRuns.length ? Math.round((agentRuns.filter((a) => a.success).length / agentRuns.length) * 100) : 0}%`}
                    caption={`(${agentRuns.filter((a) => a.success).length} / ${agentRuns.length})`}
                    tone="green"
                />
                <button
                    className="secondary-action"
                    type="button"
                    onClick={() => setLoopPaused((value) => !value)}
                >
                    <Icon name={loopPaused ? 'play' : 'pause'} />{' '}
                    {loopPaused ? 'Resume View' : 'Pause View'}
                </button>
                <button
                    className="primary-action"
                    type="button"
                    onClick={onRunLoop}
                    disabled={runningLoop}
                >
                    <Icon name="play" /> {runningLoop ? 'Running Loop' : 'Run Immune Loop'}
                </button>
                <a className="outline-action" href="#/audit">
                    <Icon name="trend" /> View Telemetry
                </a>
                <span className="subtle">{totalTools} tools called</span>
            </div>
        </section>
    );
}
