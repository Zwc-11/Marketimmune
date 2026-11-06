// Live SOL-PERP feed straight from Hyperliquid's public API (CORS-enabled REST for
// the bootstrap, one WebSocket for the stream). No backend is needed for the book,
// tape, candles, or live labels.
//
// Rendering discipline: a WebSocket message replaces the snapshot slices it changes
// (a slice is never mutated once published, except the newest bar of `candles`,
// which goes out through `lastCandle`), and listeners hear about it once per
// animation frame. A slice keeps its identity until it changes, so components
// subscribed to the book do not re-render when only the tape moved (useMarket.ts).

import {
    BOOK_DEPTH,
    CANDLE_HISTORY_BARS,
    CANDLE_INTERVALS,
    DEFAULT_CANDLE_INTERVAL,
    type CandleInterval,
    COIN,
    CTX_AVAILABILITY_MARGIN_MS,
    FEED_STALL_MS,
    HL_INFO_URL,
    HL_WS_URL,
    HORIZON_MS,
    MAX_BOOK_AGE_MS,
    MAX_CTX_AGE_MS,
    MAX_LABEL_LAG_MS,
    MODEL_URL,
    PONG_TIMEOUT_MS,
    STATS_WINDOW_MS,
    TAPE_LIMIT,
    TOXIC_FEE_BPS,
} from '../config';
import { assetFeatures, bookTop, featureValues, FEATURE_NAMES, vectorFor, type BookTop } from '../lib/features';
import { priceDecimals } from '../lib/format';
import { calibrate, ObliviousModel, type IsotonicArtifact } from '../lib/obliviousTrees';
import { OfiWindows, type OfiValues } from '../lib/ofi';
import { RegretTracker, type RegretStats, type ResolvedFill, type TapeFill } from '../lib/regret';

export type FeedStatus = 'connecting' | 'live' | 'reconnecting';

export interface Level {
    px: number;
    sz: number;
    /** Cumulative size from the touch through this level. */
    total: number;
}

interface BookState {
    time: number;
    bids: Level[];
    asks: Level[];
    top: BookTop;
    ofi: OfiValues;
}

interface AssetCtxState {
    /** Local receipt time (Date.now()); the context API does not supply an exchange timestamp,
     * so the scorer moves this onto the exchange clock before comparing it with a fill. */
    observedAt: number;
    markPx: number;
    oraclePx: number;
    funding: number;
    openInterest: number;
    premium: number;
    prevDayPx: number;
    dayNtlVlm: number;
}

export interface CandleBar {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

type ModelStatus =
    | { state: 'loading' }
    | { state: 'missing' }
    | { state: 'error'; message: string }
    | { state: 'ready'; name: string | null; treeCount: number; threshold: number };

export interface MarketSnapshot {
    status: FeedStatus;
    lastMessageAt: number | null;
    priceDecimals: number;
    book: BookState | null;
    ctx: AssetCtxState | null;
    candleInterval: CandleInterval;
    candles: CandleBar[];
    lastCandle: CandleBar | null;
    tape: TapeFill[];
    resolved: ResolvedFill[];
    stats: RegretStats;
    model: ModelStatus;
}

interface Scorer {
    model: ObliviousModel;
    calibrator: IsotonicArtifact | undefined;
    threshold: number;
}

const BOOK_HISTORY = 64;
const CTX_HISTORY = 64;
const RESOLVED_LIMIT = 200;
const CANDLE_LIMIT = 720;
const SEEN_LIMIT = 5_000;
const PING_MS = 30_000;
const STATS_MIN_INTERVAL_MS = 250;
const UNSCORED = { score: null, action: null } as const;

interface RawLevel {
    px: string;
    sz: string;
}
interface RawBook {
    time: number;
    levels: [RawLevel[], RawLevel[]];
}
interface RawTrade {
    side: string;
    px: string;
    sz: string;
    time: number;
    tid: number;
}
type RawCtx = Record<string, string | null>;
interface RawCandle {
    t: number;
    i: string;
    o: string | number;
    h: string | number;
    l: string | number;
    c: string | number;
    v: string | number;
}

export class MarketFeed {
    /** Each key is reassigned to a new slice on change; listeners hear once per frame. */
    private readonly snapshot: MarketSnapshot;
    private readonly listeners = new Set<() => void>();
    private flushHandle: number | null = null;
    private started = false;
    private pingTimer: number | null = null;
    private retry = 0;
    private ws: WebSocket | null = null;

