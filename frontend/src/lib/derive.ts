import type {
    AgentRunSummary,
    AgentToolCall,
    BenchmarkMetric,
    ImmuneMemory,
    InvestigationCase,
    LoopState,
    ModelMetric,
    SimulatorEvent,
    SimulatorPrediction,
    SimulatorState,
    TrainingRun,
} from '../types';
import type { ProductData, Tone } from '../routes';
import {
    clamp,
    formatClock,
    formatDuration,
    metricValue,
    price,
    sentenceCase,
    shortId,
} from './format';

export function latestPredictionFrom(simulator: SimulatorState | null): SimulatorPrediction | null {
    return simulator?.predictions[simulator.predictions.length - 1] ?? null;
}

export function latestEventFrom(simulator: SimulatorState | null): SimulatorEvent | null {
    return simulator?.events[simulator.events.length - 1] ?? null;
}

export function riskValues(simulator: SimulatorState | null): number[] {
    return (simulator?.predictions ?? []).map((prediction) => prediction.risk_score);
}

export function criticalAlertCount(simulator: SimulatorState | null): number {
    return (simulator?.alerts ?? []).filter((alert) =>
        alert.severity.toLowerCase().includes('critical'),
    ).length;
}

export function elevatedAlertCount(simulator: SimulatorState | null): number {
    return (simulator?.alerts ?? []).filter(
        (alert) => !alert.severity.toLowerCase().includes('critical'),
    ).length;
}

export interface AlertBreakdown {
    critical: number;
    elevated: number;
    informational: number;
}

export function alertBreakdown(
    simulator: SimulatorState | null,
    loopAlertTotal?: number,
): AlertBreakdown {
    const alerts = simulator?.alerts ?? [];
    const counts = { critical: 0, elevated: 0, informational: 0 };
    for (const alert of alerts) {
        const sev = alert.severity.toLowerCase();
        if (sev.includes('critical')) counts.critical += 1;
        else if (sev.includes('high') || sev.includes('elevated') || sev.includes('medium'))
            counts.elevated += 1;
        else counts.informational += 1;
    }
    // If the immune loop reported a larger total than the persisted simulator
    // alerts, attribute the remainder to the informational bucket so the
    // numbers still sum to the headline figure shown on the card.
    if (typeof loopAlertTotal === 'number') {
        const persisted = counts.critical + counts.elevated + counts.informational;
        if (loopAlertTotal > persisted) {
            counts.informational += loopAlertTotal - persisted;
        }
    }
    return counts;
}

export interface CaseBreakdown {
    open: number;
    in_review: number;
}

export function caseBreakdown(loop: LoopState['loop'] | null): CaseBreakdown {
    if (!loop) return { open: 0, in_review: 0 };
    const decidedIds = new Set(loop.decisions.map((d) => d.case_id));
    let open = 0;
    let inReview = 0;
    for (const c of loop.cases) {
        if (decidedIds.has(c.case_id)) inReview += 1;
        else open += 1;
    }
    return { open, in_review: inReview };
}

export function sessionDuration(simulator: SimulatorState | null): number {
    if (!simulator) return 0;
    if (simulator.duration_ms && Number.isFinite(simulator.duration_ms)) {
        return simulator.duration_ms;
    }
    if (simulator.session_start && simulator.session_end) {
        const start = Date.parse(simulator.session_start);
        const end = Date.parse(simulator.session_end);
        if (Number.isFinite(start) && Number.isFinite(end)) {
            return Math.max(0, end - start);
        }
    }
    return 0;
}

export function loopProgress(
    loop: LoopState['loop'] | null,
    running: boolean,
): { percent: number; completedAgents: number; totalAgents: number } {
    const agents: AgentRunSummary[] = loop?.agent_runs ?? [];
    const total = agents.length;
    if (!total) {
        return { percent: running ? 5 : 0, completedAgents: 0, totalAgents: 0 };
    }
    const completed = agents.filter((agent) => agent.success).length;
    const percent = Math.round((completed / total) * 100);
    return { percent, completedAgents: completed, totalAgents: total };
}

export function activeAgentIndex(
    loop: LoopState['loop'] | null,
    running: boolean,
): number {
    const agents: AgentRunSummary[] = loop?.agent_runs ?? [];
    if (!agents.length) return 0;
    if (running) {
        const idx = agents.findIndex((agent) => !agent.success);
        return idx >= 0 ? idx : agents.length - 1;
    }
    return agents.length - 1;
}

const REPLAY_EVENT_TYPE_LABEL: Record<string, string> = {
    market_data: 'Market Data',
    kline: 'Kline Tick',
    trade: 'Trade Print',
    book_depth: 'Book Depth Snapshot',
    book_ticker: 'Book Ticker',
    candle: 'Candle Close',
};

