// Live state of a paper-trading run (`python -m marketimmune.cli.paper_trade --serve 8765`).
// The run serves /state.json; when the terminal is served by the run itself it is same-origin,
// and from the Vite dev server it is read from the run's port.

import { useEffect, useRef, useState } from 'react';

export interface PaperQuote {
    px: number;
    queue: number | null;
    live: boolean;
}

export interface PaperStrategy {
    strategy: string;
    pnl: number;
    fills: number;
    notional: number;
    actions: number;
    gross_usd: number;
    bps: number | null;
    per_hour: number | null;
    actions_per_min: number | null;
    candidate: boolean;
}

export interface PaperCoin {
    coin: string;
    mid: number | null;
    spread_bps: number | null;
    gap_bps: number | null;
    gap_z: number | null;
    forecast_10s_bps: number | null;
    model_1s_bps: number | null;
    sigma_1s_bps: number | null;
    buy_burst: number | null;
    sell_burst: number | null;
    positions: Record<string, number>;
    pnl: Record<string, number>;
}

export interface PaperDecision {
    coin: string;
    strategy: string;
    bid: PaperQuote | null;
    ask: PaperQuote | null;
    position_usd: number;
    reason: string;
}

export interface PaperLogEntry {
    t_ms: number;
    coin: string;
    strategy: string;
    sides: 'both' | 'bid' | 'ask' | 'none';
    reason: string;
}

export interface PaperFill {
    t_ms: number;
    coin: string;
    strategy: string;
    side: number;
    px: number;
    usd: number;
}

export interface PaperState {
    now_ms: number;
    started_ms: number | null;
    hours: number;
    segment: number;
    last_event_ms: number | null;
    feed_delay_ms: Record<string, number[]>;
    reconnects: number;
    settings: {
        latency_ms?: number;
        strategies?: string[];
        registered?: string[];
        quote_usd?: number;
        max_quotes?: number;
        budget_usd?: number | null;
        fees_bps?: { maker: number; taker: number };
    };
    strategies: PaperStrategy[];
    coins: PaperCoin[];
    history: Record<string, [number, number][]>;
    /** Each coin's Hyperliquid mid with the PnL history (runs from 2026-11-06 on). */
    prices?: Record<string, [number, number][]>;
    /** The live clock correction: this machine's clock against Coinbase's timestamps. */
    clock?: { corrected?: boolean; offset_ms?: number; measured_ms?: number | null };
    tape: PaperFill[];
    decisions: PaperDecision[];
    decision_log: PaperLogEntry[];
}

export const PAPER_POLL_MS = 1_000;
const SOURCES = ['state.json', 'http://127.0.0.1:8765/state.json'];

export type PaperStatus = { kind: 'connecting' } | { kind: 'offline' } | { kind: 'live'; state: PaperState };

/** Poll the run once a second; remembers which source answered. */
export function usePaperState(): PaperStatus {
    const [status, setStatus] = useState<PaperStatus>({ kind: 'connecting' });
    const source = useRef(0);
    useEffect(() => {
        let alive = true;
        let misses = 0;
        const poll = async () => {
            for (let i = 0; i < SOURCES.length; i++) {
                const k = (source.current + i) % SOURCES.length;
                try {
                    const res = await fetch(SOURCES[k], { cache: 'no-store' });
                    if (!res.ok) continue;
                    const state = (await res.json()) as PaperState;
                    if (!Array.isArray(state.strategies)) continue;
                    source.current = k;
                    misses = 0;
                    if (alive) setStatus({ kind: 'live', state });
                    return;
                } catch {
                    /* try the next source */
                }
            }
            misses += 1;
            if (alive && misses >= 2) setStatus({ kind: 'offline' });
        };
        void poll();
        const timer = window.setInterval(poll, PAPER_POLL_MS);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, []);
    return status;
}

export const REGISTERED = ['improve+gap@0.25', 'gap@0.25', 'improve+gap@0.5', 'gap@0.5'];
export const ADVANCED_PREFIXES = ['zgap@', 'hawkes@', 'kelly@', 'reservation@'];

/** The run's registered strategies (from its settings), else the 24-hour confirmation's. */
export function registeredOf(state: PaperState): string[] {
    return state.settings.registered?.length ? state.settings.registered : REGISTERED;
}

export function strategyGroup(name: string, registered: string[] = REGISTERED): 'candidate' | 'control' | 'advanced' | 'baseline' {
    if (registered.includes(name)) return 'candidate';
    if (name === 'touch') return 'control';
    if (ADVANCED_PREFIXES.some((p) => name.startsWith(p))) return 'advanced';
    return 'baseline';
}

export const STRATEGY_COLORS: Record<string, string> = {
    'improve+gap@0.25': '#5aa9ff',
    'gap@0.25': '#1fb873',
    'improve+gap@0.5': '#b892ff',
    'gap@0.5': '#e8b04a',
    touch: '#9ea9b4',
    'zgap@0.25': '#4fd1c5',
    'kelly@0.5': '#f78fb3',
    'reservation@1': '#ffd166',
    'hawkes@3': '#ff9f68',
};

const PRICE_POINTS = 4_000;

/** One coin's mid over the run: the server's history when it keeps one, else what this page has
 * seen since it opened (a run started before the price history existed), taken at the PnL
 * history's own sample times so the chart's time axis gains no extra points. */
export function useCoinPrices(state: PaperState | null, coin: string): [number, number][] {
    const seen = useRef<[number, number][]>([]);
    const served = state?.prices?.[coin];
    if (state && !served) {
        const mid = state.coins.find((c) => c.coin === coin)?.mid;
        let t = -Infinity;
        for (const h of Object.values(state.history)) {
            const last = h[h.length - 1];
            if (last && last[0] > t) t = last[0];
        }
        const prev = seen.current[seen.current.length - 1];
        if (mid !== null && mid !== undefined && Number.isFinite(t) && (!prev || t > prev[0])) {
            seen.current.push([t, mid]);
            if (seen.current.length > PRICE_POINTS) seen.current.splice(0, seen.current.length - PRICE_POINTS);
        }
    }
    return served ?? seen.current;
}

const PALETTE = ['#5aa9ff', '#1fb873', '#b892ff', '#e8b04a', '#4fd1c5', '#f78fb3', '#ffd166', '#ff9f68'];

/** Line colours: the registered strategies take the palette in order, the rest keep their own. */
export function strategyColors(registered: string[]): Record<string, string> {
    const out: Record<string, string> = { ...STRATEGY_COLORS };
    registered.forEach((name, i) => {
        if (!REGISTERED.includes(name)) out[name] = PALETTE[i % PALETTE.length];
    });
    return out;
}
