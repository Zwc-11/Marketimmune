// The live label. A maker fill at price p on side s is resolved by the first mid
// printed at or after fill_time + horizon:
//     markout_bps = s * (mid - p) / p * 1e4,  regretted when markout < -fee_bps
// which is marketimmune.labels.markout.realized_markout_bps + is_toxic.

export interface TapeFill {
    id: string;
    time: number;
    px: number;
    sz: number;
    makerSide: 1 | -1;
    dueAt: number;
    score: number | null;
    action: 'quote' | 'withhold' | null;
    markoutBps: number | null;
    regret: boolean | null;
}

export interface ResolvedFill extends TapeFill {
    markoutBps: number;
    regret: boolean;
}

export interface RegretStats {
    windowMs: number;
    resolved: number;
    pending: number;
    regretRate: number | null;
    meanMarkoutBps: number | null;
    scored: number;
    withheld: number;
    /** Mean per-fill markout if every scored fill had been quoted. */
    quoteAllBps: number | null;
    /** Mean per-fill markout when withheld fills contribute 0 (the training policy). */
    policyBps: number | null;
    liftBps: number | null;
    withholdPrecision: number | null;
    regretRecall: number | null;
}

export class RegretTracker {
    /** Sorted by dueAt. */
    private pending: TapeFill[] = [];
    /** Sorted by fill time; trimmed to the stats window. */
    private readonly resolved: ResolvedFill[] = [];

    constructor(
        private readonly horizonMs: number,
        private readonly feeBps: number,
        private readonly windowMs: number,
    ) {}

    add(fill: Omit<TapeFill, 'dueAt' | 'markoutBps' | 'regret'>): TapeFill {
        const entry: TapeFill = { ...fill, dueAt: fill.time + this.horizonMs, markoutBps: null, regret: null };
        // Fills arrive in time order; keep the queue sorted by dueAt regardless.
        let at = this.pending.length;
        while (at > 0 && this.pending[at - 1].dueAt > entry.dueAt) at -= 1;
        this.pending.splice(at, 0, entry);
        return entry;
    }

    /** Resolve every fill whose horizon has elapsed by this mid's timestamp. */
    onMid(time: number, mid: number): ResolvedFill[] {
        let count = 0;
        while (count < this.pending.length && this.pending[count].dueAt <= time) count += 1;
        if (count === 0) return [];
        const done = this.pending.splice(0, count).map((fill): ResolvedFill => {
            const markoutBps = (fill.makerSide * (mid - fill.px)) / fill.px * 10_000;
            return { ...fill, markoutBps, regret: markoutBps < -this.feeBps };
        });
        this.resolved.push(...done);
        this.trim(time);
        return done;
    }

    /**
     * Forget fills that can no longer be resolved honestly: all of them after a feed
     * gap, or those due before `dueBefore` when the book stream starts later than
     * their horizon (the first mid we hold would not be the mid at t + horizon).
     */
    dropPending(dueBefore = Number.POSITIVE_INFINITY): TapeFill[] {
        const dropped = this.pending.filter((fill) => fill.dueAt < dueBefore);
        this.pending = this.pending.filter((fill) => fill.dueAt >= dueBefore);
        return dropped;
    }

    /** One pass over the window, no allocation. */
    stats(now: number): RegretStats {
        this.trim(now);
        let regrets = 0;
        let markoutSum = 0;
        let scored = 0;
        let scoredRegrets = 0;
        let withheld = 0;
        let withheldRegrets = 0;
        let quoteAllSum = 0;
        let policySum = 0;
        for (const fill of this.resolved) {
            markoutSum += fill.markoutBps;
            if (fill.regret) regrets += 1;
            if (fill.action === null) continue;
            scored += 1;
            quoteAllSum += fill.markoutBps;
            if (fill.regret) scoredRegrets += 1;
            if (fill.action === 'withhold') {
                withheld += 1;
                if (fill.regret) withheldRegrets += 1;
            } else {
                policySum += fill.markoutBps;
            }
        }
        const resolved = this.resolved.length;
        const quoteAll = scored ? quoteAllSum / scored : null;
        const policy = scored ? policySum / scored : null;
        return {
            windowMs: this.windowMs,
            resolved,
            pending: this.pending.length,
            regretRate: resolved ? regrets / resolved : null,
            meanMarkoutBps: resolved ? markoutSum / resolved : null,
            scored,
            withheld,
            quoteAllBps: quoteAll,
            policyBps: policy,
            liftBps: quoteAll === null || policy === null ? null : policy - quoteAll,
            withholdPrecision: withheld ? withheldRegrets / withheld : null,
            regretRecall: scoredRegrets ? withheldRegrets / scoredRegrets : null,
        };
    }

    private trim(now: number): void {
        const cutoff = now - this.windowMs;
        let drop = 0;
        while (drop < this.resolved.length && this.resolved[drop].time < cutoff) drop += 1;
        if (drop) this.resolved.splice(0, drop);
    }
}
