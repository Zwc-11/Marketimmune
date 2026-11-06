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
    settings: { latency_ms?: number; strategies?: string[]; fees_bps?: { maker: number; taker: number } };
    strategies: PaperStrategy[];
    coins: PaperCoin[];
    history: Record<string, [number, number][]>;
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

export function strategyGroup(name: string): 'candidate' | 'control' | 'advanced' | 'baseline' {
    if (REGISTERED.includes(name)) return 'candidate';
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
