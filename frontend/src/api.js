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
async function request(url, init) {
    const resp = await fetch(url, init);
    if (!resp.ok) {
        throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }
    return (await resp.json());
}
export async function fetchState() {
    return request(API.state);
}
export async function fetchLLMStatus() {
    return request(API.llmStatus);
}
export async function runLoop(difficulty, limit = 30) {
    return request(API.runLoop, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ difficulty, limit }),
    });
}
export async function fetchSimulatorState() {
    return request(API.simulatorState);
}
export async function startSimulatorReplay(payload) {
    const resp = await request(API.simulatorControl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (resp.status === 'error') {
        throw new Error(resp.message || 'Simulator controller failed');
    }
}
