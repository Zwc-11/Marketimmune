import type { HyperliquidCandle, SimulatorEvent } from '../types';

export type ChartTimeframe = '1m' | '5m' | '15m' | '1h' | '4h' | '1d';

export const CHART_TIMEFRAMES: ChartTimeframe[] = ['1m', '5m', '15m', '1h', '4h', '1d'];

const BAR_FACTOR: Record<ChartTimeframe, number> = {
    '1m': 1,
    '5m': 5,
    '15m': 15,
    '1h': 60,
    '4h': 240,
    '1d': 1440,
};

export function timeframeBarFactor(timeframe: ChartTimeframe): number {
    return BAR_FACTOR[timeframe];
}

/** Aggregate 1m replay bars into a coarser timeframe for chart display. */
export function aggregateReplayEvents(
    events: SimulatorEvent[],
    timeframe: ChartTimeframe,
): SimulatorEvent[] {
    const factor = timeframeBarFactor(timeframe);
    if (factor <= 1 || events.length === 0) return events;

    const buckets: SimulatorEvent[] = [];
    for (let index = 0; index < events.length; index += factor) {
        const chunk = events.slice(index, index + factor);
        if (!chunk.length) continue;
        const last = chunk[chunk.length - 1];
        buckets.push({
            ...last,
            id: `${last.id}-${index}`,
            open: chunk[0].open,
            high: Math.max(...chunk.map((event) => event.high)),
            low: Math.min(...chunk.map((event) => event.low)),
            close: last.close,
            volume: chunk.reduce((sum, event) => sum + event.volume, 0),
        });
    }
    return buckets;
}

export function aggregateLiveCandles(
    candles: HyperliquidCandle[],
    timeframe: ChartTimeframe,
): HyperliquidCandle[] {
    const factor = timeframeBarFactor(timeframe);
    if (factor <= 1 || candles.length === 0) return candles;

    const buckets: HyperliquidCandle[] = [];
    for (let index = 0; index < candles.length; index += factor) {
        const chunk = candles.slice(index, index + factor);
        if (!chunk.length) continue;
        const first = chunk[0];
        const last = chunk[chunk.length - 1];
        buckets.push({
            ...last,
            open_ts_ms: first.open_ts_ms,
            close_ts_ms: last.close_ts_ms,
            open: first.open,
            high: Math.max(...chunk.map((candle) => candle.high)),
            low: Math.min(...chunk.map((candle) => candle.low)),
            close: last.close,
            volume: chunk.reduce((sum, candle) => sum + candle.volume, 0),
            trade_count: chunk.reduce((sum, candle) => sum + candle.trade_count, 0),
        });
    }
    return buckets;
}

export function chartWindowSize(timeframe: ChartTimeframe): number {
    if (timeframe === '1d') return 48;
    if (timeframe === '4h') return 72;
    if (timeframe === '1h') return 96;
    return 120;
}
