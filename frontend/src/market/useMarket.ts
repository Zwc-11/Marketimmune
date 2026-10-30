import { useEffect, useState, useSyncExternalStore } from 'react';
import { marketFeed, type MarketSnapshot } from './feed';

/**
 * Subscribe to one slice of the live feed. Selectors must return a slice as-is
 * (e.g. `s => s.book`), not a freshly built object, so React can skip renders
 * when that slice did not change in a flush.
 */
export function useMarket<T>(selector: (snapshot: MarketSnapshot) => T): T {
    return useSyncExternalStore(
        marketFeed.subscribe,
        () => selector(marketFeed.getSnapshot()),
        () => selector(marketFeed.getSnapshot()),
    );
}

/** A clock for "age" readouts; ticks independently of feed traffic. */
export function useNow(intervalMs = 1_000): number {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
        return () => window.clearInterval(timer);
    }, [intervalMs]);
    return now;
}
