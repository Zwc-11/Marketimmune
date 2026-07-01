import { useEffect, useMemo, useState } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    DataTable,
    EmptyState,
    LoadingState,
    MetricBlock,
    PageHeader,
    StatusBadge,
} from '../components/ui';
import { RiskGauge, Sparkline, ThresholdBar } from '../components/charts';
import {
    FeatureDeltaTable,
    FeatureImpactList,
    RuleOverlayList,
} from '../components/investigation';
import {
    featureRowsFrom,
    modelOptionsFrom,
    modelScoringView,
    riskLabel,
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

export function RiskSentinelScreen({ data, loading }: { data: ProductData; loading: boolean }) {
    const modelOptions = useMemo(() => modelOptionsFrom(data), [data]);
    const defaultModel = modelOptions[0] ?? '';
    const [selectedModel, setSelectedModel] = useState(defaultModel);

    useEffect(() => {
        if (!modelOptions.length) return;
        if (!modelOptions.includes(selectedModel)) {
            setSelectedModel(modelOptions[0]);
        }
    }, [modelOptions, selectedModel]);

    const scoring = useMemo(
        () => modelScoringView(data, selectedModel || defaultModel),
        [data, selectedModel, defaultModel],
    );
    const prediction = scoring.prediction;
    const riskScore = prediction?.risk_score ?? 0;
    const threshold = scoring.threshold;
    const latestCase = data.loopState?.loop?.cases[0] ?? null;
    const featureRows = featureRowsFrom(latestCase, data.simulator);
    const alerts = data.simulator?.alerts.slice(0, 5) ?? [];

    if (loading && !data.simulator) {
        return <LoadingState label="Loading toxicity sentinel" />;
    }

    if (!data.simulator) {
        return (
            <EmptyState
                title="No replay stream"
                body="The local replay stream is unavailable. Open Live Market to inspect the Hyperliquid feed."
                action={{ label: 'Open live market', href: '#/live' }}
            />
        );
    }

    return (
        <section className="screen-stack">
            <PageHeader
                title="Toxicity Sentinel"
                subtitle="Score maker fills for adverse selection with explainable features and rule overlays"
                right={
                    <>
                        <label className="model-select-label" htmlFor="risk-model-select">
                            Scoring model
                        </label>
                        {modelOptions.length ? (
                            <select
                                id="risk-model-select"
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
                            <span className="subtle">No model artifacts loaded</span>
                        )}
                        {scoring.source === 'calibrated' && selectedModel ? (
                            <StatusBadge tone="amber">Metric overlay</StatusBadge>
                        ) : (
                            <StatusBadge tone="green">Live stream</StatusBadge>
                        )}
                        <span className="subtle">
                            Updated {data.loadedAt ? relativeTime(data.loadedAt) : 'pending'}
                        </span>
                    </>
                }
            />

            {scoring.source === 'calibrated' && (
                <p className="risk-notice" role="note">
                    Showing {selectedModel} scores calibrated from stored training metrics on the
                    current replay stream. Switch to the live classifier name for raw stream scores.
                </p>
            )}

            <DataPanel className="risk-top-strip">
                <MetricBlock
                    icon="trend"
                    label="Latest score"
                    value={<AnimatedNumber value={scoreValue(riskScore)} />}
                    helper={`Toxicity (0–1) · ${scoring.modelName || 'model'}`}
                    tone={toneForRisk(riskScore)}
                >
                    <Sparkline values={scoring.riskSeries.slice(-24)} tone="amber" />
                </MetricBlock>
                <MetricBlock
                    icon="shield"
                    label="Toxicity label"
                    value={<TextSwap text={riskLabel(riskScore)} />}
                    helper="Adverse-selection band"
                    tone={toneForRisk(riskScore)}
                />
                <MetricBlock
                    icon="target"
                    label="Confidence"
                    value={prediction ? prediction.confidence.toFixed(2) : '-'}
                    helper={prediction ? 'Model score confidence' : 'Unavailable'}
                    tone="green"
                />
                <MetricBlock
                    icon="gauge"
                    label="Quote threshold τ"
                    value={threshold.toFixed(2)}
                    helper="Widen/withhold above τ"
                    tone="ink"
                >
                    <ThresholdBar value={threshold} />
                </MetricBlock>
            </DataPanel>

            <div className="risk-grid">
                <DataPanel title="Toxicity gauge" badge={<Icon name="info" />}>
                    <RiskGauge value={riskScore} label={riskLabel(riskScore)} />
                    <p className="center-note">
                        {prediction?.explanation ??
                            'No prediction explanation is available for this model.'}
                    </p>
                </DataPanel>
                <DataPanel title="Top contributing features" badge={<Icon name="info" />}>
                    {featureRows.length ? (
                        <FeatureImpactList rows={featureRows.slice(0, 6)} />
                    ) : (
                        <EmptyState
                            title="No feature evidence"
                            body="Run the immune loop or advance the replay to populate feature snapshots."
                        />
                    )}
                </DataPanel>
                <DataPanel title="Feature deltas vs baseline" badge={<Icon name="info" />}>
                    {featureRows.length ? (
                        <FeatureDeltaTable rows={featureRows.slice(0, 7)} />
                    ) : (
                        <EmptyState
                            title="No feature deltas"
                            body="Feature deltas require a case file or simulator feature row."
                        />
                    )}
                    <a className="panel-link" href="#/investigations">
                        Open investigation case <Icon name="chevron" />
                    </a>
                </DataPanel>
                <DataPanel title="Matched rule overlays" badge={<Icon name="info" />}>
                    {latestCase?.matched_rules.length ? (
                        <RuleOverlayList rules={latestCase.matched_rules} />
                    ) : (
                        <EmptyState
                            title="No matched rules"
                            body="Run the immune loop to persist rule matches on a case file."
                        />
                    )}
                    <a className="panel-link" href="#/investigations">
                        Open investigation case <Icon name="chevron" />
                    </a>
                </DataPanel>
            </div>

            <DataTable
                title="Recent alerts"
                columns={[
                    'Time',
                    'Alert ID',
                    'Metric / message',
                    'Value',
                    'Severity',
                    'Status',
                    'Linked case',
                ]}
                rows={alerts.map((alert) => {
                    const linkedCase = data.loopState?.loop?.cases.find(
                        (caseFile) => caseFile.alert_id === String(alert.id),
                    );
                    return [
                        formatTimestamp(alert.timestamp),
                        `ALT-${alert.id}`,
                        alert.metric_name ? `${alert.metric_name}: ${alert.message}` : alert.message,
                        metricValue(alert.metric_value),
                        sentenceCase(alert.severity),
                        linkedCase ? 'In review' : 'Open',
                        linkedCase ? shortId(linkedCase.case_id) : '-',
                    ];
                })}
                footer={alerts.length ? 'Open investigation case' : undefined}
                footerHref="#/investigations"
            />
            <div className="assurance-line">
                <Icon name="shield" aria-hidden="true" />
                Feature attributions trace to persisted agent runs
            </div>
        </section>
    );
}
