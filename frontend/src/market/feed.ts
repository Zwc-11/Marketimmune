// Live SOL-PERP feed straight from Hyperliquid's public API (CORS-enabled REST for
// the bootstrap, one WebSocket for the stream). No backend is needed for the book,
// tape, candles, or live labels.
//
// Rendering discipline: WebSocket messages mutate private state and mark slices
// dirty; one requestAnimationFrame flush publishes a new snapshot per frame. A
// slice keeps its object identity until it changes, so components subscribed to
// the book do not re-render when only the tape moved (see useMarket.ts).

import {
    BOOK_DEPTH,
    CANDLE_HISTORY_BARS,
    CANDLE_INTERVALS,
    DEFAULT_CANDLE_INTERVAL,
    type CandleInterval,
    COIN,
    HL_INFO_URL,
    HL_WS_URL,
    HORIZON_MS,
    MODEL_URL,
    STATS_WINDOW_MS,
    TAPE_LIMIT,
    TOXIC_FEE_BPS,
} from '../config';
import { assetFeatures, bookTop, featureValues, vectorFor, type BookTop } from '../lib/features';
import { priceDecimals } from '../lib/format';
import { calibrate, ObliviousModel, type CompactModel } from '../lib/obliviousTrees';
import { OfiWindows, type OfiValues } from '../lib/ofi';
import { RegretTracker, type RegretStats, type TapeFill } from '../lib/regret';

export type FeedStatus = 'connecting' | 'live' | 'reconnecting';

export interface Level {
    px: number;
    sz: number;
    n: number;
}

export interface BookState {
    time: number;
    bids: Level[];
    asks: Level[];
    top: BookTop;
    ofi: OfiValues;
}

export interface AssetCtxState {
    /** UTC receipt time; the context API does not supply an exchange timestamp. */
    observedAt: number;
    markPx: number;
    oraclePx: number;
    midPx: number | null;
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

export type ModelStatus =
    | { state: 'loading' }
    | { state: 'missing' }
    | { state: 'error'; message: string }
    | { state: 'ready'; meta: Omit<CompactModel, 'trees'>; treeCount: number };

export interface FeedInfo {
    status: FeedStatus;
    connectedAt: number | null;
    lastMessageAt: number | null;
    reconnectAt: number | null;
    error: string | null;
    priceDecimals: number;
    /** Local clock minus exchange clock, smoothed; used to age fills on screen. */
    clockOffsetMs: number;
}

export interface MarketSnapshot {
    feed: FeedInfo;
    book: BookState | null;
    ctx: AssetCtxState | null;
    candleInterval: CandleInterval;
    candles: CandleBar[];
    lastCandle: CandleBar | null;
    tape: TapeFill[];
    resolved: TapeFill[];
    stats: RegretStats;
    model: ModelStatus;
}

type Slice = keyof MarketSnapshot;

const BOOK_HISTORY = 64;
const CTX_HISTORY = 64;
const RESOLVED_LIMIT = 200;
const PING_MS = 30_000;
const STATS_MIN_INTERVAL_MS = 250;

interface RawLevel {
    px: string;
    sz: string;
    n: number;
}
interface RawTrade {
    side: string;
    px: string;
    sz: string;
    time: number;
    tid: number;
}
interface RawCandle {
    t: number;
    i?: string;
    o: string | number;
    h: string | number;
    l: string | number;
    c: string | number;
    v: string | number;
}

export class MarketFeed {
    private snapshot: MarketSnapshot;
    private readonly listeners = new Set<() => void>();
    private readonly dirty = new Set<Slice>();
    private flushHandle: number | null = null;
    private started = false;
    private pingTimer: number | null = null;
    private retry = 0;

    private ofi = new OfiWindows();
    private readonly tracker = new RegretTracker(HORIZON_MS, TOXIC_FEE_BPS, STATS_WINDOW_MS);
    private readonly bookHistory: BookState[] = [];
    private readonly ctxHistory: AssetCtxState[] = [];
    private model: ObliviousModel | null = null;
    private statsAt = 0;
    private lastMessageAt: number | null = null;
    private ws: WebSocket | null = null;
    /** Exchange time of the first book since the last (re)connect. */
    private coverageStart: number | null = null;
    private readonly seenTrades = new Set<string>();
    private readonly seenOrder: string[] = [];
    private clockOffset: number | null = null;
    private candles: CandleBar[] = [];

