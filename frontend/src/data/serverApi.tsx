// The optional Django API (server/api/views.py): promoted-model health, scored Gold
// fills and backfill jobs. Read-only GETs, polled; the terminal and the model report
// work without it. Response types list only the fields the UI reads.

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { SERVER_POLL_MS } from '../config';

const HEALTH_URL = '/api/markout-model/health/';
const DECISIONS_URL = '/api/markout-model/decisions/';
const BACKFILLS_URL = '/api/hyperliquid/backfill-jobs/';

interface MarkoutModelHealth {
    available: boolean;
    message?: string;
    model_name?: string;
    dataset_label?: string;
    cv_scheme?: string;
    decision_threshold?: number | null;
    smoke_latency?: { p50_ms: number; p95_ms: number };
}

interface MarkoutFillDecision {
    decision_id: string;
    ts_ms: number;
    px: number;
    sz: number;
    maker_side: number;
    calibrated_score: number;
    action: string;
    markout_bps: number | null;
    toxic: boolean | null;
    top_features: string[];
}

interface MarkoutFillDecisionPayload {
    available: boolean;
    message: string;
    decisions: MarkoutFillDecision[];
}

export interface HyperliquidBackfillJob {
    job_id: string;
    status: 'running' | 'succeeded' | 'failed' | 'planned';
    coin: string;
    date: string;
    book_snapshots: number;
    fills: number;
    training_rows: number;
    message: string;
    duration_ms: number;
}

interface HyperliquidBackfillJobPayload {
    jobs: HyperliquidBackfillJob[];
}

interface ServerData {
    status: 'checking' | 'online' | 'offline';
    /** Each slice is null when its request failed. */
    model: MarkoutModelHealth | null;
    decisions: MarkoutFillDecisionPayload | null;
    backfills: HyperliquidBackfillJobPayload | null;
}

const EMPTY: ServerData = { status: 'checking', model: null, decisions: null, backfills: null };
const OFFLINE: ServerData = { ...EMPTY, status: 'offline' };

const Context = createContext<ServerData | null>(null);

/** Django is down when the dev proxy answers 503 (vite.config.ts), a static host 404s, or fetch fails. */
async function apiIsUp(): Promise<boolean> {
    const response = await fetch(HEALTH_URL, { method: 'HEAD' }).catch(() => null);
    return response !== null && (response.ok || response.status === 405);
}

async function getJson<T>(url: string): Promise<T> {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return (await response.json()) as T;
}

async function load(): Promise<ServerData> {
    if (!(await apiIsUp())) return OFFLINE;
    const [model, decisions, backfills] = await Promise.allSettled([
        getJson<MarkoutModelHealth>(HEALTH_URL),
        getJson<MarkoutFillDecisionPayload>(DECISIONS_URL),
        getJson<HyperliquidBackfillJobPayload>(BACKFILLS_URL),
    ]);
    const value = <T,>(result: PromiseSettledResult<T>) => (result.status === 'fulfilled' ? result.value : null);
    return { status: 'online', model: value(model), decisions: value(decisions), backfills: value(backfills) };
}

export function ServerApiProvider({ children }: { children: ReactNode }) {
    const [data, setData] = useState(EMPTY);
    useEffect(() => {
        const refresh = () => void load().then(setData);
        refresh();
        const timer = window.setInterval(() => {
            if (!document.hidden) refresh();
        }, SERVER_POLL_MS);
        return () => window.clearInterval(timer);
    }, []);
    return <Context.Provider value={data}>{children}</Context.Provider>;
}

export function useServerApi(): ServerData {
    const value = useContext(Context);
    if (!value) throw new Error('useServerApi must be used inside ServerApiProvider');
    return value;
}
