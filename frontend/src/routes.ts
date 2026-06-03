import type {
    AgentRunSummary,
    BenchmarkMetric,
    ImmuneMemory,
    InvestigationCase,
    LLMStatus,
    LoopState,
    ModelMetric,
    SimulatorEvent,
    SimulatorPrediction,
    SimulatorState,
    TrainingRun,
} from './types';
import type { IconName } from './components/Icon';

export type RouteId =
    | 'command'
    | 'live'
    | 'agentic'
    | 'risk'
    | 'investigations'
    | 'models'
    | 'memory'
    | 'audit';

export type Tone = 'green' | 'amber' | 'red' | 'steel' | 'ink';
export type ThemeMode = 'light' | 'dark';

export type NavGroupId = 'overview' | 'market' | 'operations' | 'intelligence';

export interface RouteDef {
    id: RouteId;
    path: string;
    label: string;
    title: string;
    subtitle: string;
    icon: IconName;
    group: NavGroupId;
}

export const NAV_GROUPS: { id: NavGroupId; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'market', label: 'Market' },
    { id: 'operations', label: 'Operations' },
    { id: 'intelligence', label: 'Intelligence' },
];

export interface ProductData {
    loopState: LoopState | null;
    llm: LLMStatus | null;
    simulator: SimulatorState | null;
    modelMetrics: ModelMetric[];
    benchmarkMetrics: BenchmarkMetric[];
    trainingRuns: TrainingRun[];
    errors: string[];
    loadedAt: string | null;
}

export const ROUTES: RouteDef[] = [
    {
        id: 'command',
        path: '/command',
        label: 'Command Center',
        title: 'Command Center',
        subtitle: 'Autonomous immune loop over live Hyperliquid perp flow',
        icon: 'home',
        group: 'overview',
    },
    {
        id: 'live',
        path: '/live',
        label: 'Simulation',
        title: 'Live Simulation Cockpit',
        subtitle: 'Hyperliquid perp microstructure replay with live toxicity scoring',
        icon: 'sliders',
        group: 'market',
    },
    {
        id: 'agentic',
        path: '/agentic',
        label: 'Immune Loop',
        title: 'Immune Loop',
        subtitle: 'Agentic defense orchestration with persisted tool traces',
        icon: 'loop',
        group: 'operations',
    },
    {
        id: 'risk',
        path: '/risk',
        label: 'Toxicity Sentinel',
        title: 'Toxicity Sentinel',
        subtitle: 'Score maker fills for adverse selection with explainable AI',
        icon: 'shield',
        group: 'market',
    },
    {
        id: 'investigations',
        path: '/investigations',
        label: 'Investigation Case File',
        title: 'Investigation Case File',
        subtitle: 'Evidence, matched rules, and recommended controls',
        icon: 'book',
        group: 'operations',
    },
    {
        id: 'models',
        path: '/models',
        label: 'Models',
        title: 'Model and Benchmark Center',
        subtitle: 'Promotion decisions grounded in benchmark evidence',
        icon: 'nodes',
        group: 'intelligence',
    },
    {
        id: 'memory',
        path: '/memory',
        label: 'Memory',
        title: 'Immune Memory Library',
        subtitle: 'Adverse-selection episodes the system has learned from',
        icon: 'globe',
        group: 'intelligence',
    },
    {
        id: 'audit',
        path: '/audit',
        label: 'Audit Trail',
        title: 'Decision Audit Trail',
        subtitle: 'Full traceability of loop decisions and agent actions',
        icon: 'file',
        group: 'operations',
    },
];

export const EMPTY_DATA: ProductData = {
    loopState: null,
    llm: null,
    simulator: null,
    modelMetrics: [],
    benchmarkMetrics: [],
    trainingRuns: [],
    errors: [],
    loadedAt: null,
};

export function getRoute(pathname: string): RouteDef {
    const clean = pathname.replace(/\/+$/, '') || '/command';
    const exact = ROUTES.find((route) => clean === route.path);
    if (exact) return exact;
    const nested = ROUTES.find(
        (route) => route.path !== '/command' && clean.startsWith(route.path),
    );
    if (nested) return nested;
    return ROUTES[0];
}

export type {
    AgentRunSummary,
    BenchmarkMetric,
    ImmuneMemory,
    InvestigationCase,
    LLMStatus,
    LoopState,
    ModelMetric,
    SimulatorEvent,
    SimulatorPrediction,
    SimulatorState,
    TrainingRun,
};