    private ofi = new OfiWindows();
    private readonly tracker = new RegretTracker(HORIZON_MS, TOXIC_FEE_BPS, STATS_WINDOW_MS, MAX_LABEL_LAG_MS);
    private readonly bookHistory: BookState[] = [];
    private readonly ctxHistory: AssetCtxState[] = [];
    private scorer: Scorer | null = null;
    private statsAt = 0;
    /** Exchange time of the first book since the last (re)connect. */
    private coverageStart: number | null = null;
    private readonly seenTrades = new Set<string>();
    private readonly seenOrder: string[] = [];
    private clockOffset: number | null = null;
    /** (local time, local minus exchange time) of recent books: the smallest bounds the skew. */
    private readonly offsets: { at: number; offset: number }[] = [];
    private lastBookAt: number | null = null;
    private pingAt: number | null = null;
    private pongAt: number | null = null;

    constructor() {
        this.snapshot = {
            status: 'connecting',
            lastMessageAt: null,
            priceDecimals: 3,
            book: null,
            ctx: null,
            candleInterval: DEFAULT_CANDLE_INTERVAL,
            candles: [],
            lastCandle: null,
            tape: [],
            resolved: [],
            stats: this.tracker.stats(0),
            model: { state: 'loading' },
        };
    }

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        this.start();
        return () => this.listeners.delete(listener);
    };

    getSnapshot = (): MarketSnapshot => this.snapshot;

    /** Local clock minus exchange clock, smoothed; used to age fills on screen. */
    get clockOffsetMs(): number {
        return this.clockOffset ?? 0;
    }

    start(): void {
        if (this.started) return;
        this.started = true;
        void this.loadCandles(this.snapshot.candleInterval);
        void this.loadContext();
        void this.loadModel();
        this.connect();
        window.setInterval(() => {
            this.watchdog();
            this.refreshStats(true);
        }, 1_000);
    }

    /** The exchange's clock now, from this machine's (null before the first book). */
    exchangeNow(): number | null {
        return this.clockOffset === null ? null : Date.now() - this.clockOffset;
    }

    /**
     * An open socket can stall silently: no book for `FEED_STALL_MS`, or a ping with no pong
     * for `PONG_TIMEOUT_MS`, closes it, which reconnects and resets the windows (audit B09).
     */
    private watchdog(): void {
        const ws = this.ws;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const now = Date.now();
        const bookStalled = this.lastBookAt !== null && now - this.lastBookAt > FEED_STALL_MS;
        const pongMissing = this.pingAt !== null && (this.pongAt ?? 0) < this.pingAt && now - this.pingAt > PONG_TIMEOUT_MS;
        if (bookStalled || pongMissing) {
            this.patch('status', 'reconnecting');
            ws.close();
        }
    }

    /** Switch the chart interval: new history over REST, new candle subscription. */
    setCandleInterval(interval: CandleInterval): void {
        const previous = this.snapshot.candleInterval;
        if (interval === previous) return;
        this.patch('candleInterval', interval);
        this.patch('candles', []);
        this.patch('lastCandle', null);
        if (this.ws?.readyState === WebSocket.OPEN) {
            const sub = (i: string) => ({ type: 'candle', coin: COIN, interval: i });
            this.ws.send(JSON.stringify({ method: 'unsubscribe', subscription: sub(previous) }));
            this.ws.send(JSON.stringify({ method: 'subscribe', subscription: sub(interval) }));
        }
        void this.loadCandles(interval);
    }

