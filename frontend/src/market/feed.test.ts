import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MODEL_URL } from '../config';
import { MarketFeed } from './feed';

class Socket {
    static OPEN = 1;
    static instances: Socket[] = [];
    readyState = Socket.OPEN;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    send = vi.fn();
    close = vi.fn();

    constructor() { Socket.instances.push(this); }

    message(channel: string, data: unknown): void {
        this.onmessage?.({ data: JSON.stringify({ channel, data }) });
    }
}

const context = (funding: number) => ({
    markPx: '100', oraclePx: '100', midPx: '100', funding: String(funding),
    openInterest: '1000', premium: '0', prevDayPx: '99', dayNtlVlm: '10000',
});

function book(socket: Socket, time: number, bid = 99, ask = 101): void {
    socket.message('l2Book', {
        time, levels: [[{ px: String(bid), sz: '1', n: 1 }], [{ px: String(ask), sz: '1', n: 1 }]],
    });
}

function trade(socket: Socket, time: number, side = 'B'): void {
    socket.message('trades', [{ time, tid: time, side, px: '100', sz: '1' }]);
}

const MODEL = {
    format: 'marketimmune.oblivious.v1', feature_columns: ['asset_funding'], coin: 'SOL', horizon: '10s',
    decision_threshold: 0.5, scale: 1, bias: 0, trees: [{ f: [0], b: [0.5], v: [-2, 2] }],
};

async function start(restContext = false, model: Record<string, unknown> = MODEL): Promise<{ feed: MarketFeed; socket: Socket }> {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        if (url === MODEL_URL) return Response.json(model);
        const request = JSON.parse(String(init?.body)) as { type: string };
        return Response.json(request.type === 'metaAndAssetCtxs'
            ? [{ universe: restContext ? [{ name: 'SOL' }] : [] }, [context(1)]]
            : []);
    }));
    const feed = new MarketFeed();
    feed.start();
    const socket = Socket.instances[0];
    socket.onopen?.();
    await vi.waitFor(() => expect(feed.getSnapshot().model.state).not.toBe('loading'));
    return { feed, socket };
}

