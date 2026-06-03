import { useState } from 'react';
import type { ProductData } from '../routes';
import { BrandMark, Icon } from '../components/Icon';
import {
    DataPanel,
    KeyValueList,
    LegendItem,
    LoadingState,
    SplitCard,
    StatusBadge,
} from '../components/ui';
import { BenchmarkTable } from '../components/investigation';
import {
    benchmarkRows,
    benchmarkSelectionBody,
    benchmarkSelectionTitle,
    modelTabBody,
    modelTabTitle,
    type BenchmarkSplitView,
    type ModelTab,
} from '../lib/derive';
import { formatDate, formatTimestamp, metricValue, sentenceCase, shortId, truncate, cleanText } from '../lib/format';

export function ModelBenchmarkScreen({
    data,
    loading,
}: {
    data: ProductData;
    loading: boolean;
}) {
    const promotion = data.loopState?.promotion ?? null;
    const activeRun = data.trainingRuns[0] ?? null;
    const candidateRun = data.trainingRuns[1] ?? data.trainingRuns[0] ?? null;
    const benchmark = data.benchmarkMetrics[0] ?? null;
    const rows = benchmarkRows(data.trainingRuns, data.modelMetrics);
    const activeName =
        promotion?.incumbent_model || activeRun?.model_name || data.modelMetrics[0]?.model_name || '-';
    const candidateName =
        promotion?.candidate_model || candidateRun?.model_name || data.modelMetrics[1]?.model_name || '-';
    const [splitView, setSplitView] = useState<BenchmarkSplitView>('heldout');
    const [modelTab, setModelTab] = useState<ModelTab>('trend');

    if (loading && data.trainingRuns.length === 0) {
        return <LoadingState label="Loading benchmark evidence" />;
    }

    return (
        <section className="screen-stack">
            <DataPanel className="model-hero">
                <div className="model-card active">
                    <span>
                        Active Model <span className="status-dot green" />
                    </span>
                    <div className="model-line">
                        <BrandMark />
                        <div>
                            <strong>{activeName}</strong>
                            <StatusBadge tone="green">Production</StatusBadge>
                            <small>Deployed: {activeRun ? formatDate(activeRun.created_at) : '-'}</small>
                            <small>Model ID: {activeRun ? shortId(activeRun.artifact_path) : '-'}</small>
                        </div>
                    </div>
                </div>
                <div className="vs-badge">VS</div>
                <div className="model-card candidate">
                    <span>Candidate Model</span>
                    <div className="model-line">
                        <BrandMark />
                        <div>
                            <strong>{candidateName}</strong>
                            <StatusBadge tone="amber">Challenger</StatusBadge>
                            <small>Trained: {candidateRun ? formatDate(candidateRun.created_at) : '-'}</small>
                            <small>Model ID: {candidateRun ? shortId(candidateRun.artifact_path) : '-'}</small>
                        </div>
                    </div>
                </div>
                <div className="promotion-decision">
                    <span>Promotion Decision</span>
                    <div className="decision-check">
                        <Icon name="check" />
                    </div>
                    <strong>{promotion ? sentenceCase(promotion.verdict) : 'No Decision'}</strong>
                    <p>
                        {promotion
                            ? truncate(cleanText(promotion.rationale), 130)
                            : 'No persisted promotion decision is available.'}
                    </p>
                    <small>
                        Decision: {promotion ? 'BenchmarkJudge persisted record' : 'not persisted'} -{' '}
                        {promotion ? formatTimestamp(promotion.created_at) : '-'}
                    </small>
                </div>
            </DataPanel>

            <div className="split-row">
                <SplitCard
                    title="Random Row Split"
                    subtitle="IID estimate (sanity check)"
                    active={splitView === 'random'}
                    onClick={() => setSplitView('random')}
                />
                <SplitCard
                    title="Scenario-Family Held-Out Split"
                    subtitle="Generalization estimate (primary)"
                    badge="Primary"
                    active={splitView === 'heldout'}
                    onClick={() => setSplitView('heldout')}
                />
                <SplitCard
                    title="Benchmark Window"
                    subtitle={
                        benchmark
                            ? String(benchmark.data.period ?? benchmark.title)
                            : 'Benchmark period unavailable'
                    }
                    icon="calendar"
                    active={splitView === 'window'}
                    onClick={() => setSplitView('window')}
                />
                <SplitCard
                    title="Scenarios"
                    subtitle={
                        benchmark
                            ? `${String(benchmark.data.tasks ?? '-')} tasks - ${metricValue(Number(benchmark.data.examples))} examples`
                            : 'Benchmark scenarios unavailable'
                    }
                    icon="layers"
                    active={splitView === 'scenarios'}
                    onClick={() => setSplitView('scenarios')}
                />
            </div>
            <DataPanel className="selection-panel">
                <strong>{benchmarkSelectionTitle(splitView)}</strong>
                <span>{benchmarkSelectionBody(splitView, benchmark)}</span>
            </DataPanel>

            <div className="model-grid">
                <DataPanel
                    className="benchmark-table-panel"
                    title="Benchmark Results"
                    badge={<Icon name="info" />}
                >
                    <BenchmarkTable rows={rows} />
                    <div className="table-legend">
                        <LegendItem tone="green" label="Improved" />
                        <LegendItem tone="amber" label="Degraded" />
                        <span>No material change</span>
                        <span>Δ shown as absolute difference</span>
                    </div>
                </DataPanel>
                <DataPanel title="Provenance & Honesty" badge={<Icon name="info" />}>
                    <div className="provenance-section real">
                        <Icon name="shield" />
                        <strong>Benchmark Evidence (from data)</strong>
                        <p>
                            Metrics computed from persisted benchmark and training run records.
                        </p>
                        <ul>
                            <li>Random Row Split (IID)</li>
                            <li>Scenario-Family Held-Out Split (Primary)</li>
                        </ul>
                    </div>
                    <div className="provenance-section simulated">
                        <Icon name="flask" />
                        <strong>Simulated Outputs</strong>
                        <p>
                            Operational estimates are labeled and not used for promotion decisions.
                        </p>
                        <ul>
                            <li>Live traffic projection</li>
                            <li>What-if threshold analysis</li>
                        </ul>
                    </div>
                    <KeyValueList
                        rows={[
                            ['Code Version', String(benchmark?.data.code_version ?? '-')],
                            ['Data Snapshot', String(benchmark?.data.dataset ?? '-')],
                            ['Benchmark Job ID', promotion ? shortId(promotion.decision_id) : '-'],
                        ]}
                    />
                    <a className="panel-link" href="#/audit">
                        View full benchmark report <Icon name="external" />
                    </a>
                </DataPanel>
            </div>
            <div className="tab-strip">
                <button
                    className={modelTab === 'trend' ? 'active' : ''}
                    type="button"
                    onClick={() => setModelTab('trend')}
                >
                    Trend View
                </button>
                <button
                    className={modelTab === 'scenario' ? 'active' : ''}
                    type="button"
                    onClick={() => setModelTab('scenario')}
                >
                    Scenario Breakdown
                </button>
                <button
                    className={modelTab === 'threshold' ? 'active' : ''}
                    type="button"
                    onClick={() => setModelTab('threshold')}
                >
                    Threshold Analysis
                </button>
                <button
                    className={modelTab === 'calibration' ? 'active' : ''}
                    type="button"
                    onClick={() => setModelTab('calibration')}
                >
                    Calibration
                </button>
                <span className="right">
                    All times in UTC · Last updated:{' '}
                    {data.loadedAt ? formatTimestamp(data.loadedAt) : 'pending'}
                </span>
            </div>
            <DataPanel className="selection-panel">
                <strong>{modelTabTitle(modelTab)}</strong>
                <span>{modelTabBody(modelTab, rows.length)}</span>
            </DataPanel>
        </section>
    );
}