    // ---- REST ------------------------------------------------------------

    private async loadCandles(interval: CandleInterval): Promise<void> {
        const now = Date.now();
        const bars = await info<RawCandle[]>({
            type: 'candleSnapshot',
            req: {
                coin: COIN,
                interval,
                startTime: now - CANDLE_HISTORY_BARS * CANDLE_INTERVALS[interval],
                endTime: now,
            },
        });
        // A newer switch may have happened while this request was in flight.
        if (interval !== this.snapshot.candleInterval) return;
        this.patch('candles', mergeCandles(bars.map(parseCandle), this.snapshot.candles));
    }

    private async loadContext(): Promise<void> {
        const [meta, contexts] = await info<[{ universe: { name: string }[] }, RawCtx[]]>({
            type: 'metaAndAssetCtxs',
        });
        const index = meta.universe.findIndex((asset) => asset.name === COIN);
        if (index >= 0) this.onCtx(contexts[index]);
    }

    private async loadModel(): Promise<void> {
        try {
            const response = await fetch(MODEL_URL, { cache: 'no-cache' });
            // Static hosts and the dev server answer a missing file with index.html.
            if (!response.ok || !(response.headers.get('content-type') ?? '').includes('json')) {
                this.patch('model', { state: 'missing' });
                return;
            }
            const model = ObliviousModel.fromCompact(await response.json());
            const { calibrator, decision_threshold: threshold, model_name: name } = model.meta;
            checkCompatible(model);
            if (threshold === null || threshold === undefined || !(threshold >= 0 && threshold <= 1)) {
                throw new Error('the model carries no decision threshold in [0, 1]');
            }
            this.scorer = { model, calibrator, threshold };
            this.patch('model', {
                state: 'ready',
                name: name ?? null,
                treeCount: model.treeCount,
                threshold: this.scorer.threshold,
            });
        } catch (error) {
            this.patch('model', { state: 'error', message: (error as Error).message });
        }
    }

    // ---- websocket -------------------------------------------------------

    private connect(): void {
        const ws = new WebSocket(HL_WS_URL);
        this.ws = ws;
        ws.onopen = () => {
            this.retry = 0;
            this.resetAfterGap();
            for (const subscription of [
                { type: 'l2Book', coin: COIN },
                { type: 'trades', coin: COIN },
                { type: 'activeAssetCtx', coin: COIN },
                { type: 'candle', coin: COIN, interval: this.snapshot.candleInterval },
            ]) {
                ws.send(JSON.stringify({ method: 'subscribe', subscription }));
            }
            this.pingAt = null;
            this.pongAt = null;
            this.lastBookAt = Date.now();
            this.pingTimer = window.setInterval(() => {
                if (ws.readyState !== WebSocket.OPEN) return;
                ws.send('{"method":"ping"}');
                if (this.pingAt === null || (this.pongAt ?? 0) >= this.pingAt) this.pingAt = Date.now();
            }, PING_MS);
            this.patch('status', 'live');
        };
        ws.onmessage = (event: MessageEvent<string>) => this.onMessage(event.data);
        ws.onclose = () => {
            if (this.pingTimer !== null) window.clearInterval(this.pingTimer);
            this.pingTimer = null;
            const delay = Math.min(15_000, 1_000 * 2 ** this.retry);
            this.retry += 1;
            this.patch('status', 'reconnecting');
            window.setTimeout(() => this.connect(), delay);
        };
    }

    /**
     * A reconnect leaves a hole in the book stream. OFI restarts from zero (as at
     * the start of an archive day) and fills still waiting on their 10 s mid are
     * dropped: the first mid after the hole would not be the mid at t+10 s.
     */
    private resetAfterGap(): void {
        this.coverageStart = null;
        this.ctxHistory.length = 0;
        if (this.snapshot.book === null) return;
        this.ofi = new OfiWindows();
        this.bookHistory.length = 0;
        this.forget(this.tracker.dropPending());
    }

