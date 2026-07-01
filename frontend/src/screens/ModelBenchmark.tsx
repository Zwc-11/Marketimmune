import { useMemo, useState } from 'react';
import type { ProductData } from '../routes';
import type { MarkoutFillDecisionPayload, MarkoutModelHealth, PromotionDecision } from '../types';
import type { Tone } from '../routes';
import { Icon } from '../components/Icon';
import { ModelTabPanel } from '../components/ModelTabPanel';
import { SlidingTabs } from '../components/motion/SlidingTabs';
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
    type BenchmarkSplitView,
    type ModelTab,
} from '../lib/derive';
import {
    formatDate,
    formatTimestamp,
    metricValue,
    price,
    sentenceCase,
    shortId,
    truncate,
    cleanText,
} from '../lib/format';

const MODEL_TABS: Array<{ id: ModelTab; label: string }> = [
    { id: 'trend', label: 'Trend' },
    { id: 'scenario', label: 'Scenarios' },
    { id: 'threshold', label: 'Threshold' },
    { id: 'calibration', label: 'Calibration' },
];

const VERDICT_LABEL: Record<PromotionDecision['verdict'], string> = {
    promote: 'Promote challenger',
    reject: 'Keep champion',
    needs_more_data: 'Needs more data',
};

const VERDICT_TONE: Record<PromotionDecision['verdict'], Tone> = {
    promote: 'green',
    reject: 'red',
    needs_more_data: 'amber',
};

function formatMetric(value: number | undefined | null, suffix = ''): string {
    return typeof value === 'number' && Number.isFinite(value)
        ? metricValue(value, suffix)
        : '-';
}

function actionTone(action: string | undefined): Tone {
    return action === 'withhold_quote' ? 'red' : 'green';
}

function refreshTone(status: string | undefined): Tone {
    if (status === 'succeeded') return 'green';
    if (status === 'failed') return 'red';
    if (status === 'running') return 'amber';
    return 'steel';
}

function PromotedMarkoutStatus({
    health,
    decisions,
}: {
    health: MarkoutModelHealth | null;
    decisions: MarkoutFillDecisionPayload | null;
}) {
    const available = health?.available ?? false;
    const training = health?.training ?? null;
    const holdout = health?.holdout ?? null;
    const fillRows = decisions?.decisions ?? [];
    const latest = fillRows[0] ?? null;
    const refresh = decisions?.latest_refresh ?? null;
    const holdoutDelta =
        health?.holdout_baseline_comparison?.event_ofi?.markout_lift_bps ??
        health?.baseline_comparison?.event_ofi?.markout_lift_bps;
    const badgeTone: Tone = available ? 'green' : 'amber';
    const badgeLabel = available ? 'Artifact live' : 'Artifact pending';

    return (
        <DataPanel
            className="promoted-markout-status"
            title="Promoted Hyperliquid markout model"
            eyebrow={health?.dataset_label ?? 'No promoted artifact loaded'}
            badge={<StatusBadge tone={badgeTone}>{badgeLabel}</StatusBadge>}
        >
            <KeyValueList
                rows={[
                    ['Instrument', health?.instrument ?? '-'],
                    ['Horizon', health?.horizon ?? '-'],
                    ['Training rows', training?.training_rows ?? training?.n_rows ?? '-'],
                    ['Holdout rows', holdout?.n_rows ?? '-'],
                    ['Holdout PR-AUC', formatMetric(holdout?.pr_auc)],
                    ['Holdout Brier', formatMetric(holdout?.brier)],
                    ['Holdout lift', formatMetric(holdout?.markout_lift_bps, ' bps')],
                    ['Vs event-OFI', formatMetric(holdoutDelta, ' bps')],
                    ['Threshold', formatMetric(health?.decision_threshold)],
                    ['Smoke p95', formatMetric(health?.smoke_latency?.p95_ms, ' ms')],
                    ['Persisted decisions', fillRows.length || '-'],
                    ['Latest action', latest ? sentenceCase(latest.action) : '-'],
                    ['Refresh status', refresh ? sentenceCase(refresh.status) : '-'],
                    ['Refresh trigger', refresh?.trigger ?? '-'],
                    ['Refresh count', refresh?.refreshed_count ?? '-'],
                    ['Refresh latency', formatMetric(refresh?.duration_ms, ' ms')],
                ]}
            />
            <div className="artifact-strip">
                <span className="trace-label">Artifact</span>
                <span className="mono">
                    {health?.artifacts?.model?.path ?? health?.message ?? 'Awaiting backend status'}
                </span>
            </div>
            <div className="artifact-strip">
                <span className="trace-label">Live decisions</span>
                <span>
                    {latest
                        ? `${sentenceCase(latest.action)} at ${formatMetric(latest.calibrated_score)}`
                        : decisions?.message || 'No persisted scored fills yet'}
                </span>
            </div>
            <div className="artifact-strip">
                <span className="trace-label">Refresh source</span>
                <span className="mono">
                    {refresh?.source_path ?? decisions?.source_path ?? 'No refresh run yet'}
                </span>
            </div>
        </DataPanel>
    );
}

