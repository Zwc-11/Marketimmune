import type { LLMStatus, LoopState, SimulatorState } from './types';

// All requests are relative URLs so the same code works in:
//   * `npm run dev` (Vite dev server proxies `/api/...` -> Django :8000)
//   * production (Django serves the bundle and the API on the same origin)
const API = {
    state: '/api/agentic/state/',
    llmStatus: '/api/agentic/llm-status/',
    runLoop: '/api/agentic/run/',
    simulatorState: '/api/simulator/state/',
    simulatorControl: '/api/simulator/control/',
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
    const resp = await fetch(url, init);
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }
    return (await resp.json()) as T;
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ difficulty, limit }),
    });
}

export interface SimulatorControlRequest {
    scenario: string;
    date: string;
    limit: number;
    speed: number;
    symbol?: string;
}

export async function fetchSimulatorState(): Promise<SimulatorState> {
    return request<SimulatorState>(API.simulatorState);
}

export async function startSimulatorReplay(payload: SimulatorControlRequest): Promise<void> {
    const resp = await request<{ status: string; message?: string }>(API.simulatorControl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (resp.status === 'error') {
        throw new Error(resp.message || 'Simulator controller failed');
    }
}