    private forget(dropped: TapeFill[]): void {
        if (!dropped.length) return;
        const ids = new Set(dropped.map((fill) => fill.id));
        this.patch('tape', this.snapshot.tape.filter((fill) => !ids.has(fill.id)));
        this.refreshStats(true);
    }

    /** True if this trade id was already processed (the feed can replay trades). */
    private seen(id: string): boolean {
        if (this.seenTrades.has(id)) return true;
        this.seenTrades.add(id);
        this.seenOrder.push(id);
        if (this.seenOrder.length > SEEN_LIMIT) {
            for (const old of this.seenOrder.splice(0, 1_000)) this.seenTrades.delete(old);
        }
        return false;
    }

    private onMessage(raw: string): void {
        const message = JSON.parse(raw) as { channel: string; data: unknown };
        const now = Date.now();
        switch (message.channel) {
            case 'l2Book':
                this.onBook(message.data as RawBook);
                break;
            case 'trades':
                this.onTrades(message.data as RawTrade[]);
                break;
            case 'activeAssetCtx':
                this.onCtx((message.data as { ctx: RawCtx }).ctx);
                break;
            case 'candle':
                this.onCandle(message.data as RawCandle | RawCandle[]);
                break;
            case 'pong':
                this.pongAt = now;
                return;
            default:
                return;
        }
        this.patch('lastMessageAt', now);
    }

    private onBook({ time, levels: [rawBids, rawAsks] }: RawBook): void {
        if (!rawBids.length || !rawAsks.length) return;
        const bids = parseLevels(rawBids);
        const asks = parseLevels(rawAsks);
        const top = bookTop(time, bids[0].px, bids[0].sz, asks[0].px, asks[0].sz);
        if (!top) return;
        if (this.snapshot.book === null) {
            this.patch('priceDecimals', priceDecimals(rawBids.concat(rawAsks).slice(0, 20).map((l) => l.px)));
        }
        const now = Date.now();
        const offset = now - time;
        this.clockOffset = this.clockOffset === null ? offset : this.clockOffset * 0.9 + offset * 0.1;
        this.offsets.push({ at: now, offset });
        while (this.offsets.length && this.offsets[0].at < now - OFFSET_WINDOW_MS) this.offsets.shift();
        this.lastBookAt = now;
        const book: BookState = { time, bids, asks, top, ofi: this.ofi.push(top) };
        if (this.coverageStart === null) {
            // Fills due before our first mid cannot be labelled with the mid at t+10 s.
            this.coverageStart = time;
            this.forget(this.tracker.dropPending(time));
        }
        this.bookHistory.push(book);
        if (this.bookHistory.length > BOOK_HISTORY) this.bookHistory.shift();
        this.patch('book', book);

        const done = this.tracker.onMid(time, top.mid);
        this.forget(this.tracker.takeDropped());
        if (!done.length) return;
        const byId = new Map(done.map((fill) => [fill.id, fill]));
        this.patch('tape', this.snapshot.tape.map((fill) => byId.get(fill.id) ?? fill));
        this.patch('resolved', prependCapped(done.reverse(), this.snapshot.resolved, RESOLVED_LIMIT));
        this.refreshStats(false);
    }

    private onTrades(trades: RawTrade[]): void {
        const added: TapeFill[] = [];
        const resolved: ResolvedFill[] = [];
        for (const trade of trades) {
            const px = Number(trade.px);
            const sz = Number(trade.sz);
            const id = `${trade.time}-${trade.tid}`;
            if (!(px > 0) || !(sz > 0) || this.seen(id)) continue;
            // The subscription replays recent history; skip fills we cannot label.
            if (this.coverageStart !== null && trade.time + HORIZON_MS < this.coverageStart) continue;
            // `side` is the aggressor; the maker who got filled sits on the other side.
            const makerSide = trade.side === 'B' ? -1 : 1;
            const { outcome, ...fill } = this.tracker.add({ id, time: trade.time, px, sz, makerSide, ...this.score(trade.time, px, sz, makerSide) });
            if (outcome === 'unavailable') continue; // its horizon mid is not among the mids seen
            added.push(fill);
            if (outcome === 'resolved') resolved.push(fill as ResolvedFill);
        }
        if (!added.length) return;
        this.patch('tape', prependCapped(added.reverse(), this.snapshot.tape, TAPE_LIMIT));
        if (resolved.length) this.patch('resolved', prependCapped(resolved.reverse(), this.snapshot.resolved, RESOLVED_LIMIT));
        this.refreshStats(false);
    }

