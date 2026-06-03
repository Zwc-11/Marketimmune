import type { ReactNode } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    EmptyState,
    KeyValueList,
    LoadingState,
    MetricCard,
    StatusBadge,
    StatusLine,
} from '../components/ui';
import { MiniScale, ProgressBar, Sparkline } from '../components/charts';
import { LazyImmuneCore as ImmuneCore } from '../components/three/LazyImmuneCore';
import {
    compactScenario,
    formatClock,
    formatDuration,
    formatNumber,
    relativeTime,
    scoreValue,
} from '../lib/format';
import {
    alertBreakdown,
    caseBreakdown,
    latestPredictionFrom,
    latestScenario,
    loopProgress,
    marketRegime,
    metricFromExtra,
    postureLabel,
    riskLabel,
    riskValues,
    toneForRisk,
} from '../lib/derive';
import { metricValue } from '../lib/format';
import { AnimatedNumber } from '../components/motion/AnimatedNumber';
import { TextSwap } from '../components/motion/TextSwap';
import { ShimmerText } from '../components/motion/ShimmerText';

export function CommandCenterScreen({
    data,
    loading,
    runningLoop,
    runMessage,
    onRunLoop,
}: {
    data: ProductData;
    loading: boolean;
    runningLoop: boolean;
    runMessage: string;
    onRunLoop: () => void;
}) {
    const loop = data.loopState?.loop ?? null;
    const latestPrediction = latestPredictionFrom(data.simulator);
    const latestCase = loop?.cases[0] ?? null;
    const memories = data.loopState?.memories ?? [];
    const progress = loopProgress(loop, runningLoop);
    const alertCounts = alertBreakdown(data.simulator, loop?.alert_count);
    const caseCounts = caseBreakdown(loop);
    const totalLoops = data.loopState?.recent_loops.length ?? 0;
    const telemetryRows: Array<[ReactNode, ReactNode]> = [
        ['Recent Loops Persisted', formatNumber(totalLoops)],
        ['Agent Runs (this loop)', formatNumber(loop?.agent_runs.length ?? 0)],
        ['Last Cycle Time', loop ? formatDuration(loop.duration_ms) : '-'],
        [
            'Latest Prediction Confidence',
            latestPrediction ? `${Math.round(latestPrediction.confidence * 100)}%` : '-',
        ],
        ['False Positive Rate', metricValue(metricFromExtra(data.modelMetrics[0], 'false_positive_rate'), '%')],
        ['Model Confidence', latestPrediction ? latestPrediction.confidence.toFixed(2) : '-'],
    ];

    if (loading && !loop) return <LoadingState label="Loading command center data" />;

    return (
        <section>
            <div className="command-grid">
                <div className="metric-stack">
                    <MetricCard
                        icon="pulse"
                        label="Loop Status"
                        value={
                            runningLoop ? (
                                <ShimmerText>Running</ShimmerText>
                            ) : (
                                <TextSwap text={loop ? 'Completed' : 'Ready'} />
                            )
                        }
                        caption={
                            loop
                                ? `${progress.completedAgents}/${progress.totalAgents} agents · ${formatClock(loop.started_at)}`
                                : 'No persisted loop yet'
                        }
                        tone="green"
                    >
                        <ProgressBar value={progress.percent} tone="green" />
                    </MetricCard>
                    <MetricCard
                        icon="target"
                        label="Active Scenario"
                        value={compactScenario(loop?.proposal?.name ?? latestScenario(data))}
                        caption={
                            loop?.proposal?.rationale_source === 'llm'
                                ? 'Source: Narrative engine'
                                : 'Source: persisted loop data'
                        }
                        tone="ink"
                    />
                    <MetricCard
                        icon="trend"
                        label="Market Regime"
                        value={marketRegime(latestPrediction)}
                        caption={
                            latestPrediction
                                ? `Regime confidence: ${Math.round(latestPrediction.confidence * 100)}%`
                                : 'Awaiting replay'
                        }
                        tone="amber"
                    />
                    <MetricCard
                        icon="shield"
                        label="Toxicity Posture"
                        value={postureLabel(loop?.aggregate_posture)}
                        caption={
                            latestPrediction
                                ? `vs. baseline +${latestPrediction.risk_score.toFixed(2)}`
                                : 'Awaiting replay'
                        }
                        tone={toneForRisk(latestPrediction?.risk_score ?? latestCase?.confidence ?? 0)}
                    >
                        <Sparkline values={riskValues(data.simulator).slice(-22)} tone="amber" />
                    </MetricCard>
                    <MetricCard
                        icon="gauge"
                        label="Latest Toxicity Score"
                        value={
                            <AnimatedNumber
                                value={scoreValue(
                                    latestPrediction?.risk_score ?? latestCase?.confidence,
                                )}
                            />
                        }
                        caption={
                            latestPrediction
                                ? `Model confidence ${latestPrediction.confidence.toFixed(2)}`
                                : 'No persisted prediction'
                        }
                        tone={toneForRisk(latestPrediction?.risk_score ?? 0)}
                    >
                        <MiniScale value={latestPrediction?.risk_score ?? latestCase?.confidence ?? 0} />
                    </MetricCard>
                    <MetricCard
                        icon="bell"
                        label="Alerts"
                        value={
                            <AnimatedNumber
                                value={formatNumber(
                                    loop?.alert_count ?? data.simulator?.alerts.length ?? 0,
                                )}
                            />
                        }
                        caption={`${alertCounts.critical} critical, ${alertCounts.elevated} elevated, ${alertCounts.informational} info`}
                        tone="amber"
                        action
                    />
                    <MetricCard
                        icon="folder"
                        label="Investigation Cases"
                        value={formatNumber(loop?.case_count ?? 0)}
                        caption={`${caseCounts.open} open, ${caseCounts.in_review} with policy decision`}
                        tone="green"
                        action
                    />
                    <MetricCard
                        icon="brain"
                        label="Immune Memories"
                        value={formatNumber(memories.length)}
                        caption={
                            memories[0]
                                ? `Last added: ${relativeTime(memories[0].last_seen_at)}`
                                : 'No memories persisted'
                        }
                        tone="green"
                        action
                    />
                </div>

                <DataPanel className="loop-panel" title="Immune Loop">
                    <div className="loop-panel-meta">
                        <StatusBadge tone="steel">Cycle {compactScenario(loop?.loop_id)}</StatusBadge>
                        <span>Started&nbsp; {formatClock(loop?.started_at)}</span>
                    </div>
                    <ImmuneCore>
                        <div className="hero-overlay">
                            <div
                                className={`hero-readout tone-${toneForRisk(
                                    latestPrediction?.risk_score ?? latestCase?.confidence ?? 0,
                                )}`}
                            >
                                <strong>
                                    <AnimatedNumber
                                        value={scoreValue(
                                            latestPrediction?.risk_score ?? latestCase?.confidence,
                                        )}
                                    />
                                </strong>
                                <span>Aggregate Toxicity</span>
                            </div>
                        </div>
                    </ImmuneCore>
                    <div className="loop-actions">
                        <button
                            className="primary-action"
                            type="button"
                            onClick={onRunLoop}
                            disabled={runningLoop}
                        >
                            <Icon name="play" />
                            <span>{runningLoop ? 'Running Immune Loop' : 'Run Immune Loop'}</span>
                        </button>
                        <a className="secondary-action" href="#/investigations">
                            <Icon name="folder" />
                            <span>View Last Investigation</span>
                        </a>
                    </div>
                    {runMessage && <div className="run-message">{runMessage}</div>}
                </DataPanel>

                <div className="side-stack">
                    <DataPanel title="Loop Telemetry">
                        <KeyValueList rows={telemetryRows} />
                    </DataPanel>
                    <DataPanel title="Last Run Summary">
                        {loop ? (
                            <div className="summary-list">
                                <StatusLine
                                    icon="check"
                                    label={`Completed ${relativeTime(loop.started_at)}`}
                                    tone="green"
                                />
                                <KeyValueList
                                    rows={[
                                        ['Scenario', compactScenario(loop.proposal?.name ?? loop.proposal_name)],
                                        ['Result', `${loop.alert_count} alerts, ${loop.case_count} cases`],
                                        [
                                            'Toxicity Score',
                                            `${scoreValue(latestPrediction?.risk_score ?? latestCase?.confidence)} (${riskLabel(latestPrediction?.risk_score ?? latestCase?.confidence ?? 0)})`,
                                        ],
                                    ]}
                                />
                                <a className="panel-link" href="#/audit">
                                    View Run Details <Icon name="chevron" />
                                </a>
                            </div>
                        ) : (
                            <EmptyState
                                title="No run yet"
                                body="Run the immune loop to create persisted traces."
                            />
                        )}
                    </DataPanel>
                </div>
            </div>
        </section>
    );
}
