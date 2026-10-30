import { describe, expect, it } from 'vitest';
import { RegretTracker } from './regret';

function fill(id: string, time: number, px: number, makerSide: 1 | -1, action: 'quote' | 'withhold' | null) {
    return { id, time, px, sz: 1, makerSide, score: action ? 0.5 : null, action };
}

describe('RegretTracker', () => {
    it('resolves on the first mid at or after fill time + horizon', () => {
        const tracker = new RegretTracker(10_000, 1, 300_000);
        tracker.add(fill('a', 1_000, 100, 1, null));
        expect(tracker.onMid(10_999, 99)).toEqual([]);
        const [done] = tracker.onMid(11_000, 99.98);
        expect(done.markoutBps).toBeCloseTo(-2, 9);
        expect(done.regret).toBe(true);
    });

    it('uses the fee hurdle: -0.5 bps is not a regret at 1 bps fee', () => {
        const tracker = new RegretTracker(10_000, 1, 300_000);
        tracker.add(fill('b', 0, 100, -1, null));
        const [done] = tracker.onMid(10_000, 100.005);
        expect(done.markoutBps).toBeCloseTo(-0.5, 9);
        expect(done.regret).toBe(false);
    });

    it('scores the skip policy the way the trainer does', () => {
        const tracker = new RegretTracker(10_000, 1, 300_000);
        tracker.add(fill('q', 0, 100, 1, 'quote')); // maker bought: +2 bps
        tracker.add(fill('w', 0, 100, -1, 'withhold')); // maker sold: -2 bps, a regret
        tracker.onMid(10_000, 100.02);
        const stats = tracker.stats(10_000);
        expect(stats.quoteAllBps).toBeCloseTo(0, 9);
        expect(stats.policyBps).toBeCloseTo(1, 9);
        expect(stats.liftBps).toBeCloseTo(1, 9);
        expect(stats.withheld).toBe(1);
        expect(stats.withholdPrecision).toBe(1);
        expect(stats.regretRecall).toBe(1);
    });

    it('drops resolved fills older than the stats window', () => {
        const tracker = new RegretTracker(10_000, 1, 60_000);
        tracker.add(fill('old', 0, 100, 1, null));
        tracker.onMid(10_000, 100);
        expect(tracker.stats(10_000).resolved).toBe(1);
        expect(tracker.stats(70_001).resolved).toBe(0);
    });

    it('drops only fills due before the first mid it holds', () => {
        const tracker = new RegretTracker(10_000, 1, 60_000);
        tracker.add(fill('stale', 0, 100, 1, null));
        tracker.add(fill('fresh', 9_000, 100, 1, null));
        expect(tracker.dropPending(15_000).map((f) => f.id)).toEqual(['stale']);
        expect(tracker.onMid(19_000, 100).map((f) => f.id)).toEqual(['fresh']);
    });

    it('drops pending fills on request and never resolves them', () => {
        const tracker = new RegretTracker(10_000, 1, 60_000);
        tracker.add(fill('gap', 0, 100, 1, null));
        expect(tracker.dropPending().map((f) => f.id)).toEqual(['gap']);
        expect(tracker.onMid(20_000, 101)).toEqual([]);
        expect(tracker.stats(20_000).pending).toBe(0);
    });
});
