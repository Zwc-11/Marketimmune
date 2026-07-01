import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
    type ReactNode,
} from 'react';
import type { ProductData } from '../routes';
import type { SimulatorState } from '../types';
import {
    fetchBenchmarkMetrics,
    fetchHyperliquidBackfillJobs,
    fetchHyperliquidCandles,
    fetchHyperliquidLive,
    fetchLLMStatus,
    fetchMarkoutFillDecisions,
    fetchMarkoutModelHealth,
    fetchModelMetrics,
    fetchState,
    fetchTrainingRuns,
    probeApi,
    runLoop as apiRunLoop,
    ApiError,
} from '../api';
import { createSimEngine } from './simEngine';
import {
    SEED_BENCHMARK_METRICS,
    SEED_LLM,
    SEED_LOOP_STATE,
    SEED_MODEL_METRICS,
    SEED_TRAINING_RUNS,
} from './seed';
import { LIVE_MARKET_CONFIG } from '../config';

interface AppDataValue {
    data: ProductData;
    loading: boolean;
    runningLoop: boolean;
    runMessage: string;
    runLoop: () => Promise<void>;
    refresh: () => Promise<void>;
    setScenario: (name: string) => void;
}

const AppDataContext = createContext<AppDataValue | null>(null);
const LiveRiskContext = createContext<number>(0);
const HYDRATION_LABELS = [
    'Loop state',
    'LLM status',
    'Model metrics',
    'Benchmark metrics',
    'Training runs',
    'Hyperliquid backfill jobs',
    'Promoted markout model',
    'Promoted fill decisions',
] as const;

function seedProductData(simulator: SimulatorState): ProductData {
    return {
        loopState: SEED_LOOP_STATE,
        llm: SEED_LLM,
        simulator,
        liveMarket: null,
        liveCandles: null,
        hyperliquidBackfills: null,
        markoutModel: null,
        markoutDecisions: null,
        modelMetrics: SEED_MODEL_METRICS,
        benchmarkMetrics: SEED_BENCHMARK_METRICS,
        trainingRuns: SEED_TRAINING_RUNS,
        errors: [],
        warnings: [],
        dataSource: 'fixtures',
        loadedAt: new Date().toISOString(),
    };
}

function tickPeriodMs(): number {
    const reduced =
        typeof window !== 'undefined' &&
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return reduced ? 4000 : 1500;
}

function withoutLiveMarketWarning(warnings: string[]): string[] {
    return warnings.filter((item) => !item.startsWith('Hyperliquid live:'));
}

function withLiveMarketWarning(warnings: string[], message: string): string[] {
    return [...withoutLiveMarketWarning(warnings), `Hyperliquid live: ${message}`];
}

function withoutLiveCandleWarning(warnings: string[]): string[] {
    return warnings.filter((item) => !item.startsWith('Hyperliquid candles:'));
}

function withLiveCandleWarning(warnings: string[], message: string): string[] {
    return [...withoutLiveCandleWarning(warnings), `Hyperliquid candles: ${message}`];
}

function formatHydrationFailure(label: string, reason: unknown): string {
    if (reason instanceof ApiError) {
        return `${label}: ${reason.message}`;
    }
    return `${label}: unavailable`;
}

function hydrationMeta(
    results: PromiseSettledResult<unknown>[],
): Pick<ProductData, 'dataSource' | 'errors' | 'warnings'> {
    const hits = results.filter((result) => result.status === 'fulfilled').length;
    const failures = results
        .map((result, index) =>
            result.status === 'rejected'
                ? formatHydrationFailure(HYDRATION_LABELS[index], result.reason)
                : null,
        )
        .filter((value): value is string => Boolean(value));

    if (hits === 0) {
        return { dataSource: 'fixtures', errors: [], warnings: [] };
    }

    return {
        dataSource: hits === results.length ? 'live' : 'hybrid',
        errors: [],
        warnings:
            failures.length > 0
                ? [
                      'Some API slices did not load; local fixtures remain active for missing data.',
                      ...failures,
                  ]
                : [],
    };
}

function sidebarCollapsedDefault(): boolean {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(max-width: 960px)').matches;
}

