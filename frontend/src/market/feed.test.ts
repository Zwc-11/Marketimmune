import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MODEL_URL } from '../config';
import { MarketFeed } from './feed';

class Socket {
    static OPEN = 1;
    static instances: Socket[] = [];
    readyState = Socket.OPEN;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    send = vi.fn();

    constructor() { Socket.instances.push(this); }

    message(channel: string, data: unknown): void {
        this.onmessage?.({ data: JSON.stringify({ channel, data }) });
    }
}

const context = (funding: number) => ({
    markPx: '100', oraclePx: '100', midPx: '100', funding: String(funding),
    openInterest: '1000', premium: '0', prevDayPx: '99', dayNtlVlm: '10000',
});

function book(socket: Socket, time: number): void {
    socket.message('l2Book', {
        time, levels: [[{ px: '99', sz: '1', n: 1 }], [{ px: '101', sz: '1', n: 1 }]],
    });
}

function trade(socket: Socket, time: number): void {
    socket.message('trades', [{ time, tid: time, side: 'B', px: '100', sz: '1' }]);
}

async function start(restContext = false): Promise<{ feed: MarketFeed; socket: Socket }> {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
        if (url === MODEL_URL) return Response.json({
            format: 'marketimmune.oblivious.v1', feature_columns: ['asset_funding'],
            scale: 1, bias: 0, trees: [{ f: [0], b: [0.5], v: [-2, 2] }],
        });
        const request = JSON.parse(String(init?.body)) as { type: string };
        return Response.json(request.type === 'metaAndAssetCtxs'
            ? [{ universe: restContext ? [{ name: 'SOL' }] : [] }, [context(1)]]
            : []);
    }));
    const feed = new MarketFeed();
    feed.start();
    const socket = Socket.instances[0];
    socket.onopen?.();
    await vi.waitFor(() => expect(feed.getSnapshot().model.state).toBe('ready'));
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
        socket.message('activeAssetCtx', { ctx: context(0) });
        vi.mocked(Date.now).mockReturnValue(2000);
        socket.message('activeAssetCtx', { ctx: context(1) });
        book(socket, 2000);
        trade(socket, 1500);
        expect(feed.getSnapshot().tape[0].score).toBeCloseTo(1 / (1 + Math.exp(2)));
        expect(feed.getSnapshot().tape[0].action).toBe('quote');
        trade(socket, 2000);
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
        book(socket, 2000);
        trade(socket, 2001);
        expect(feed.getSnapshot().tape[0].score).toBeNull();
        vi.mocked(Date.now).mockReturnValue(3000);
        socket.message('activeAssetCtx', { ctx: context(0) });
        trade(socket, 3001);
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