function BackfillJobStatus({ data }: { data: ProductData }) {
    const jobs = data.hyperliquidBackfills?.jobs ?? [];
    const latest = jobs[0] ?? null;
    const badgeTone = refreshTone(latest?.status);
    return (
        <DataPanel
            title="Requester-pays backfill jobs"
            eyebrow="Explicit operator jobs; browser is read-only"
            badge={
                <StatusBadge tone={badgeTone}>
                    {latest ? sentenceCase(latest.status) : 'No jobs'}
                </StatusBadge>
            }
        >
            <div className="table-scroll">
                <table className="model-compare-table" aria-label="Hyperliquid backfill jobs">
                    <thead>
                        <tr>
                            <th scope="col">Started</th>
                            <th scope="col">Coin</th>
                            <th scope="col">Date</th>
                            <th scope="col">Trigger</th>
                            <th scope="col" className="num-cell">
                                Fills
                            </th>
                            <th scope="col" className="num-cell">
                                Training rows
                            </th>
                            <th scope="col">Refresh</th>
                            <th scope="col">Message</th>
                        </tr>
                    </thead>
                    <tbody>
                        {jobs.slice(0, 5).map((job) => (
                            <tr key={job.job_id}>
                                <td>{formatTimestamp(job.started_at)}</td>
                                <td>{job.coin}</td>
                                <td>{job.date}</td>
                                <td>{sentenceCase(job.trigger)}</td>
                                <td className="num-cell">{formatMetric(job.fills)}</td>
                                <td className="num-cell">{formatMetric(job.training_rows)}</td>
                                <td>
                                    {job.refresh_run_id ? `Run ${job.refresh_run_id}` : '-'}
                                </td>
                                <td>{job.message || sentenceCase(job.status)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {!jobs.length && (
                <p className="panel-note">
                    No persisted requester-pays backfill jobs yet.
                </p>
            )}
        </DataPanel>
    );
}

function RecentFillDecisions({ payload }: { payload: MarkoutFillDecisionPayload | null }) {
    const rows = payload?.decisions ?? [];
    const latest = rows[0] ?? null;
    const refresh = payload?.latest_refresh ?? null;
    const badgeTone: Tone = refresh ? refreshTone(refresh.status) : actionTone(latest?.action);
    return (
        <DataPanel
            title="Recent promoted fill decisions"
            eyebrow={payload?.source_path ?? 'Gold training parquet not scored yet'}
            badge={
                <StatusBadge tone={badgeTone}>
                    {refresh ? sentenceCase(refresh.status) : `${rows.length} persisted`}
                </StatusBadge>
            }
        >
            <div className="table-scroll">
                <table className="model-compare-table" aria-label="Recent scored fill decisions">
                    <thead>
                        <tr>
                            <th scope="col">Time</th>
                            <th scope="col">Coin</th>
                            <th scope="col">Action</th>
                            <th scope="col" className="num-cell">
                                Score
                            </th>
                            <th scope="col" className="num-cell">
                                Price
                            </th>
                            <th scope="col" className="num-cell">
                                Size
                            </th>
                            <th scope="col" className="num-cell">
                                Markout
                            </th>
                            <th scope="col">Loop action</th>
                            <th scope="col">Evidence</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => (
                            <tr key={row.decision_id}>
                                <td>{formatTimestamp(row.timestamp)}</td>
                                <td>{row.coin}</td>
                                <td>
                                    <StatusBadge tone={actionTone(row.action)}>
                                        {sentenceCase(row.action)}
                                    </StatusBadge>
                                </td>
                                <td className="num-cell">{formatMetric(row.calibrated_score)}</td>
                                <td className="num-cell">{price(row.px)}</td>
                                <td className="num-cell">{formatMetric(row.sz)}</td>
                                <td className="num-cell">
                                    {formatMetric(row.markout_bps, ' bps')}
                                </td>
                                <td>{row.recommended_action ? sentenceCase(row.recommended_action) : '-'}</td>
                                <td className="mono">{row.top_features.slice(0, 3).join(', ')}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {!rows.length && (
                <p className="panel-note">
                    {payload?.message || 'Run the promoted fill-decision refresh to persist rows.'}
                </p>
            )}
            {refresh && (
                <footer className="promotion-meta">
                    <span>
                        {refresh.refreshed_count} scored · {sentenceCase(refresh.trigger)} ·{' '}
                        {formatMetric(refresh.duration_ms, ' ms')}
                    </span>
                    <time dateTime={refresh.finished_at ?? refresh.started_at}>
                        {formatTimestamp(refresh.finished_at ?? refresh.started_at)}
                    </time>
                </footer>
            )}
        </DataPanel>
    );
}

function PromotionGate({
    promotion,
    activeName,
    candidateName,
    activeRun,
    candidateRun,
    championMarkout,
    challengerMarkout,
    championPrAuc,
    challengerPrAuc,
}: {
    promotion: PromotionDecision | null;
    activeName: string;
    candidateName: string;
    activeRun: ProductData['trainingRuns'][number] | null;
    candidateRun: ProductData['trainingRuns'][number] | null;
    championMarkout: string;
    challengerMarkout: string;
    championPrAuc: string;
    challengerPrAuc: string;
}) {
    const criteria = promotion?.metrics.criteria ?? {};
    const passed = promotion?.metrics.promote_votes ?? 0;
    const total = Object.keys(criteria).length || 5;
    const verdictTone = promotion ? VERDICT_TONE[promotion.verdict] : 'steel';
    const verdictLabel = promotion ? VERDICT_LABEL[promotion.verdict] : 'No verdict yet';

    return (
        <DataPanel
            className="promotion-strip"
            title="Benchmark promotion"
            eyebrow={
                activeRun?.split_summary ??
                'Purged and embargoed walk-forward · scenario-family held-out'
            }
            badge={<StatusBadge tone={verdictTone}>{verdictLabel}</StatusBadge>}
        >
            <div className="promotion-votes mono num">
                {promotion ? `${passed} / ${total} criteria passed` : 'Run immune loop to persist judge output'}
            </div>

            <div className="table-scroll">
                <table className="model-compare-table" aria-label="Champion and challenger comparison">
                    <thead>
                        <tr>
                            <th scope="col">Model</th>
                            <th scope="col" className="num-cell">
                                Markout lift
                            </th>
                            <th scope="col" className="num-cell">
                                PR-AUC
                            </th>
                            <th scope="col">Trained</th>
                            <th scope="col">Artifact</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>
                                <strong>{activeName}</strong>
                                <StatusBadge tone="green">Champion</StatusBadge>
                            </td>
                            <td className="num-cell">{championMarkout}</td>
                            <td className="num-cell">{championPrAuc}</td>
                            <td>{activeRun ? formatDate(activeRun.created_at) : '—'}</td>
                            <td className="mono">{activeRun ? shortId(activeRun.artifact_path) : '—'}</td>
                        </tr>
                        <tr>
                            <td>
                                <strong>{candidateName}</strong>
                                <StatusBadge tone="amber">Challenger</StatusBadge>
                            </td>
                            <td className="num-cell">{challengerMarkout}</td>
                            <td className="num-cell">{challengerPrAuc}</td>
                            <td>{candidateRun ? formatDate(candidateRun.created_at) : '—'}</td>
                            <td className="mono">
                                {candidateRun ? shortId(candidateRun.artifact_path) : '—'}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            {promotion && Object.keys(criteria).length > 0 && (
                <ul className="criteria-grid" aria-label="Promotion criteria">
                    {Object.entries(criteria).map(([name, item]) => (
                        <li key={name} className={item.passed ? 'criteria-pass' : 'criteria-fail'}>
                            <Icon name={item.passed ? 'check' : 'close'} aria-hidden="true" />
                            <div>
                                <span className="criteria-name">{name.replace(/_/g, ' ')}</span>
                                <span className="criteria-detail">{item.detail}</span>
                            </div>
                        </li>
                    ))}
                </ul>
            )}

            <p className="promotion-rationale">
                {promotion
                    ? truncate(cleanText(promotion.rationale), 220)
                    : 'BenchmarkJudge writes a verdict after each immune loop when benchmark metrics are persisted.'}
            </p>
            <footer className="promotion-meta">
                <time dateTime={promotion?.created_at ?? undefined}>
                    {promotion ? formatTimestamp(promotion.created_at) : 'Not persisted yet'}
                </time>
                <a className="panel-link" href="#/audit">
                    Open audit trace <Icon name="external" />
                </a>
            </footer>
        </DataPanel>
    );
}

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
        promotion?.incumbent_model || activeRun?.model_name || data.modelMetrics[0]?.model_name || '—';
    const candidateName =
        promotion?.candidate_model || candidateRun?.model_name || data.modelMetrics[1]?.model_name || '—';
    const [splitView, setSplitView] = useState<BenchmarkSplitView>('heldout');
    const [modelTab, setModelTab] = useState<ModelTab>('trend');

    const metricLookup = useMemo(() => {
        const map = new Map(rows.map((row) => [row.metric, row]));
        return {
            markout: map.get('Realized Markout Lift'),
            prAuc: map.get('PR-AUC'),
        };
    }, [rows]);

    if (loading && data.trainingRuns.length === 0) {
        return <LoadingState label="Loading benchmark evidence" />;
    }

    return (
        <section className="screen-stack">
            <PromotionGate
                promotion={promotion}
                activeName={activeName}
                candidateName={candidateName}
                activeRun={activeRun}
                candidateRun={candidateRun}
                championMarkout={metricLookup.markout?.active ?? '—'}
                challengerMarkout={metricLookup.markout?.candidate ?? '—'}
                championPrAuc={metricLookup.prAuc?.active ?? '—'}
                challengerPrAuc={metricLookup.prAuc?.candidate ?? '—'}
            />

            <PromotedMarkoutStatus
                health={data.markoutModel}
                decisions={data.markoutDecisions}
            />
            <BackfillJobStatus data={data} />
            <RecentFillDecisions payload={data.markoutDecisions} />

            <div className="split-row" role="group" aria-label="Evaluation split">
                <SplitCard
                    title="Random row split"
                    subtitle="IID sanity check"
                    active={splitView === 'random'}
                    onClick={() => setSplitView('random')}
                />
                <SplitCard
                    title="Scenario-family held-out"
                    subtitle="Primary generalization split"
                    badge="Primary"
                    active={splitView === 'heldout'}
                    onClick={() => setSplitView('heldout')}
                />
                <SplitCard
                    title="Benchmark window"
                    subtitle={
                        benchmark
                            ? String(benchmark.data.period ?? benchmark.title)
                            : 'Period unavailable'
                    }
                    icon="calendar"
                    active={splitView === 'window'}
                    onClick={() => setSplitView('window')}
                />
                <SplitCard
                    title="Scenario coverage"
                    subtitle={
                        benchmark
                            ? `${String(benchmark.data.tasks ?? '—')} tasks · ${metricValue(Number(benchmark.data.examples))} examples`
                            : 'Coverage unavailable'
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
                    title="Benchmark results"
                    badge={
                        <span
                            className="panel-info"
                            title="Champion vs challenger on persisted training artifacts"
                        >
                            <Icon name="info" aria-hidden="true" />
                            <span className="sr-only">Benchmark methodology</span>
                        </span>
                    }
                >
                    <BenchmarkTable rows={rows} splitView={splitView} />
                    <div className="table-legend">
                        <LegendItem tone="green" label="Challenger improved" />
                        <LegendItem tone="amber" label="Challenger degraded" />
                        <span>Δ is absolute difference</span>
                    </div>
                </DataPanel>

                <DataPanel
                    title="Provenance"
                    badge={
                        <span className="panel-info" title="What is persisted vs preview">
                            <Icon name="info" aria-hidden="true" />
                            <span className="sr-only">Provenance key</span>
                        </span>
                    }
                >
                    <div className="provenance-section real">
                        <Icon name="shield" aria-hidden="true" />
                        <strong>From persisted records</strong>
                        <p>Training runs, promotion verdict, and benchmark tables in the audit store.</p>
                        <ul>
                            <li>Purged and embargoed walk-forward CV</li>
                            <li>Scenario-family held-out evaluation</li>
                        </ul>
                    </div>
                    <div className="provenance-section simulated">
                        <Icon name="flask" aria-hidden="true" />
                        <strong>Preview fixtures</strong>
                        <p>Scenario lift bars on the Scenarios tab use local fixtures until Gold backfill ships.</p>
                        <ul>
                            <li>simEngine toxicity stream (not model inference)</li>
                            <li>Scenario lift chart on Scenarios tab</li>
                        </ul>
                    </div>
                    <KeyValueList
                        rows={[
                            ['Code version', String(benchmark?.data.code_version ?? '—')],
                            ['Data snapshot', String(benchmark?.data.dataset ?? '—')],
                            ['Decision ID', promotion ? shortId(promotion.decision_id) : '—'],
                            [
                                'Judge verdict',
                                promotion ? sentenceCase(promotion.verdict) : '—',
                            ],
                        ]}
                    />
                </DataPanel>
            </div>

            <div className="model-tab-bar">
                <SlidingTabs
                    tabs={MODEL_TABS}
                    value={modelTab}
                    onChange={setModelTab}
                    idPrefix="model-tab"
                />
                <span className="model-tab-meta">
                    UTC · Updated {data.loadedAt ? formatTimestamp(data.loadedAt) : 'pending'}
                </span>
            </div>
            <div
                role="tabpanel"
                id={`model-tab-${modelTab}-panel`}
                aria-labelledby={`model-tab-${modelTab}`}
            >
                <ModelTabPanel tab={modelTab} data={data} />
            </div>
        </section>
    );
}
