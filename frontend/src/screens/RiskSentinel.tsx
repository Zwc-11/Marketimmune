import { useMemo, useState } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    DataTable,
    EmptyState,
    LoadingState,
    MetricBlock,
    PageHeader,
} from '../components/ui';
import { RiskGauge, Sparkline, ThresholdBar } from '../components/charts';
import {
    FeatureDeltaTable,
    FeatureImpactList,
    RuleOverlayList,
} from '../components/investigation';
import {
    featureRowsFrom,
    latestPredictionFrom,
    riskLabel,
    riskValues,
    toneForRisk,
} from '../lib/derive';
import {
    formatTimestamp,
    metricValue,
    relativeTime,
    scoreValue,
    sentenceCase,
    shortId,
} from '../lib/format';
import { AnimatedNumber } from '../components/motion/AnimatedNumber';
import { TextSwap } from '../components/motion/TextSwap';

const HIGH_RISK_THRESHOLD = 0.75;

export function RiskSentinelScreen({ data, loading }: { data: ProductData; loading: boolean }) {
    const latestPrediction = latestPredictionFrom(data.simulator);
    const latestCase = data.loopState?.loop?.cases[0] ?? null;
    const riskScore = latestPrediction?.risk_score ?? latestCase?.confidence ?? 0;
    const featureRows = featureRowsFrom(latestCase, data.simulator);
    const alerts = data.simulator?.alerts.slice(0, 5) ?? [];
    const modelOptions = useMemo(() => {
        const names = new Set<string>();
        if (latestPrediction?.model_name) names.add(latestPrediction.model_name);
        for (const run of data.trainingRuns) names.add(run.model_name);
        for (const metric of data.modelMetrics) names.add(metric.model_name);
        return Array.from(names).filter(Boolean);
    }, [latestPrediction?.model_name, data.trainingRuns, data.modelMetrics]);
    const [selectedModel, setSelectedModel] = useState<string>(
        latestPrediction?.model_name ?? modelOptions[0] ?? '',
    );

    if (loading && !data.simulator) return <LoadingState label="Loading risk sentinel" />;

    return (
        <section className="screen-stack">
            <PageHeader
                title="Toxicity Sentinel"
                subtitle="Score maker fills for adverse selection with explainable AI"
                right={
                    <>
                        <label className="model-select-label">Model</label>
                        {modelOptions.length ? (
                            <select
                                className="model-select"
                                value={selectedModel}
                                onChange={(event) => setSelectedModel(event.target.value)}
                            >
                                {modelOptions.map((name) => (
                                    <option key={name} value={name}>
                                        {name}
                                    </option>
                                ))}
                            </select>
                        ) : (
                            <span className="subtle">No persisted model</span>
                        )}
                        <span className="subtle">
                            Last updated: {data.loadedAt ? relativeTime(data.loadedAt) : 'pending'}
                        </span>
                    </>
                }
            />
            <DataPanel className="risk-top-strip">
                <MetricBlock
                    icon="trend"
                    label="Latest Prediction"
                    value={<AnimatedNumber value={scoreValue(riskScore)} />}
                    helper="Toxicity Score (0-1)"
                    tone={toneForRisk(riskScore)}
                >
                    <Sparkline values={riskValues(data.simulator).slice(-24)} tone="amber" />
                </MetricBlock>
                <MetricBlock
                    icon="shield"
                    label="Toxicity Label"
                    value={<TextSwap text={riskLabel(riskScore)} />}
                    helper="Adverse-selection risk"
                    tone={toneForRisk(riskScore)}
                />
                <MetricBlock
                    icon="target"
                    label="Confidence"
                    value={latestPrediction?.confidence.toFixed(2) ?? '-'}
                    helper="Model Confidence"
                    tone="green"
                />
                <MetricBlock
                    icon="gauge"
                    label="Decision Threshold"
                    value={HIGH_RISK_THRESHOLD.toFixed(2)}
                    helper="Toxicity Threshold"
                    tone="ink"
                >
                    <ThresholdBar value={HIGH_RISK_THRESHOLD} />
                </MetricBlock>
            </DataPanel>

            <div className="risk-grid">
                <DataPanel title="Toxicity Score Gauge" badge={<Icon name="info" />}>
                    <RiskGauge value={riskScore} label={riskLabel(riskScore)} />
                    <p className="center-note">Toxicity score calibrated (isotonic) to realized markout</p>
                </DataPanel>
                <DataPanel title="Top Contributing Features" badge={<Icon name="info" />}>
                    {featureRows.length ? (
                        <FeatureImpactList rows={featureRows.slice(0, 6)} />
                    ) : (
                        <EmptyState
                            title="No feature evidence"
                            body="No persisted feature snapshot is available for this replay."
                        />
                    )}
                </DataPanel>
                <DataPanel title="Feature Deltas (vs. Baseline)" badge={<Icon name="info" />}>
                    {featureRows.length ? (
                        <FeatureDeltaTable rows={featureRows.slice(0, 7)} />
                    ) : (
                        <EmptyState
                            title="No feature deltas"
                            body="Feature deltas require persisted case or simulator feature data."
                        />
                    )}
                    <a className="panel-link" href="#/investigations">
                        View all feature deltas <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Matched Rule Overlays" badge={<Icon name="info" />}>
                    {latestCase?.matched_rules.length ? (
                        <RuleOverlayList rules={latestCase.matched_rules} />
                    ) : (
                        <EmptyState
                            title="No matched rules"
                            body="Run the immune loop to persist rule matches."
                        />
                    )}
                    <a className="panel-link" href="#/investigations">
                        View all matched rules <Icon name="chevron" />
                    </a>
                </DataPanel>
            </div>

            <DataTable
                title="Recent Alerts"
                columns={[
                    'Time',
                    'Alert ID',
                    'Metric / Message',
                    'Value',
                    'Severity',
                    'Status',
                    'Linked Case',
                ]}
                rows={alerts.map((alert) => {
                    const linkedCase = data.loopState?.loop?.cases.find(
                        (c) => c.alert_id === String(alert.id),
                    );
                    return [
                        formatTimestamp(alert.timestamp),
                        `ALT-${alert.id}`,
                        alert.metric_name ? `${alert.metric_name}: ${alert.message}` : alert.message,
                        metricValue(alert.metric_value),
                        sentenceCase(alert.severity),
                        linkedCase ? 'In Review' : 'Detected',
                        linkedCase ? shortId(linkedCase.case_id) : '-',
                    ];
                })}
                footer={alerts.length ? 'View full alert evidence' : 'No persisted alerts'}
            />
            <div className="assurance-line">
                <Icon name="shield" /> Explainability ensured by Immune Loop
            </div>
        </section>
    );
}