beforeEach(() => {
    Socket.instances = [];
    vi.spyOn(Date, 'now').mockReturnValue(1000);
    vi.stubGlobal('WebSocket', Socket);
    vi.stubGlobal('window', {
        setInterval: vi.fn(), setTimeout: vi.fn(), clearInterval: vi.fn(),
        requestAnimationFrame: vi.fn(() => 1),
    });
    vi.stubGlobal('document', { hidden: false });
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

describe('point-in-time asset context scoring', () => {
    it('scores a delayed trade with its earlier context, then uses the new context for later trades', async () => {
        const { feed, socket } = await start();
        book(socket, 1000);
        socket.message('activeAssetCtx', { ctx: context(0) }); // known from exchange time 1500 (the margin)
        vi.mocked(Date.now).mockReturnValue(2000);
        socket.message('activeAssetCtx', { ctx: context(1) }); // known from 2500
        book(socket, 2000);
        trade(socket, 1500);
        expect(feed.getSnapshot().tape[0].score).toBeCloseTo(1 / (1 + Math.exp(2)));
        expect(feed.getSnapshot().tape[0].action).toBe('quote');
        trade(socket, 2000); // the context received at 2000 is not yet counted as known
        expect(feed.getSnapshot().tape[0].action).toBe('quote');
        trade(socket, 2500);
        expect(feed.getSnapshot().tape[0].score).toBeCloseTo(1 / (1 + Math.exp(-2)));
        expect(feed.getSnapshot().tape[0].action).toBe('withhold');
    });

    it('leaves trades before the first observed context unscored', async () => {
        const { feed, socket } = await start();
        book(socket, 1000);
        vi.mocked(Date.now).mockReturnValue(2000);
        socket.message('activeAssetCtx', { ctx: context(1) });
        trade(socket, 1500);
        expect(feed.getSnapshot().tape[0]).toMatchObject({ score: null, action: null });
    });

    it('timestamps the REST bootstrap context when the response is received', async () => {
        const { feed, socket } = await start(true);
        book(socket, 500);
        trade(socket, 750);
        expect(feed.getSnapshot().tape[0].score).toBeNull();
        trade(socket, 1000);
        expect(feed.getSnapshot().tape[0].score).not.toBeNull();
    });

    it('requires a fresh context after reconnecting', async () => {
        const { feed, socket } = await start();
        book(socket, 1000);
        socket.message('activeAssetCtx', { ctx: context(1) });
        socket.onopen?.();
        vi.mocked(Date.now).mockReturnValue(2000);
        book(socket, 2000);
        trade(socket, 2001);
        expect(feed.getSnapshot().tape[0].score).toBeNull();
        vi.mocked(Date.now).mockReturnValue(3000);
        socket.message('activeAssetCtx', { ctx: context(0) });
        book(socket, 3000);
        trade(socket, 3500);
        expect(feed.getSnapshot().tape[0].action).toBe('quote');
    });

    it('leaves trades older than the bounded context history unscored', async () => {
        const { feed, socket } = await start();
        book(socket, 1000);
        for (let i = 0; i < 65; i += 1) {
            vi.mocked(Date.now).mockReturnValue(1000 + i);
            socket.message('activeAssetCtx', { ctx: context(1) });
        }
        trade(socket, 1000);
        expect(feed.getSnapshot().tape[0].score).toBeNull();
    });
});

describe('audit 2026-11-06: clocks, freshness, labels and models', () => {
    it('B03: a context received after a trade is not used for it when this clock runs slow', async () => {
        const { feed, socket } = await start();
        // This machine is 2 s slow: a book stamped 2900 on the exchange arrives at local 1000.
        book(socket, 2900);
        socket.message('activeAssetCtx', { ctx: context(1) }); // received at exchange time ~3000
        trade(socket, 2500); // happened before that context was received
        expect(feed.getSnapshot().tape[0]).toMatchObject({ score: null, action: null });
        vi.mocked(Date.now).mockReturnValue(1500); // the same 2 s skew, half a second later
        book(socket, 3400);
        trade(socket, 3400);
        expect(feed.getSnapshot().tape[0].action).toBe('withhold');
    });

    it('B08: a trade arriving after its horizon is labelled from the mid at its horizon', async () => {
        const { feed, socket } = await start();
        book(socket, 9_000, 99.99, 100.01);
        book(socket, 11_000, 98.99, 99.01); // the mid at fill + 10 s: 99
        trade(socket, 1_000, 'A'); // a maker buy at 100, delivered late
        const [fill] = feed.getSnapshot().tape;
        expect(fill.markoutBps).toBeCloseTo(-100, 6);
        book(socket, 12_000, 100.99, 101.01); // the next mid (101) must not relabel it
        expect(feed.getSnapshot().resolved[0].markoutBps).toBeCloseTo(-100, 6);
    });

    it('B08: a late trade whose horizon is before the mids seen gets no label', async () => {
        const { feed, socket } = await start();
        book(socket, 50_000);
        book(socket, 51_000);
        trade(socket, 1_000); // horizon at 11 s, long before the first mid held
        expect(feed.getSnapshot().tape).toEqual([]);
    });

    it('B09: a label whose mid comes long after the horizon is dropped, and a stale book does not score', async () => {
        const { feed, socket } = await start();
        book(socket, 1_000);
        socket.message('activeAssetCtx', { ctx: context(1) });
        trade(socket, 1_600);
        expect(feed.getSnapshot().tape).toHaveLength(1);
        book(socket, 20_000); // horizon at 11.6 s; this mid is 8.4 s late
        expect(feed.getSnapshot().tape).toEqual([]);
        expect(feed.getSnapshot().resolved).toEqual([]);
        trade(socket, 26_000); // the last book is 6 s old
        expect(feed.getSnapshot().tape[0]).toMatchObject({ score: null, action: null });
    });

    it('B09: a stalled book stream or a missing pong closes the socket', async () => {
        const { socket } = await start();
        const tick = vi.mocked(window.setInterval).mock.calls[0][0] as () => void;
        book(socket, 1_000);
        vi.mocked(Date.now).mockReturnValue(10_000);
        tick();
        expect(socket.close).not.toHaveBeenCalled();
        vi.mocked(Date.now).mockReturnValue(17_000);
        tick();
        expect(socket.close).toHaveBeenCalledTimes(1);
    });

    it('B10: a model for another coin or horizon, or without a threshold, is refused', async () => {
        for (const [patch, message] of [
            [{ coin: 'BTC' }, 'model is for BTC'],
            [{ horizon: '60s' }, '60s horizon'],
            [{ coin: undefined }, 'unnamed coin'],
            [{ decision_threshold: null }, 'no decision threshold'],
        ] as const) {
            Socket.instances = [];
            const { feed } = await start(false, { ...MODEL, ...patch });
            expect(feed.getSnapshot().model).toMatchObject({ state: 'error' });
            expect((feed.getSnapshot().model as { message: string }).message).toContain(message);
        }
    });

    it('B11: a model reading an unknown feature is refused; a non-finite feature leaves the fill unscored', async () => {
        const { feed } = await start(false, { ...MODEL, feature_columns: ['not_a_live_feature'] });
        expect(feed.getSnapshot().model).toMatchObject({ state: 'error' });
        Socket.instances = [];
        const second = await start(false, { ...MODEL, feature_columns: ['asset_premium'] });
        book(second.socket, 1_000);
        second.socket.message('activeAssetCtx', { ctx: { ...context(1), premium: null } });
        trade(second.socket, 1_600);
        expect(second.feed.getSnapshot().tape[0]).toMatchObject({ score: null, action: null });
    });

    it('B24: the stats window ages with the clock when the book stops', async () => {
        const { feed, socket } = await start();
        const tick = vi.mocked(window.setInterval).mock.calls[0][0] as () => void;
        book(socket, 1_000);
        trade(socket, 1_000);
        book(socket, 11_000);
        vi.mocked(Date.now).mockReturnValue(11_000);
        tick();
        expect(feed.getSnapshot().stats.resolved).toBe(1);
        vi.mocked(Date.now).mockReturnValue(11_000 + 11 * 60_000); // no book for 11 minutes
        tick();
        expect(feed.getSnapshot().stats.resolved).toBe(0);
    });
});