export function eventTypeLabel(event: SimulatorEvent | null | undefined): string {
    if (!event) return '-';
    const raw = (event.event_type ?? '').toLowerCase();
    if (raw && REPLAY_EVENT_TYPE_LABEL[raw]) return REPLAY_EVENT_TYPE_LABEL[raw];
    if (raw) return sentenceCase(raw.replaceAll('_', ' '));
    return 'Market Tick';
}

export function uniqueAgentCount(simulator: SimulatorState | null): number {
    return new Set((simulator?.agent_orders ?? []).map((order) => order.agent_id)).size;
}

export function eventMove(event: SimulatorEvent | null): string {
    if (!event) return '-';
    const delta = event.close - event.open;
    const pct = event.open ? (delta / event.open) * 100 : 0;
    return `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)`;
}

export function marketImpact(event: SimulatorEvent | null): string {
    if (!event?.spread || !event.close) return '-';
    return `${((event.spread / event.close) * 100).toFixed(3)}%`;
}

export function latestScenario(data: ProductData): string {
    return data.simulator?.scenario_name ?? data.loopState?.loop?.proposal_name ?? '-';
}

export function marketRegime(prediction: SimulatorPrediction | null): string {
    const score = prediction?.risk_score ?? 0;
    if (score >= 0.75) return 'High Volatility';
    if (score >= 0.45) return 'Elevated';
    return 'Calm';
}

export function postureLabel(value: string | undefined): string {
    if (!value) return 'Monitoring';
    return sentenceCase(value.replaceAll('_', ' '));
}

export function riskLabel(value: number): string {
    if (value >= 0.75) return 'High Risk';
    if (value >= 0.55) return 'Elevated';
    return 'Low Risk';
}

export function toneForRisk(value: number): Tone {
    if (value >= 0.82) return 'red';
    if (value >= 0.55) return 'amber';
    return 'green';
}

export function metricFromExtra(metric: ModelMetric | undefined, key: string): unknown {
    return metric?.extra_metrics?.[key];
}

export function featureRowsFrom(
    caseFile: InvestigationCase | null,
    simulator: SimulatorState | null,
): Array<[string, number]> {
    const caseRows = Object.entries(caseFile?.feature_evidence ?? {}).map(
        ([key, value]) => [key, Number(value)] as [string, number],
    );
    if (caseRows.length) return caseRows.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    const snapshot = simulator?.feature_snapshots[simulator.feature_snapshots.length - 1];
    return Object.entries(snapshot?.features ?? {}).map(
        ([key, value]) => [key, Number(value)] as [string, number],
    );
}

export function timelineFromCase(
    caseFile: InvestigationCase,
): Array<{ title: string; time: string; detail: string; tone: Tone }> {
    const source = caseFile.timeline ?? [];
    if (source.length) {
        return source.slice(0, 5).map((item, index) => {
            const timestamp = String(item.timestamp ?? caseFile.created_at);
            return {
                title:
                    index === 0
                        ? 'Order submission rate spiked'
                        : String(item.policy_decision ?? 'Risk event observed'),
                time: formatClock(timestamp),
                detail: `Risk ${Number(item.risk_score ?? caseFile.confidence).toFixed(2)} · ${price(Number(item.close_price ?? 0))}`,
                tone: index < 2 ? 'green' : 'amber',
            };
        });
    }
    return [
        {
            title: 'Investigation case created',
            time: formatClock(caseFile.created_at),
            detail: shortId(caseFile.case_id),
            tone: 'green',
        },
    ];
}

export type BenchmarkSplitView = 'random' | 'heldout' | 'window' | 'scenarios';
export type ModelTab = 'trend' | 'scenario' | 'threshold' | 'calibration';

export function benchmarkSelectionTitle(view: BenchmarkSplitView): string {
    if (view === 'random') return 'Random Row Split';
    if (view === 'heldout') return 'Scenario-Family Held-Out Split';
    if (view === 'window') return 'Benchmark Window';
    return 'Scenarios';
}

export function benchmarkSelectionBody(
    view: BenchmarkSplitView,
    benchmark: BenchmarkMetric | null,
): string {
    if (view === 'random')
        return 'Showing IID sanity-check metrics from persisted benchmark and training records.';
    if (view === 'heldout')
        return 'Showing the primary generalization split used for promotion decisions.';
    if (view === 'window')
        return `Benchmark period: ${String(benchmark?.data.period ?? benchmark?.title ?? '-')}.`;
    return `Scenario coverage: ${String(benchmark?.data.tasks ?? '-')} tasks and ${metricValue(Number(benchmark?.data.examples))} examples.`;
}

