// Streaming order-flow imbalance, numerically identical to
// marketimmune.features.hyperliquid_features.l2_rows_with_ofi.
//
// Python computes each window as a difference of prefix sums over the whole day.
// Here only the last 10 s of events are kept (bounded replay): a window value is
// `cum_now - cum_before(first event inside the window)`, the same subtraction, so
// results match without holding history. parity.test.ts pins the equivalence.

export interface TopOfBookSizes {
    ts: number;
    bidPx: number;
    bidSz: number;
    askPx: number;
    askSz: number;
}

export interface OfiValues {
    event: number;
    ofi1s: number;
    ofi5s: number;
    ofi10s: number;
}

const WINDOWS = [1_000, 5_000, 10_000] as const;
const MAX_WINDOW = WINDOWS[WINDOWS.length - 1];

export function normalizedOfiEvent(prev: TopOfBookSizes, cur: TopOfBookSizes): number {
    const bidPressure =
        (cur.bidPx >= prev.bidPx ? cur.bidSz : 0) - (cur.bidPx <= prev.bidPx ? prev.bidSz : 0);
    const askPressure =
        (cur.askPx >= prev.askPx ? prev.askSz : 0) - (cur.askPx <= prev.askPx ? cur.askSz : 0);
    const denominator = prev.bidSz + prev.askSz + cur.bidSz + cur.askSz;
    if (denominator <= 0) return 0;
    return (bidPressure + askPressure) / denominator;
}

export class OfiWindows {
    private times: number[] = [];
    private cumBefore: number[] = [];
    private head = 0;
    private cum = 0;
    private prev: TopOfBookSizes | null = null;

    /** Push the next snapshot (non-decreasing ts) and return its OFI values. */
    push(book: TopOfBookSizes): OfiValues {
        const event = this.prev === null ? 0 : normalizedOfiEvent(this.prev, book);
        this.prev = book;
        this.times.push(book.ts);
        this.cumBefore.push(this.cum);
        this.cum += event;
        this.evictBefore(book.ts - MAX_WINDOW);
        return {
            event,
            ofi1s: this.window(book.ts, WINDOWS[0]),
            ofi5s: this.window(book.ts, WINDOWS[1]),
            ofi10s: this.window(book.ts, WINDOWS[2]),
        };
    }

    get size(): number {
        return this.times.length - this.head;
    }

    private window(ts: number, span: number): number {
        // First retained event with time >= ts - span (bisect_left semantics).
        let lo = this.head;
        let hi = this.times.length;
        const target = ts - span;
        while (lo < hi) {
            const mid = (lo + hi) >>> 1;
            if (this.times[mid] < target) lo = mid + 1;
            else hi = mid;
        }
        return this.cum - this.cumBefore[lo];
    }

    private evictBefore(cutoff: number): void {
        while (this.head < this.times.length && this.times[this.head] < cutoff) this.head += 1;
        if (this.head > 4096 && this.head * 2 > this.times.length) {
            this.times = this.times.slice(this.head);
            this.cumBefore = this.cumBefore.slice(this.head);
            this.head = 0;
        }
    }
}