    private onCtx(raw: RawCtx): void {
        // Use receipt time, including for REST bootstrap. Never backdate an
        // untimestamped context to the last book or the request's start time.
        const ctx = parseCtx(raw, Date.now());
        this.ctxHistory.push(ctx);
        if (this.ctxHistory.length > CTX_HISTORY) this.ctxHistory.shift();
        this.patch('ctx', ctx);
    }

    /**
     * Score with the latest book and context known at or before the fill, both fresh (at most
     * `MAX_BOOK_AGE_MS` / `MAX_CTX_AGE_MS` old), on one clock: the context's local receipt time
     * is moved onto the exchange clock (audit B03). A missing or non-finite feature leaves the
     * fill unscored rather than handing the model a value it never trained on (audit B11).
     */
    private score(time: number, px: number, sz: number, makerSide: 1 | -1): Pick<TapeFill, 'score' | 'action'> {
        const scorer = this.scorer;
        if (!scorer || !this.offsets.length) return UNSCORED;
        const skew = Math.min(...this.offsets.map((o) => o.offset));
        const known = (ctx: AssetCtxState) => ctx.observedAt - skew + CTX_AVAILABILITY_MARGIN_MS;
        const ctx = latestAtOrBefore(this.ctxHistory, time, known);
        if (!ctx || time - known(ctx) > MAX_CTX_AGE_MS) return UNSCORED;
        const book = latestAtOrBefore(this.bookHistory, time, bookTime);
        const asset = assetFeatures(ctx);
        if (!book || !asset || time - book.time > MAX_BOOK_AGE_MS) return UNSCORED;
        const values = featureValues({ px, sz, makerSide, feeBps: 0 }, book.top, book.ofi, asset);
        const { model, calibrator, threshold } = scorer;
        const vector = vectorFor(model.featureColumns, values);
        if (!vector.every((v) => Number.isFinite(v))) return UNSCORED;
        const probability = model.probability(vector);
        if (!Number.isFinite(probability)) return UNSCORED;
        const score = calibrate(calibrator, probability);
        return { score, action: score >= threshold ? 'withhold' : 'quote' };
    }

    private onCandle(data: RawCandle | RawCandle[]): void {
        const interval = this.snapshot.candleInterval;
        for (const raw of Array.isArray(data) ? data : [data]) {
            if (raw.i !== interval) continue;
            const bar = parseCandle(raw);
            const candles = this.snapshot.candles;
            const last = candles[candles.length - 1];
            if (last?.time === bar.time) {
                // In-place: the chart takes this bar through `lastCandle`, not a full reload.
                candles[candles.length - 1] = bar;
            } else if (!last || bar.time > last.time) {
                const next = candles.slice(Math.max(0, candles.length + 1 - CANDLE_LIMIT));
                next.push(bar);
                this.patch('candles', next);
            }
            this.patch('lastCandle', bar);
        }
    }

    // ---- publishing ------------------------------------------------------

    private refreshStats(force: boolean): void {
        const now = Date.now();
        if (!force && now - this.statsAt < STATS_MIN_INTERVAL_MS) return;
        this.statsAt = now;
        // The window ages with the clock, not with the last book, which stops in an outage (audit B24).
        this.patch('stats', this.tracker.stats(this.exchangeNow() ?? now));
    }

