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
import { StatusAnnouncer } from '../components/StatusAnnouncer';

function LinkedMetricCard({
    href,
    ...props
}: React.ComponentProps<typeof MetricCard> & { href: string }) {
    return (
        <a className="metric-card-link" href={href}>
            <MetricCard {...props} />
        </a>
    );
}

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
    const toxicityScore = latestPrediction?.risk_score ?? latestCase?.confidence;
    const telemetryRows: Array<[ReactNode, ReactNode]> = [
        ['Recent loops persisted', formatNumber(totalLoops)],
        ['Agent runs (this loop)', formatNumber(loop?.agent_runs.length ?? 0)],
        ['Last cycle time', loop ? formatDuration(loop.duration_ms) : '—'],
        [
            'Prediction confidence',
            latestPrediction ? `${Math.round(latestPrediction.confidence * 100)}%` : '—',
        ],
        [
            'False positive rate',
            metricValue(metricFromExtra(data.modelMetrics[0], 'false_positive_rate'), '%'),
        ],
        [
            'Walk-forward PR-AUC',
            data.modelMetrics[0]?.pr_auc != null
                ? data.modelMetrics[0].pr_auc.toFixed(3)
                : '—',
        ],
    ];

    if (loading && !loop) return <LoadingState label="Loading command center data" />;

    return (
        <section>
            <div className="command-grid">
                <DataPanel className="loop-panel" title="Immune loop">
                    <div className="loop-panel-meta">
                        <StatusBadge tone="steel">Cycle {compactScenario(loop?.loop_id)}</StatusBadge>
                        <StatusBadge tone={runningLoop ? 'green' : loop ? 'green' : 'steel'}>
                            {runningLoop ? 'Running' : loop ? 'Completed' : 'Ready'}
                        </StatusBadge>
                        <span>
                            {loop ? `Started ${formatClock(loop.started_at)}` : 'No persisted cycle yet'}
                        </span>
                    </div>
                    <div className="loop-progress">
                        <div className="loop-progress-head">
                            <span>Agent progress</span>
                            <span className="mono">
                                {progress.completedAgents}/{progress.totalAgents}
                            </span>
                        </div>
                        <ProgressBar value={progress.percent} tone="green" />
                    </div>
                    <ImmuneCore>
                        <div className="hero-overlay">
                            <div
                                className={`hero-readout tone-${toneForRisk(toxicityScore ?? 0)}`}
                            >
                                <strong>
                                    <AnimatedNumber value={scoreValue(toxicityScore)} />
                                </strong>
                                <span>Aggregate toxicity · 10s markout proxy</span>
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
                            <span>{runningLoop ? 'Running Immune Loop…' : 'Run Immune Loop'}</span>
                        </button>
                        <a className="secondary-action" href="#/investigations">
                            <Icon name="folder" />
                            <span>Last Investigation</span>
                        </a>
                    </div>
                    {runMessage && <StatusAnnouncer message={runMessage} className="run-message" />}
                </DataPanel>

                <div className="metric-stack">
                    <MetricCard
                        icon="target"
                        label="Active scenario"
                        value={compactScenario(loop?.proposal?.name ?? latestScenario(data))}
                        caption={
                            loop?.proposal?.rationale_source === 'llm'
                                ? 'Rationale: narrative engine'
                                : 'From persisted loop data'
                        }
                        tone="ink"
                    />
                    <MetricCard
                        icon="shield"
                        label="Toxicity posture"
                        value={postureLabel(loop?.aggregate_posture)}
                        caption={
                            latestPrediction
                                ? `${marketRegime(latestPrediction)} · ${riskLabel(latestPrediction.risk_score)}`
                                : 'Monitoring Hyperliquid BTC-PERP flow'
                        }
                        tone={toneForRisk(toxicityScore ?? 0)}
                    >
                        <Sparkline values={riskValues(data.simulator).slice(-22)} tone="amber" />
                    </MetricCard>
                    <MetricCard
                        icon="gauge"
                        label="Latest toxicity score"
                        value={<AnimatedNumber value={scoreValue(toxicityScore)} />}
                        caption={
                            latestPrediction
                                ? `Calibrated confidence ${latestPrediction.confidence.toFixed(2)}`
                                : 'No persisted prediction'
                        }
                        tone={toneForRisk(latestPrediction?.risk_score ?? 0)}
                    >
                        <MiniScale value={toxicityScore ?? 0} />
                    </MetricCard>
                    <LinkedMetricCard
                        href="#/risk"
                        icon="bell"
                        label="Toxicity alerts"
                        value={
                            <AnimatedNumber
                                value={formatNumber(
                                    loop?.alert_count ?? data.simulator?.alerts.length ?? 0,
                                )}
                            />
                        }
                        caption={`${alertCounts.critical} critical · ${alertCounts.elevated} elevated · ${alertCounts.informational} info`}
                        tone="amber"
                    />
                    <LinkedMetricCard
                        href="#/investigations"
                        icon="folder"
                        label="Investigation cases"
                        value={formatNumber(loop?.case_count ?? 0)}
                        caption={`${caseCounts.open} open · ${caseCounts.in_review} with policy decision`}
                        tone="green"
                    />
                    <LinkedMetricCard
                        href="#/memory"
                        icon="brain"
                        label="Immune memories"
                        value={formatNumber(memories.length)}
                        caption={
                            memories[0]
                                ? `Last added ${relativeTime(memories[0].last_seen_at)}`
                                : 'No memories persisted'
                        }
                        tone="green"
                    />
                </div>

                <div className="side-stack">
                    <DataPanel title="Loop telemetry">
                        <KeyValueList rows={telemetryRows} />
                    </DataPanel>
                    <DataPanel title="Last run summary">
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
                                        ['Result', `${loop.alert_count} alerts · ${loop.case_count} cases`],
                                        [
                                            'Toxicity score',
                                            `${scoreValue(toxicityScore)} (${riskLabel(toxicityScore ?? 0)})`,
                                        ],
                                    ]}
                                />
                                <a className="panel-link" href="#/audit">
                                    View audit trace <Icon name="chevron" />
                                </a>
                            </div>
                        ) : (
                            <EmptyState
                                title="No run yet"
                                body="Run the immune loop to create persisted traces and investigation cases."
                            />
                        )}
                    </DataPanel>
                </div>
            </div>
        </section>
    );
}
