// The live label. A maker fill at price p on side s is resolved by the first mid
// printed at or after fill_time + horizon:
//     markout_bps = s * (mid - p) / p * 1e4,  regretted when markout < -fee_bps
// which is marketimmune.labels.markout.realized_markout_bps + is_toxic.

export type MakerSide = 1 | -1;
export type QuoteAction = 'quote' | 'withhold';

export interface TapeFill {
    id: string;
    time: number;
    px: number;
    sz: number;
    makerSide: MakerSide;
    dueAt: number;
    score: number | null;
    action: QuoteAction | null;
    markoutBps: number | null;
    regret: boolean | null;
    resolvedAt: number | null;
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
    private pending: TapeFill[] = [];
    private resolved: TapeFill[] = [];

    constructor(
        private readonly horizonMs: number,
        private readonly feeBps: number,
        private readonly windowMs: number,
    ) {}

    add(fill: Omit<TapeFill, 'dueAt' | 'markoutBps' | 'regret' | 'resolvedAt'>): TapeFill {
        const entry: TapeFill = {
            ...fill,
            dueAt: fill.time + this.horizonMs,
            markoutBps: null,
            regret: null,
            resolvedAt: null,
        };
        // Fills arrive in time order; keep the queue sorted by dueAt regardless.
        let at = this.pending.length;
        while (at > 0 && this.pending[at - 1].dueAt > entry.dueAt) at -= 1;
        this.pending.splice(at, 0, entry);
        return entry;
    }

    /** Resolve every fill whose horizon has elapsed by this mid's timestamp. */
    onMid(time: number, mid: number): TapeFill[] {
        let count = 0;
        while (count < this.pending.length && this.pending[count].dueAt <= time) count += 1;
        if (count === 0) return [];
        const due = this.pending.splice(0, count);
        const done = due.map((fill) => {
            const markoutBps = (fill.makerSide * (mid - fill.px)) / fill.px * 10_000;
            return { ...fill, markoutBps, regret: markoutBps < -this.feeBps, resolvedAt: time };
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

    stats(now: number): RegretStats {
        this.trim(now);
        const rows = this.resolved;
        const scored = rows.filter((fill) => fill.action !== null);
        const withheld = scored.filter((fill) => fill.action === 'withhold');
        const regrets = rows.filter((fill) => fill.regret);
        const scoredRegrets = scored.filter((fill) => fill.regret);
        const quoteAll = mean(scored.map((fill) => fill.markoutBps ?? 0));
        const policy = mean(
            scored.map((fill) => (fill.action === 'withhold' ? 0 : (fill.markoutBps ?? 0))),
        );
        return {
            windowMs: this.windowMs,
            resolved: rows.length,
            pending: this.pending.length,
            regretRate: rows.length ? regrets.length / rows.length : null,
            meanMarkoutBps: mean(rows.map((fill) => fill.markoutBps ?? 0)),
            scored: scored.length,
            withheld: withheld.length,
            quoteAllBps: quoteAll,
            policyBps: policy,
            liftBps: quoteAll === null || policy === null ? null : policy - quoteAll,
            withholdPrecision: withheld.length
                ? withheld.filter((fill) => fill.regret).length / withheld.length
                : null,
            regretRecall: scoredRegrets.length
                ? scoredRegrets.filter((fill) => fill.action === 'withhold').length /
                  scoredRegrets.length
                : null,
        };
    }

    private trim(now: number): void {
        const cutoff = now - this.windowMs;
        let drop = 0;
        while (drop < this.resolved.length && this.resolved[drop].time < cutoff) drop += 1;
        if (drop) this.resolved.splice(0, drop);
    }
}

function mean(values: number[]): number | null {
    if (!values.length) return null;
    let total = 0;
    for (const value of values) total += value;
    return total / values.length;
}