    private patch<K extends keyof MarketSnapshot>(key: K, value: MarketSnapshot[K]): void {
        this.snapshot[key] = value;
        if (this.flushHandle !== null) return;
        this.flushHandle = document.hidden
            ? window.setTimeout(this.flush, 500)
            : window.requestAnimationFrame(this.flush);
    }

    private readonly flush = (): void => {
        this.flushHandle = null;
        for (const listener of this.listeners) listener();
    };
}

async function info<T>(body: unknown): Promise<T> {
    const response = await fetch(HL_INFO_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Hyperliquid info ${response.status}`);
    return (await response.json()) as T;
}

const bookTime = (book: BookState) => book.time;
/** How far back the smallest local-minus-exchange offset is taken. */
const OFFSET_WINDOW_MS = 5 * 60_000;

/**
 * A model is used only if it was trained for this coin and label horizon and every feature it
 * reads is one the live feed computes (audit B10, B11).
 */
export function checkCompatible(model: ObliviousModel): void {
    const meta = model.meta as { coin?: unknown; horizon?: unknown };
    const horizon = `${HORIZON_MS / 1000}s`;
    if (meta.coin !== COIN) throw new Error(`model is for ${String(meta.coin ?? 'an unnamed coin')}, this feed is ${COIN}`);
    if (meta.horizon !== horizon) throw new Error(`model is for a ${String(meta.horizon ?? 'unnamed')} horizon, this feed labels ${horizon}`);
    const unknown = model.featureColumns.filter((name) => !FEATURE_NAMES.includes(name));
    if (unknown.length) throw new Error(`model reads features the live feed does not compute: ${unknown.join(', ')}`);
}

/** Newest entry at or before `time` in a history appended in time order. */
function latestAtOrBefore<T>(history: readonly T[], time: number, at: (entry: T) => number): T | undefined {
    for (let i = history.length - 1; i >= 0; i -= 1) {
        if (at(history[i]) <= time) return history[i];
    }
    return undefined;
}

/** `[...head, ...tail].slice(0, limit)` reusing `head`, which the caller hands over. */
function prependCapped<T>(head: T[], tail: readonly T[], limit: number): T[] {
    for (let i = 0; head.length < limit && i < tail.length; i += 1) head.push(tail[i]);
    if (head.length > limit) head.length = limit;
    return head;
}

/** Bootstrap bars, then any bars the socket delivered while REST was in flight. */
function mergeCandles(snapshot: CandleBar[], streamed: CandleBar[]): CandleBar[] {
    const byTime = new Map(snapshot.map((bar) => [bar.time, bar]));
    for (const bar of streamed) byTime.set(bar.time, bar);
    return [...byTime.values()].sort((a, b) => a.time - b.time);
}

function parseLevels(raw: RawLevel[]): Level[] {
    const levels: Level[] = [];
    let total = 0;
    for (let i = 0; i < raw.length && i < BOOK_DEPTH; i += 1) {
        const sz = Number(raw[i].sz);
        total += sz;
        levels.push({ px: Number(raw[i].px), sz, total });
    }
    return levels;
}

function parseCandle(raw: RawCandle): CandleBar {
    return {
        time: Math.floor(raw.t / 1000),
        open: Number(raw.o),
        high: Number(raw.h),
        low: Number(raw.l),
        close: Number(raw.c),
        volume: Number(raw.v),
    };
}

/** Hyperliquid sends some context fields as null (e.g. premium); they become NaN, a missing feature. */
function parseCtx(raw: RawCtx, observedAt: number): AssetCtxState {
    const num = (key: string) => Number(raw[key] ?? Number.NaN);
    return {
        observedAt,
        markPx: num('markPx'),
        oraclePx: num('oraclePx'),
        funding: num('funding'),
        openInterest: num('openInterest'),
        premium: num('premium'),
        prevDayPx: num('prevDayPx'),
        dayNtlVlm: num('dayNtlVlm'),
    };
}

export const marketFeed = new MarketFeed();
