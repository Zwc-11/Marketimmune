import { useEffect, useState, useSyncExternalStore } from 'react';
import { marketFeed, type MarketSnapshot } from './feed';

/**
 * Subscribe to one slice of the live feed. Selectors must return a slice as-is
 * (e.g. `s => s.book`), not a freshly built object, so React can skip renders
 * when that slice did not change in a flush.
 */
export function useMarket<T>(selector: (snapshot: MarketSnapshot) => T): T {
    const select = () => selector(marketFeed.getSnapshot());
    return useSyncExternalStore(marketFeed.subscribe, select, select);
}

/** A 1 s clock for "age" readouts; ticks independently of feed traffic. */
export function useNow(): number {
    const [now, setNow] = useState(Date.now);
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1_000);
        return () => window.clearInterval(timer);
    }, []);
    return now;
}
