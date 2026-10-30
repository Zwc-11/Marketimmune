// Slices served by the Django API (server/): promoted-model health, scored fills
// and backfill jobs. All optional: the terminal and model report work without it.

import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
    type ReactNode,
} from 'react';
import {
    ApiError,
    fetchHyperliquidBackfillJobs,
    fetchMarkoutFillDecisions,
    fetchMarkoutModelHealth,
    probeApi,
} from '../api';
import { SERVER_POLL_MS } from '../config';
import type {
    HyperliquidBackfillJobPayload,
    MarkoutFillDecisionPayload,
    MarkoutModelHealth,
} from '../types';

export type ApiStatus = 'checking' | 'online' | 'offline';

interface ServerData {
    status: ApiStatus;
    model: MarkoutModelHealth | null;
    decisions: MarkoutFillDecisionPayload | null;
    backfills: HyperliquidBackfillJobPayload | null;
    failures: string[];
    refreshedAt: number | null;
}

interface ServerValue extends ServerData {
    refresh: () => Promise<void>;
}

const EMPTY: ServerData = {
    status: 'checking',
    model: null,
    decisions: null,
    backfills: null,
    failures: [],
    refreshedAt: null,
};

const Context = createContext<ServerValue | null>(null);
const LABELS = ['Model health', 'Scored fills', 'Backfills'];

export function ServerApiProvider({ children }: { children: ReactNode }) {
    const [data, setData] = useState<ServerData>(EMPTY);

    const refresh = useCallback(async () => {
        if (!(await probeApi())) {
            setData({ ...EMPTY, status: 'offline', refreshedAt: Date.now() });
            return;
        }
        const results = await Promise.allSettled([
            fetchMarkoutModelHealth(),
            fetchMarkoutFillDecisions(),
            fetchHyperliquidBackfillJobs(),
        ]);
        const value = <T,>(index: number): T | null => {
            const result = results[index];
            return result.status === 'fulfilled' ? (result.value as T) : null;
        };
        setData({
            status: 'online',
            model: value<MarkoutModelHealth>(0),
            decisions: value<MarkoutFillDecisionPayload>(1),
            backfills: value<HyperliquidBackfillJobPayload>(2),
            failures: results.flatMap((result, index) =>
                result.status === 'rejected'
                    ? [`${LABELS[index]}: ${result.reason instanceof ApiError ? result.reason.message : 'unavailable'}`]
                    : [],
            ),
            refreshedAt: Date.now(),
        });
    }, []);

    useEffect(() => {
        void refresh();
        const timer = window.setInterval(() => {
            if (!document.hidden) void refresh();
        }, SERVER_POLL_MS);
        return () => window.clearInterval(timer);
    }, [refresh]);

    const value = useMemo<ServerValue>(() => ({ ...data, refresh }), [data, refresh]);
    return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useServerApi(): ServerValue {
    const value = useContext(Context);
    if (!value) throw new Error('useServerApi must be used inside ServerApiProvider');
    return value;
}