    constructor() {
        const emptyStats = this.tracker.stats(0);
        this.snapshot = {
            feed: {
                status: 'connecting',
                connectedAt: null,
                lastMessageAt: null,
                reconnectAt: null,
                error: null,
                priceDecimals: 3,
                clockOffsetMs: 0,
            },
            book: null,
            ctx: null,
            candleInterval: DEFAULT_CANDLE_INTERVAL,
            candles: [],
            lastCandle: null,
            tape: [],
            resolved: [],
            stats: emptyStats,
            model: { state: 'loading' },
        };
    }

    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        this.start();
        return () => this.listeners.delete(listener);
    };

    getSnapshot = (): MarketSnapshot => this.snapshot;

    start(): void {
        if (this.started || typeof window === 'undefined') return;
        this.started = true;
        void this.bootstrap();
        void this.loadModel();
        this.connect();
        window.setInterval(() => this.refreshStats(true), 1_000);
    }

    // ---- bootstrap -------------------------------------------------------

    private async bootstrap(): Promise<void> {
        const [candles, ctxs] = await Promise.allSettled([
            this.loadCandles(this.snapshot.candleInterval),
            info<[{ universe: { name: string }[] }, Record<string, string | string[] | null>[]]>({
                type: 'metaAndAssetCtxs',
            }),
        ]);
        if (ctxs.status === 'fulfilled') {
            const [meta, contexts] = ctxs.value;
            const index = meta.universe.findIndex((asset) => asset.name === COIN);
            if (index >= 0) this.onCtx(contexts[index]);
        }
        if (candles.status === 'rejected' && ctxs.status === 'rejected') {
            this.patchFeed({ error: 'Hyperliquid REST API unreachable' });
        }
    }