export function modelTabTitle(tab: ModelTab): string {
    if (tab === 'trend') return 'Trend View';
    if (tab === 'scenario') return 'Scenario Breakdown';
    if (tab === 'threshold') return 'Threshold Analysis';
    return 'Calibration';
}

export function modelTabBody(tab: ModelTab, metricCount: number): string {
    if (tab === 'trend')
        return `${metricCount} persisted benchmark metric rows are visible in the table above.`;
    if (tab === 'scenario')
        return 'Scenario-family performance uses the held-out split where available.';
    if (tab === 'threshold')
        return 'Threshold analysis is limited to persisted benchmark evidence; no synthetic threshold rows are injected.';
    return 'Calibration view uses persisted model metrics only.';
}

export interface BenchmarkRow {
    metric: string;
    helper: string;
    active: string;
    candidate: string;
    delta: string;
    tone: Tone;
}

export function benchmarkRows(
    trainingRuns: TrainingRun[],
    modelMetrics: ModelMetric[],
): BenchmarkRow[] {
    const active = trainingRuns[0];
    const candidate = trainingRuns[1] ?? trainingRuns[0];
    const activeMetric = modelMetrics[0];
    const candidateMetric = modelMetrics[1] ?? modelMetrics[0];
    const rows = [
        {
            metric: 'Realized Markout Lift',
            helper: 'bps vs. always-quote baseline (higher is better)',
            a: Number(metricFromExtra(activeMetric, 'markout_lift_bps')),
            c: Number(metricFromExtra(candidateMetric, 'markout_lift_bps')),
            suffix: ' bps',
        },
        {
            metric: 'PR-AUC',
            helper: 'Precision-Recall AUC',
            a: active?.pr_auc ?? activeMetric?.pr_auc,
            c: candidate?.pr_auc ?? candidateMetric?.pr_auc,
        },
        {
            metric: 'ROC-AUC',
            helper: 'ROC AUC',
            a: activeMetric?.auroc ?? active?.recall,
            c: candidateMetric?.auroc ?? candidate?.recall,
        },
        {
            metric: 'F1',
            helper: 'F1 Score @ 0.5',
            a: active?.f1,
            c: candidate?.f1,
        },
        {
            metric: 'p95 Inference Latency',
            helper: 'Milliseconds (lower is better)',
            a: active?.lead_time_ms ?? activeMetric?.inference_latency_ms,
            c: candidate?.lead_time_ms ?? candidateMetric?.inference_latency_ms,
            lowerBetter: true,
            suffix: ' ms',
        },
    ].filter(
        (row) =>
            typeof row.a === 'number' &&
            Number.isFinite(row.a) &&
            typeof row.c === 'number' &&
            Number.isFinite(row.c),
    );
    return rows.map((row) => {
        const activeValue = Number(row.a);
        const candidateValue = Number(row.c);
        const delta = candidateValue - activeValue;
        const improved = row.lowerBetter ? delta <= 0 : delta >= 0;
        const suffix = row.suffix ?? '';
        return {
            metric: row.metric,
            helper: row.helper,
            active: `${activeValue.toFixed(activeValue > 10 ? 0 : 3)}${suffix}`,
            candidate: `${candidateValue.toFixed(candidateValue > 10 ? 0 : 3)}${suffix}`,
            delta: `${delta >= 0 ? '+' : ''}${delta.toFixed(Math.abs(delta) > 1 ? 0 : 3)}${suffix}`,
            tone: (improved ? 'green' : 'amber') as Tone,
        };
    });
}

export type MemoryCardShape = Pick<
    ImmuneMemory,
    | 'threat_name'
    | 'description'
    | 'key_signals'
    | 'best_detector'
    | 'failed_detector'
    | 'recommended_detector'
    | 'novelty_score'
    | 'times_seen'
    | 'example_case_id'
>;

export function memoryCards(realMemories: ImmuneMemory[]): MemoryCardShape[] {
    return realMemories.map((memory) => ({
        threat_name: memory.threat_name,
        description: memory.description,
        key_signals: memory.key_signals,
        best_detector: memory.best_detector,
        failed_detector: memory.failed_detector,
        recommended_detector: memory.recommended_detector,
        novelty_score: memory.novelty_score,
        times_seen: memory.times_seen,
        example_case_id: memory.example_case_id,
    }));
}

export function noveltyLabel(value: number): string {
    if (value >= 0.66) return 'High Novelty';
    if (value >= 0.33) return 'Medium Novelty';
    return 'Low Novelty';
}

export type MemoryTypeFilter =
    | 'all'
    | 'liquidation'
    | 'basis'
    | 'funding'
    | 'momentum'
    | 'iceberg'
    | 'other';
