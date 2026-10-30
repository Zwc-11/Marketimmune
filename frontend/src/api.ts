import type {
    HyperliquidBackfillJobPayload,
    MarkoutFillDecisionPayload,
    MarkoutModelHealth,
} from './types';

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

export async function fetchMarkoutModelHealth(): Promise<MarkoutModelHealth> {
    return request<MarkoutModelHealth>(API.markoutModelHealth);
}

export async function fetchMarkoutFillDecisions(): Promise<MarkoutFillDecisionPayload> {
    return request<MarkoutFillDecisionPayload>(API.markoutFillDecisions);
}

export async function fetchHyperliquidBackfillJobs(): Promise<HyperliquidBackfillJobPayload> {
    return request<HyperliquidBackfillJobPayload>(API.hyperliquidBackfills);
}

export async function probeApi(): Promise<boolean> {
    try {
        const resp = await fetch(API.markoutModelHealth, { method: 'HEAD' });
        if (resp.status === 503) return false;
        return resp.ok || resp.status === 405;
    } catch {
        return false;
    }
}