export function DataProvider({ children }: { children: ReactNode }) {
    const engine = useMemo(() => createSimEngine(), []);
    const [data, setData] = useState<ProductData>(() => seedProductData(engine.snapshot()));
    const [liveRisk, setLiveRisk] = useState<number>(() => engine.risk());
    const [loading, setLoading] = useState(true);
    const [runningLoop, setRunningLoop] = useState(false);
    const [runMessage, setRunMessage] = useState('');

    const syncSimulator = useCallback(() => {
        setData((prev) => ({ ...prev, simulator: engine.snapshot() }));
        setLiveRisk(engine.risk());
    }, [engine]);

    const syncLiveMarket = useCallback(async () => {
        try {
            const snapshot = await fetchHyperliquidLive();
            setData((prev) => ({
                ...prev,
                liveMarket: snapshot,
                dataSource: prev.dataSource === 'fixtures' ? 'hybrid' : prev.dataSource,
                warnings: withoutLiveMarketWarning(prev.warnings),
                loadedAt: new Date().toISOString(),
            }));
        } catch (error) {
            const message =
                error instanceof ApiError ? error.message : 'unavailable';
            setData((prev) => ({
                ...prev,
                warnings: withLiveMarketWarning(prev.warnings, message),
                loadedAt: new Date().toISOString(),
            }));
        }
    }, []);

    const syncLiveCandles = useCallback(async () => {
        try {
            const series = await fetchHyperliquidCandles(
                LIVE_MARKET_CONFIG.candleInterval,
                LIVE_MARKET_CONFIG.candleLookbackMinutes,
            );
            setData((prev) => ({
                ...prev,
                liveCandles: series,
                dataSource: prev.dataSource === 'fixtures' ? 'hybrid' : prev.dataSource,
                warnings: withoutLiveCandleWarning(prev.warnings),
                loadedAt: new Date().toISOString(),
            }));
        } catch (error) {
            const message =
                error instanceof ApiError && error.status === 404
                    ? 'candles route not found; restart Django to load the latest API routes'
                    : error instanceof ApiError
                      ? error.message
                      : 'unavailable';
            setData((prev) => ({
                ...prev,
                warnings: withLiveCandleWarning(prev.warnings, message),
                loadedAt: new Date().toISOString(),
            }));
        }
    }, []);

    useEffect(() => {
        const timer = window.setInterval(() => {
            if (document.hidden) return;
            engine.tick();
            syncSimulator();
        }, tickPeriodMs());
        return () => window.clearInterval(timer);
    }, [engine, syncSimulator]);

    useEffect(() => {
        void syncLiveMarket();
        const timer = window.setInterval(() => {
            if (!document.hidden) void syncLiveMarket();
        }, LIVE_MARKET_CONFIG.marketPollMs);
        return () => window.clearInterval(timer);
    }, [syncLiveMarket]);

    useEffect(() => {
        void syncLiveCandles();
        const timer = window.setInterval(() => {
            if (!document.hidden) void syncLiveCandles();
        }, LIVE_MARKET_CONFIG.candlePollMs);
        return () => window.clearInterval(timer);
    }, [syncLiveCandles]);

    const refresh = useCallback(async () => {
        const online = await probeApi();
        if (!online) {
            setData((prev) => ({
                ...prev,
                dataSource: 'fixtures',
                errors: [],
                warnings: withoutLiveCandleWarning(withoutLiveMarketWarning(prev.warnings)),
                loadedAt: new Date().toISOString(),
            }));
            await syncLiveMarket();
            await syncLiveCandles();
            return;
        }

        const results = await Promise.allSettled([
            fetchState(),
            fetchLLMStatus(),
            fetchModelMetrics(),
            fetchBenchmarkMetrics(),
            fetchTrainingRuns(),
            fetchHyperliquidBackfillJobs(),
            fetchMarkoutModelHealth(),
            fetchMarkoutFillDecisions(),
        ]);
        const meta = hydrationMeta(results);

        setData((prev) => {
            const next = { ...prev, ...meta, loadedAt: new Date().toISOString() };
            const [
                loop,
                llm,
                models,
                benches,
                runs,
                backfills,
                markoutModel,
                markoutDecisions,
            ] = results;
            if (loop.status === 'fulfilled') next.loopState = loop.value;
            if (llm.status === 'fulfilled') next.llm = llm.value;
            if (models.status === 'fulfilled' && models.value.length) next.modelMetrics = models.value;
            if (benches.status === 'fulfilled' && benches.value.length) {
                next.benchmarkMetrics = benches.value;
            }
            if (runs.status === 'fulfilled' && runs.value.length) next.trainingRuns = runs.value;
            if (backfills.status === 'fulfilled') next.hyperliquidBackfills = backfills.value;
            if (markoutModel.status === 'fulfilled') next.markoutModel = markoutModel.value;
            if (markoutDecisions.status === 'fulfilled') {
                next.markoutDecisions = markoutDecisions.value;
            }
            return next;
        });
        await syncLiveMarket();
        await syncLiveCandles();
    }, [syncLiveCandles, syncLiveMarket]);

    useEffect(() => {
        refresh().finally(() => setLoading(false));
    }, [refresh]);

    const runLoop = useCallback(async () => {
        setRunningLoop(true);
        setRunMessage('Running immune loop over the replayed episode…');
        try {
            const response = await apiRunLoop('hard');
            setRunMessage(
                `Loop ${response.loop_id}: ${response.alert_count} alerts, ` +
                    `${response.case_count} cases, ${response.new_memory_count} new memory.`,
            );
            await refresh();
        } catch (error) {
            for (let i = 0; i < 20; i += 1) engine.tick();
            syncSimulator();
            const loop = SEED_LOOP_STATE.loop;
            const detail =
                error instanceof ApiError ? error.message : 'Backend unreachable';
            setRunMessage(
                `Offline replay: ${loop?.proposal_name ?? 'episode'} · ${loop?.alert_count ?? 0} alerts · ${detail}`,
            );
        } finally {
            setRunningLoop(false);
        }
    }, [engine, refresh, syncSimulator]);

    const setScenario = useCallback(
        (name: string) => {
            engine.setScenario(name);
            syncSimulator();
        },
        [engine, syncSimulator],
    );

    const value = useMemo<AppDataValue>(
        () => ({ data, loading, runningLoop, runMessage, runLoop, refresh, setScenario }),
        [data, loading, runningLoop, runMessage, runLoop, refresh, setScenario],
    );

    return (
        <AppDataContext.Provider value={value}>
            <LiveRiskContext.Provider value={liveRisk}>{children}</LiveRiskContext.Provider>
        </AppDataContext.Provider>
    );
}

export function useAppData(): AppDataValue {
    const ctx = useContext(AppDataContext);
    if (!ctx) throw new Error('useAppData must be used within a DataProvider');
    return ctx;
}

export function useLiveRisk(): number {
    return useContext(LiveRiskContext);
}

export { sidebarCollapsedDefault };