export type NoveltyFilter = 'high' | 'medium' | 'low';

export function noveltyBucket(value: number): NoveltyFilter {
    if (value >= 0.66) return 'high';
    if (value >= 0.33) return 'medium';
    return 'low';
}

type MemoryCategory = Exclude<MemoryTypeFilter, 'all'>;

/** Classify an adverse-selection memory into a single v2 episode family. */
function classifyMemory(
    memory: Pick<ImmuneMemory, 'threat_name' | 'description' | 'key_signals'>,
): MemoryCategory {
    const text =
        `${memory.threat_name} ${memory.description} ${memory.key_signals.join(' ')}`.toLowerCase();
    if (text.includes('liquidation')) return 'liquidation';
    if (text.includes('basis') || text.includes('oracle')) return 'basis';
    if (text.includes('funding')) return 'funding';
    if (text.includes('momentum')) return 'momentum';
    if (text.includes('iceberg')) return 'iceberg';
    return 'other';
}

export function memoryMatchesType(
    memory: Pick<ImmuneMemory, 'threat_name' | 'description' | 'key_signals'>,
    type: MemoryTypeFilter,
): boolean {
    if (type === 'all') return true;
    return classifyMemory(memory) === type;
}

export function memoryTypeCounts(memories: ImmuneMemory[]) {
    const counts: Record<MemoryCategory, number> = {
        liquidation: 0,
        basis: 0,
        funding: 0,
        momentum: 0,
        iceberg: 0,
        other: 0,
    };
    for (const memory of memories) {
        counts[classifyMemory(memory)] += 1;
    }
    return counts;
}

export function recommendedDetectorRate(memories: ImmuneMemory[]): string {
    if (!memories.length) return '-';
    const ready = memories.filter((memory) => Boolean(memory.recommended_detector)).length;
    return `${Math.round((ready / memories.length) * 100)}%`;
}

export interface AuditRow {
    time: string;
    agent: string;
    step: string;
    title: string;
    decision: string;
    control: string;
    confidence: number;
    artifacts: number;
    tools: number;
    observation: string;
    runId: string;
    durationMs: number;
    toolCalls: AgentToolCall[];
    artifactEntries: Array<[string, string]>;
}

export function auditRowsFrom(loop: LoopState['loop'] | null): AuditRow[] {
    if (!loop) return [];
    return loop.agent_runs.slice(0, 6).map((agent, index) => {
        const trace = agent.decision_traces[0];
        const decision =
            loop.decisions[index]?.recommended_action ?? trace?.decision ?? 'proceed';
        return {
            time: formatClock(agent.started_at),
            agent: agent.agent_name.replace('Agent', '').replace(/([a-z])([A-Z])/g, '$1 $2'),
            step: `Step ${index + 1} of ${Math.min(loop.agent_runs.length, 6)}`,
            title: trace?.goal || agent.goal,
            decision: sentenceCase(
                decision.includes('block')
                    ? 'Block'
                    : decision.includes('alert')
                      ? 'Escalate'
                      : 'Proceed',
            ),
            control: loop.decisions[index]?.recommended_action
                ? sentenceCase(loop.decisions[index].recommended_action)
                : '-',
            confidence: trace?.confidence ?? loop.decisions[index]?.confidence ?? 0,
            artifacts: Number(
                Object.keys(agent.linked_artifacts ?? {}).length || agent.trace_count || 0,
            ),
            tools: agent.tool_call_count,
            observation: trace?.observation ?? agent.goal,
            runId: agent.run_id,
            durationMs: agent.duration_ms,
            toolCalls: agent.tool_calls ?? [],
            artifactEntries: Object.entries(agent.linked_artifacts ?? {}).map(([key, value]) => [
                key,
                Array.isArray(value) ? value.join(', ') : String(value),
            ]),
        };
    });
}

export function exportTrace(
    loop: LoopState['loop'] | null,
    rows: AuditRow[],
    setNotice: (message: string) => void,
) {
    if (!loop) {
        setNotice('No persisted loop trace is available to export.');
        return;
    }
    const blob = new Blob([JSON.stringify({ loop_id: loop.loop_id, rows }, null, 2)], {
        type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `marketimmune-trace-${shortId(loop.loop_id)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    setNotice('Trace export generated from persisted loop data.');
}

export async function shareCurrentLink(setNotice: (message: string) => void) {
    try {
        await navigator.clipboard.writeText(window.location.href);
        setNotice('Audit link copied to clipboard.');
    } catch {
        setNotice('Clipboard access is unavailable in this browser.');
    }
}

// Re-export for downstream consumers.
export { clamp, formatDuration };
