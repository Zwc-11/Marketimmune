// Django-backed slices: immune-loop state, promoted-model health, scored fills,
// and backfill jobs. Everything here is optional; the terminal and model report
// work without the API.

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
    fetchLLMStatus,
    fetchMarkoutFillDecisions,
    fetchMarkoutModelHealth,
    fetchState,
    probeApi,
    runLoop as apiRunLoop,
} from '../api';
import { DJANGO_POLL_MS } from '../config';
import { SAMPLE_LOOP_STATE } from './sampleLoop';
import type {
    HyperliquidBackfillJobPayload,
    LLMStatus,
    LoopState,
    MarkoutFillDecisionPayload,
    MarkoutModelHealth,
} from '../types';

export type ApiStatus = 'checking' | 'online' | 'offline';

interface DjangoData {
    status: ApiStatus;
    loop: LoopState | null;
    llm: LLMStatus | null;
    model: MarkoutModelHealth | null;
    decisions: MarkoutFillDecisionPayload | null;
    backfills: HyperliquidBackfillJobPayload | null;
    failures: string[];
    refreshedAt: number | null;
}

interface DjangoValue extends DjangoData {
    /** Loop data to render: the API's when online, else the labelled sample if asked for. */
    loopView: { state: LoopState; source: 'api' | 'sample' } | null;
    sampleRequested: boolean;
    requestSample: (show: boolean) => void;
    refresh: () => Promise<void>;
    runLoop: () => Promise<void>;
    running: boolean;
    runMessage: string;
}

const EMPTY: DjangoData = {
    status: 'checking',
    loop: null,
    llm: null,
    model: null,
    decisions: null,
    backfills: null,
    failures: [],
    refreshedAt: null,
};

const Context = createContext<DjangoValue | null>(null);
const LABELS = ['Loop state', 'LLM status', 'Model health', 'Scored fills', 'Backfills'];

export function DjangoProvider({ children }: { children: ReactNode }) {
    const [data, setData] = useState<DjangoData>(EMPTY);
    const [running, setRunning] = useState(false);
    const [runMessage, setRunMessage] = useState('');
    const [sampleRequested, requestSample] = useState(false);

    const refresh = useCallback(async () => {
        if (!(await probeApi())) {
            setData({ ...EMPTY, status: 'offline', refreshedAt: Date.now() });
            return;
        }
        const results = await Promise.allSettled([
            fetchState(),
            fetchLLMStatus(),
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
            loop: value<LoopState>(0),
            llm: value<LLMStatus>(1),
            model: value<MarkoutModelHealth>(2),
            decisions: value<MarkoutFillDecisionPayload>(3),
            backfills: value<HyperliquidBackfillJobPayload>(4),
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
        }, DJANGO_POLL_MS);
        return () => window.clearInterval(timer);
    }, [refresh]);

    const runLoop = useCallback(async () => {
        setRunning(true);
        setRunMessage('Running the immune loop…');
        try {
            const response = await apiRunLoop('hard');
            setRunMessage(
                `Loop ${response.loop_id} finished: ${response.alert_count} alerts, ` +
                    `${response.case_count} cases, ${response.new_memory_count} new memories.`,
            );
            await refresh();
        } catch (error) {
            setRunMessage(
                error instanceof ApiError
                    ? `Loop failed: ${error.message}`
                    : 'Loop failed: the Django API is not reachable.',
            );
        } finally {
            setRunning(false);
        }
    }, [refresh]);

    const value = useMemo<DjangoValue>(() => {
        const loopView = data.loop?.loop
            ? { state: data.loop, source: 'api' as const }
            : sampleRequested
              ? { state: SAMPLE_LOOP_STATE, source: 'sample' as const }
              : null;
        return { ...data, loopView, sampleRequested, requestSample, refresh, runLoop, running, runMessage };
    }, [data, sampleRequested, refresh, runLoop, running, runMessage]);
    return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useDjango(): DjangoValue {
    const value = useContext(Context);
    if (!value) throw new Error('useDjango must be used inside DjangoProvider');
    return value;
}
