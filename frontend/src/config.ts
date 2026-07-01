function numberEnv(name: string, fallback: number, min = 0): number {
    const raw = import.meta.env[name];
    if (raw === undefined || raw === '') return fallback;
    const value = Number(raw);
    return Number.isFinite(value) && value >= min ? value : fallback;
}

function optionalNumberEnv(name: string, min = 0): number | undefined {
    const raw = import.meta.env[name];
    if (raw === undefined || raw === '') return undefined;
    const value = Number(raw);
    return Number.isFinite(value) && value >= min ? value : undefined;
}

function stringEnv(name: string, fallback: string): string {
    const raw = import.meta.env[name];
    return raw === undefined || raw.trim() === '' ? fallback : raw.trim();
}

export const LIVE_MARKET_CONFIG = {
    requestBudgetMs: optionalNumberEnv('VITE_MARKETIMMUNE_HYPERLIQUID_BUDGET_MS', 1),
    marketPollMs: numberEnv('VITE_MARKETIMMUNE_HYPERLIQUID_POLL_MS', 5000, 250),
    candlePollMs: numberEnv('VITE_MARKETIMMUNE_HYPERLIQUID_CANDLE_POLL_MS', 30000, 1000),
    candleInterval: stringEnv('VITE_MARKETIMMUNE_HYPERLIQUID_CANDLE_INTERVAL', '1m'),
    candleLookbackMinutes: numberEnv(
        'VITE_MARKETIMMUNE_HYPERLIQUID_CANDLE_LOOKBACK_MINUTES',
        240,
        1,
    ),
} as const;
