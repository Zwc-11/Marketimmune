import type {
    BenchmarkMetric,
    HyperliquidBackfillJobPayload,
    HyperliquidCandleSeries,
    HyperliquidLiveSnapshot,
    LLMStatus,
    MarkoutFillDecisionPayload,
    LoopState,
    MarkoutModelHealth,
    ModelMetric,
    TrainingRun,
} from './types';
import { LIVE_MARKET_CONFIG } from './config';

export class ApiError extends Error {
    status: number;
    code?: string;

    constructor(message: string, status: number, code?: string) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
    }
}

const API = {
    state: '/api/agentic/state/',
    llmStatus: '/api/agentic/llm-status/',
    runLoop: '/api/agentic/run/',
    modelMetrics: '/api/model-metrics/',
    benchmarkMetrics: '/api/benchmark-metrics/',
    trainingRuns: '/api/training-runs/',
    hyperliquidLive: '/api/hyperliquid/live/',
    hyperliquidCandles: '/api/hyperliquid/candles/',
    hyperliquidBackfills: '/api/hyperliquid/backfill-jobs/',
    markoutModelHealth: '/api/markout-model/health/',
    markoutFillDecisions: '/api/markout-model/decisions/',
};

function getCookie(name: string): string | null {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : null;
}

async function parseError(resp: Response): Promise<ApiError> {
    let message = `HTTP ${resp.status} ${resp.statusText}`;
    let code: string | undefined;
    try {
        const body = (await resp.json()) as { error?: string; code?: string; detail?: string };
        message = body.error || body.detail || message;
        code = body.code;
    } catch {
        /* keep default message */
    }
    return new ApiError(message, resp.status, code);
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
    const headers = new Headers(init?.headers);
    if (init?.method === 'POST' && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }
    const csrf = getCookie('csrftoken');
    if (csrf && init?.method && init.method !== 'GET') {
        headers.set('X-CSRFToken', csrf);
    }

    const resp = await fetch(url, { ...init, headers });
    if (!resp.ok) {
        throw await parseError(resp);
    }
    return (await resp.json()) as T;
}

function unpackList<T>(payload: T[] | { results?: T[] }): T[] {
    return Array.isArray(payload) ? payload : payload.results ?? [];
}

export async function fetchState(): Promise<LoopState> {
    return request<LoopState>(API.state);
}

export async function fetchLLMStatus(): Promise<LLMStatus> {
    return request<LLMStatus>(API.llmStatus);
}

export interface RunLoopResponse {
    loop_id: string;
    aggregate_posture: string;
    alert_count: number;
    case_count: number;
    new_memory_count: number;
    duration_ms: number;
    proposal_name: string;
}

export async function runLoop(
    difficulty: 'easy' | 'medium' | 'hard',
    limit = 30,
): Promise<RunLoopResponse> {
    return request<RunLoopResponse>(API.runLoop, {
        method: 'POST',
        body: JSON.stringify({ difficulty, limit }),
    });
}

export async function fetchModelMetrics(): Promise<ModelMetric[]> {
    return unpackList(await request<ModelMetric[] | { results?: ModelMetric[] }>(API.modelMetrics));
}

export async function fetchBenchmarkMetrics(): Promise<BenchmarkMetric[]> {
    return unpackList(
        await request<BenchmarkMetric[] | { results?: BenchmarkMetric[] }>(API.benchmarkMetrics),
    );
}

export async function fetchTrainingRuns(): Promise<TrainingRun[]> {
    return unpackList(await request<TrainingRun[] | { results?: TrainingRun[] }>(API.trainingRuns));
}

export async function fetchMarkoutModelHealth(): Promise<MarkoutModelHealth> {
    return request<MarkoutModelHealth>(API.markoutModelHealth);
}

export async function fetchMarkoutFillDecisions(): Promise<MarkoutFillDecisionPayload> {
    return request<MarkoutFillDecisionPayload>(API.markoutFillDecisions);
}

export async function fetchHyperliquidBackfillJobs(): Promise<HyperliquidBackfillJobPayload> {
    return request<HyperliquidBackfillJobPayload>(API.hyperliquidBackfills);
}

export async function fetchHyperliquidLive(
    budgetMs = LIVE_MARKET_CONFIG.requestBudgetMs,
): Promise<HyperliquidLiveSnapshot> {
    const started = performance.now();
    const params = new URLSearchParams();
    if (budgetMs !== undefined) params.set('budget_ms', String(budgetMs));
    const suffix = params.size ? `?${params.toString()}` : '';
    const snapshot = await request<HyperliquidLiveSnapshot>(
        `${API.hyperliquidLive}${suffix}`,
    );
    return { ...snapshot, client_elapsed_ms: Number((performance.now() - started).toFixed(3)) };
}

export async function fetchHyperliquidCandles(
    interval: string,
    lookbackMinutes: number,
    budgetMs = LIVE_MARKET_CONFIG.requestBudgetMs,
): Promise<HyperliquidCandleSeries> {
    const started = performance.now();
    const params = new URLSearchParams({
        interval,
        lookback_minutes: String(lookbackMinutes),
    });
    if (budgetMs !== undefined) params.set('budget_ms', String(budgetMs));
    const series = await request<HyperliquidCandleSeries>(
        `${API.hyperliquidCandles}?${params.toString()}`,
    );
    return { ...series, client_elapsed_ms: Number((performance.now() - started).toFixed(3)) };
}

export async function probeApi(): Promise<boolean> {
    try {
        const resp = await fetch(API.llmStatus, { method: 'HEAD' });
        if (resp.status === 503) return false;
        return resp.ok || resp.status === 405;
    } catch {
        return false;
    }
}