    /** Switch the chart interval: new history over REST, new candle subscription. */
    setCandleInterval(interval: CandleInterval): void {
        const previous = this.snapshot.candleInterval;
        if (interval === previous) return;
        this.candles = [];
        this.patch('candleInterval', interval);
        this.patch('candles', this.candles);
        this.patch('lastCandle', null);
        if (this.ws?.readyState === WebSocket.OPEN) {
            const sub = (i: string) => ({ type: 'candle', coin: COIN, interval: i });
            this.ws.send(JSON.stringify({ method: 'unsubscribe', subscription: sub(previous) }));
            this.ws.send(JSON.stringify({ method: 'subscribe', subscription: sub(interval) }));
        }
        void this.loadCandles(interval);
    }

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
        if (interval !== this.snapshot.candleInterval || !Array.isArray(bars)) return;
        this.candles = mergeCandles(bars.map(parseCandle), this.candles);
        this.patch('candles', this.candles);
    }

    private async loadModel(): Promise<void> {
        try {
            const response = await fetch(MODEL_URL, { cache: 'no-cache' });
            const type = response.headers.get('content-type') ?? '';
            if (!response.ok || !type.includes('json')) {
                this.patch('model', { state: 'missing' });
                return;
            }
            const model = ObliviousModel.fromCompact(await response.json());
            this.model = model;
            this.patch('model', { state: 'ready', meta: model.meta, treeCount: model.treeCount });
        } catch (error) {
            this.patch('model', {
                state: 'error',
                message: error instanceof Error ? error.message : 'could not load model',
            });
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
            this.pingTimer = window.setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) ws.send('{"method":"ping"}');
            }, PING_MS);
            this.patchFeed({
                status: 'live',
                connectedAt: Date.now(),
                reconnectAt: null,
                error: null,
            });
        };
        ws.onmessage = (event: MessageEvent<string>) => this.onMessage(event.data);
        ws.onclose = () => {
            if (this.pingTimer !== null) window.clearInterval(this.pingTimer);
            this.pingTimer = null;
            const delay = Math.min(15_000, 1_000 * 2 ** this.retry);
            this.retry += 1;
            this.patchFeed({ status: 'reconnecting', reconnectAt: Date.now() + delay });
            window.setTimeout(() => this.connect(), delay);
        };
        ws.onerror = () => this.patchFeed({ error: 'WebSocket error; reconnecting' });
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
        if (this.seenOrder.length > 5_000) {
            for (const old of this.seenOrder.splice(0, 1_000)) this.seenTrades.delete(old);
        }
        return false;
    }

    private onMessage(raw: string): void {
        let message: { channel?: string; data?: unknown };
        try {
            message = JSON.parse(raw) as { channel?: string; data?: unknown };
        } catch {
            return;
        }
        const now = Date.now();
        switch (message.channel) {
            case 'l2Book':
                this.onBook(message.data as { time: number; levels: [RawLevel[], RawLevel[]] });
                break;
            case 'trades':
                this.onTrades(message.data as RawTrade[]);
                break;
            case 'activeAssetCtx':
                this.onCtx((message.data as { ctx: Record<string, string> }).ctx);
                break;
            case 'candle':
                this.onCandle(message.data as RawCandle | RawCandle[]);
                break;
            default:
                return;
        }
        this.lastMessageAt = now;
        this.dirty.add('feed');
        this.scheduleFlush();
    }

    private onBook(data: { time: number; levels: [RawLevel[], RawLevel[]] }): void {
        const [rawBids, rawAsks] = data.levels;
        if (!rawBids?.length || !rawAsks?.length) return;
        const bids = rawBids.slice(0, BOOK_DEPTH).map(parseLevel);
        const asks = rawAsks.slice(0, BOOK_DEPTH).map(parseLevel);
        const top = bookTop(data.time, bids[0].px, bids[0].sz, asks[0].px, asks[0].sz);
        if (!top) return;
        if (this.snapshot.book === null) {
            this.patchFeed({
                priceDecimals: priceDecimals([...rawBids, ...rawAsks].slice(0, 20).map((l) => l.px)),
            });
        }
        const offset = Date.now() - data.time;
        this.clockOffset = this.clockOffset === null ? offset : this.clockOffset * 0.9 + offset * 0.1;
        const book: BookState = { time: data.time, bids, asks, top, ofi: this.ofi.push(top) };
        if (this.coverageStart === null) {
            // Fills due before our first mid cannot be labelled with the mid at t+10 s.
            this.coverageStart = book.time;
            this.forget(this.tracker.dropPending(book.time));
        }
        this.bookHistory.push(book);
        if (this.bookHistory.length > BOOK_HISTORY) this.bookHistory.shift();
        this.patch('book', book);

        const done = this.tracker.onMid(book.time, top.mid);
        if (done.length) {
            const byId = new Map(done.map((fill) => [fill.id, fill]));
            this.patch('tape', this.snapshot.tape.map((fill) => byId.get(fill.id) ?? fill));
            this.patch('resolved', [...done.reverse(), ...this.snapshot.resolved].slice(0, RESOLVED_LIMIT));
            this.refreshStats(false);
        }
    }

    private onTrades(trades: RawTrade[]): void {
        if (!Array.isArray(trades) || !trades.length) return;
        const added: TapeFill[] = [];
        for (const trade of trades) {
            const px = Number(trade.px);
            const sz = Number(trade.sz);
            const id = `${trade.time}-${trade.tid}`;
            if (!(px > 0) || !(sz > 0) || this.seen(id)) continue;
            // The subscription replays recent history; skip fills we cannot label.
            if (this.coverageStart !== null && trade.time + HORIZON_MS < this.coverageStart) continue;
            // `side` is the aggressor; the maker who got filled sits on the other side.
            const makerSide = trade.side === 'B' ? -1 : 1;
            const scored = this.score(trade.time, px, sz, makerSide);
            added.push(this.tracker.add({
                id,
                time: trade.time,
                px,
                sz,
                makerSide,
                score: scored?.score ?? null,
                action: scored?.action ?? null,
            }));
        }
        if (!added.length) return;
        this.patch('tape', [...added.reverse(), ...this.snapshot.tape].slice(0, TAPE_LIMIT));
        this.refreshStats(false);
    }

    private onCtx(raw: Record<string, unknown>): void {
        // Use receipt time, including for REST bootstrap. Never backdate an
        // untimestamped context to the last book or the request's start time.
        const ctx = parseCtx(raw, Date.now());
        this.ctxHistory.push(ctx);
        if (this.ctxHistory.length > CTX_HISTORY) this.ctxHistory.shift();
        this.patch('ctx', ctx);
    }

    /** Score with the latest book and context available at or before the fill. */
    private score(
        time: number,
        px: number,
        sz: number,
        makerSide: 1 | -1,
    ): { score: number; action: 'quote' | 'withhold' } | null {
        const model = this.model;
        if (!model) return null;
        let ctx: AssetCtxState | undefined;
        for (let i = this.ctxHistory.length - 1; i >= 0; i -= 1) {
            if (this.ctxHistory[i].observedAt <= time) {
                ctx = this.ctxHistory[i];
                break;
            }
        }
        if (!ctx) return null;
        let book: BookState | undefined;
        for (let i = this.bookHistory.length - 1; i >= 0; i -= 1) {
            if (this.bookHistory[i].time <= time) {
                book = this.bookHistory[i];
                break;
            }
        }
        const asset = assetFeatures(ctx);
        if (!book || !asset) return null;
        const values = featureValues({ px, sz, makerSide, feeBps: 0 }, book.top, book.ofi, asset);
        const meta = model.meta;
        const score = calibrate(meta.calibrator, model.probability(vectorFor(model.featureColumns, values)));
        const threshold = meta.decision_threshold ?? 0.5;
        return { score, action: score >= threshold ? 'withhold' : 'quote' };
    }

    private onCandle(data: RawCandle | RawCandle[]): void {
        let appended = false;
        const interval = this.snapshot.candleInterval;
        const raws = (Array.isArray(data) ? data : [data]).filter((raw) => !raw.i || raw.i === interval);
        for (const bar of raws.map(parseCandle)) {
            const last = this.candles[this.candles.length - 1];
            if (last && last.time === bar.time) {
                this.candles[this.candles.length - 1] = bar;
            } else if (!last || bar.time > last.time) {
                this.candles = [...this.candles, bar].slice(-720);
                appended = true;
            }
            this.patch('lastCandle', bar);
        }
        // A new bar changes the series length; in-place updates go out via lastCandle.
        if (appended) this.patch('candles', this.candles);
    }

    // ---- publishing ------------------------------------------------------

    private refreshStats(force: boolean): void {
        const now = Date.now();
        if (!force && now - this.statsAt < STATS_MIN_INTERVAL_MS) return;
        this.statsAt = now;
        this.patch('stats', this.tracker.stats(this.snapshot.book?.time ?? now));
    }

    private patch<K extends Slice>(key: K, value: MarketSnapshot[K]): void {
        this.snapshot[key] = value;
        this.dirty.add(key);
        this.scheduleFlush();
    }

    private patchFeed(update: Partial<FeedInfo>): void {
        this.patch('feed', { ...this.snapshot.feed, ...update });
    }

    private scheduleFlush(): void {
        if (this.flushHandle !== null) return;
        const flush = () => {
            this.flushHandle = null;
            if (!this.dirty.size) return;
            const next = { ...this.snapshot };
            if (this.dirty.has('feed')) {
                next.feed = {
                    ...next.feed,
                    lastMessageAt: this.lastMessageAt,
                    clockOffsetMs: this.clockOffset ?? 0,
                };
            }
            this.dirty.clear();
            this.snapshot = next;
            for (const listener of this.listeners) listener();
        };
        this.flushHandle = document.hidden
            ? window.setTimeout(flush, 500)
            : window.requestAnimationFrame(flush);
    }
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

/** Bootstrap bars, then any bars the socket delivered while REST was in flight. */
function mergeCandles(snapshot: CandleBar[], streamed: CandleBar[]): CandleBar[] {
    const byTime = new Map(snapshot.map((bar) => [bar.time, bar]));
    for (const bar of streamed) byTime.set(bar.time, bar);
    return [...byTime.values()].sort((a, b) => a.time - b.time);
}

function parseLevel(level: RawLevel): Level {
    return { px: Number(level.px), sz: Number(level.sz), n: level.n };
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

function parseCtx(raw: Record<string, unknown>, observedAt: number): AssetCtxState {
    const num = (key: string) => Number(raw[key] ?? Number.NaN);
    const mid = raw.midPx === null || raw.midPx === undefined ? null : Number(raw.midPx);
    return {
        observedAt,
        markPx: num('markPx'),
        oraclePx: num('oraclePx'),
        midPx: mid,
        funding: num('funding'),
        openInterest: num('openInterest'),
        premium: num('premium'),
        prevDayPx: num('prevDayPx'),
        dayNtlVlm: num('dayNtlVlm'),
    };
}

export const marketFeed = new MarketFeed();
