// The live label. A maker fill at price p on side s is resolved by the first mid
// printed at or after fill_time + horizon:
//     markout_bps = s * (mid - p) / p * 1e4,  regretted when markout < -fee_bps
// which is marketimmune.labels.markout.realized_markout_bps + is_toxic.
//
// The mid must come within `maxLagMs` of the horizon (as MarkoutConfig.max_mid_lag_s
// bounds the offline label): after a gap, the next mid is not the mid at t + horizon,
// and the fill has no label. A fill that arrives after its horizon has passed is
// resolved from the mids already seen, not the next one; if those do not reach back
// to its horizon, it has no label either.

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

/** What `add` did with a fill: still waiting, labelled at once from seen mids, or unlabellable. */
export type AddOutcome = 'pending' | 'resolved' | 'unavailable';

export class RegretTracker {
    /** Sorted by dueAt. */
    private pending: TapeFill[] = [];
    /** Sorted by fill time; trimmed to the stats window. */
    private readonly resolved: ResolvedFill[] = [];
    /** Mids seen, in time order, kept for `horizonMs + maxLagMs` back. */
    private readonly mids: { time: number; mid: number }[] = [];
    /** Pending fills whose mid came too late since the last `takeDropped`. */
    private dropped: TapeFill[] = [];

    constructor(
        private readonly horizonMs: number,
        private readonly feeBps: number,
        private readonly windowMs: number,
        private readonly maxLagMs: number = Number.POSITIVE_INFINITY,
    ) {}

    add(fill: Omit<TapeFill, 'dueAt' | 'markoutBps' | 'regret'>): TapeFill & { outcome: AddOutcome } {
        const entry: TapeFill = { ...fill, dueAt: fill.time + this.horizonMs, markoutBps: null, regret: null };
        const last = this.mids[this.mids.length - 1];
        if (last && last.time >= entry.dueAt) {
            // A late arrival: its horizon mid has already printed (audit B08).
            const first = this.mids.findIndex((m) => m.time >= entry.dueAt);
            const covered = first > 0 || (first === 0 && this.mids[0].time === entry.dueAt);
            const mid = this.mids[first];
            if (!covered || mid.time - entry.dueAt > this.maxLagMs) return { ...entry, outcome: 'unavailable' };
            const done = this.label(entry, mid.mid);
            this.insertResolved(done);
            return { ...done, outcome: 'resolved' };
        }
        // Fills arrive in time order; keep the queue sorted by dueAt regardless.
        let at = this.pending.length;
        while (at > 0 && this.pending[at - 1].dueAt > entry.dueAt) at -= 1;
        this.pending.splice(at, 0, entry);
        return { ...entry, outcome: 'pending' };
    }

    /** Resolve every fill whose horizon has elapsed by this mid's timestamp; a fill whose
     * horizon passed more than `maxLagMs` before this mid has no label (`takeDropped`). */
    onMid(time: number, mid: number): ResolvedFill[] {
        this.mids.push({ time, mid });
        const keep = time - this.horizonMs - (Number.isFinite(this.maxLagMs) ? this.maxLagMs : 60_000);
        let old = 0;
        while (old < this.mids.length - 1 && this.mids[old + 1].time <= keep) old += 1;
        if (old) this.mids.splice(0, old);
        let count = 0;
        while (count < this.pending.length && this.pending[count].dueAt <= time) count += 1;
        if (count === 0) return [];
        const due = this.pending.splice(0, count);
        const done: ResolvedFill[] = [];
        for (const fill of due) {
            if (time - fill.dueAt > this.maxLagMs) this.dropped.push(fill);
            else done.push(this.label(fill, mid));
        }
        this.resolved.push(...done);
        this.trim(time);
        return done;
    }

    /** Fills that lost their label to a late mid since the last call. */
    takeDropped(): TapeFill[] {
        const out = this.dropped;
        this.dropped = [];
        return out;
    }

    private label(fill: TapeFill, mid: number): ResolvedFill {
        const markoutBps = (fill.makerSide * (mid - fill.px)) / fill.px * 10_000;
        return { ...fill, markoutBps, regret: markoutBps < -this.feeBps };
    }

    private insertResolved(fill: ResolvedFill): void {
        let at = this.resolved.length;
        while (at > 0 && this.resolved[at - 1].time > fill.time) at -= 1;
        this.resolved.splice(at, 0, fill);
    }

    /**
     * Forget fills that can no longer be resolved honestly: all of them after a feed
     * gap, or those due before `dueBefore` when the book stream starts later than
     * their horizon (the first mid we hold would not be the mid at t + horizon).
     */
    dropPending(dueBefore = Number.POSITIVE_INFINITY): TapeFill[] {
        const dropped = this.pending.filter((fill) => fill.dueAt < dueBefore);
        this.pending = this.pending.filter((fill) => fill.dueAt >= dueBefore);
        if (dueBefore === Number.POSITIVE_INFINITY) this.mids.length = 0; // a gap: seen mids no longer reach the next fills
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
