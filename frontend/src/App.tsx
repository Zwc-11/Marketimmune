import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { getRoute, ROUTES, type RouteId } from './routes';
import { AppShell } from './components/shell';
import { ScreenLayout } from './components/ScreenLayout';
import { ErrorState, LoadingState, WarningBanner } from './components/ui';
import { useAppData, sidebarCollapsedDefault } from './data/provider';

const CommandCenterScreen = lazy(() =>
    import('./screens/CommandCenter').then((m) => ({ default: m.CommandCenterScreen })),
);
const LiveCockpitScreen = lazy(() =>
    import('./screens/LiveCockpit').then((m) => ({ default: m.LiveCockpitScreen })),
);
const AgenticLoopScreen = lazy(() =>
    import('./screens/AgenticLoop').then((m) => ({ default: m.AgenticLoopScreen })),
);
const RiskSentinelScreen = lazy(() =>
    import('./screens/RiskSentinel').then((m) => ({ default: m.RiskSentinelScreen })),
);
const InvestigationScreen = lazy(() =>
    import('./screens/Investigation').then((m) => ({ default: m.InvestigationScreen })),
);
const ModelBenchmarkScreen = lazy(() =>
    import('./screens/ModelBenchmark').then((m) => ({ default: m.ModelBenchmarkScreen })),
);
const MemoryLibraryScreen = lazy(() =>
    import('./screens/MemoryLibrary').then((m) => ({ default: m.MemoryLibraryScreen })),
);
const AuditTrailScreen = lazy(() =>
    import('./screens/AuditTrail').then((m) => ({ default: m.AuditTrailScreen })),
);
const ROUTE_ORDER: RouteId[] = ROUTES.map((r) => r.id);
const ROUTES_WITH_CUSTOM_HEADER: RouteId[] = ['agentic', 'risk', 'memory', 'audit'];

function routeIndex(id: RouteId): number {
    return ROUTE_ORDER.indexOf(id);
}

function currentHashPath(): string {
    const raw = window.location.hash.replace(/^#/, '');
    return raw || '/command';
}

function useHashRoute() {
    const [path, setPath] = useState(currentHashPath);
    const prevIndex = useRef(routeIndex(getRoute(path).id));

    useEffect(() => {
        const onHash = () => {
            const next = getRoute(currentHashPath());
            const nextIndex = routeIndex(next.id);
            const dir = nextIndex >= prevIndex.current ? 1 : -1;
            document.documentElement.style.setProperty('--route-dir', String(dir));
            prevIndex.current = nextIndex;
            setPath(currentHashPath());
            const main = document.getElementById('main-content');
            main?.focus({ preventScroll: true });
            requestAnimationFrame(() => {
                window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
            });
        };
        window.addEventListener('hashchange', onHash);
        if (!window.location.hash) window.location.replace('#/command');
        return () => window.removeEventListener('hashchange', onHash);
    }, []);

    return getRoute(path);
}

export function App() {
    const { data, loading, runningLoop, runMessage, runLoop, refresh } = useAppData();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(sidebarCollapsedDefault);
    const [warningsDismissed, setWarningsDismissed] = useState(false);
    const route = useHashRoute();

    useEffect(() => {
        document.title = `${route.title} - MarketImmune`;
    }, [route.title]);

    useEffect(() => {
        setWarningsDismissed(false);
    }, [data.warnings.length]);

    useEffect(() => {
        const mobile = window.matchMedia('(max-width: 960px)');
        const onChange = () => {
            if (mobile.matches) setSidebarCollapsed(true);
        };
        mobile.addEventListener('change', onChange);
        return () => mobile.removeEventListener('change', onChange);
    }, []);

    const hideLayoutHeader = ROUTES_WITH_CUSTOM_HEADER.includes(route.id);

    return (
        <AppShell
            route={route}
            data={data}
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        >
            {data.errors.length > 0 && <ErrorState errors={data.errors} onRetry={refresh} />}
            {!warningsDismissed && data.warnings.length > 0 && (
                <WarningBanner
                    warnings={data.warnings}
                    onDismiss={() => setWarningsDismissed(true)}
                />
            )}
            <div className="route-page t-resize" key={route.id}>
                <ScreenLayout route={route} hideHeader={hideLayoutHeader}>
                    <Suspense fallback={<LoadingState label={`Loading ${route.label.toLowerCase()}`} />}>
                        {route.id === 'command' && (
                            <CommandCenterScreen
                                data={data}
                                loading={loading}
                                runningLoop={runningLoop}
                                runMessage={runMessage}
                                onRunLoop={runLoop}
                            />
                        )}
                        {route.id === 'live' && (
                            <LiveCockpitScreen data={data} loading={loading} onRefresh={refresh} />
                        )}
                        {route.id === 'agentic' && (
                            <AgenticLoopScreen
                                data={data}
                                loading={loading}
                                runningLoop={runningLoop}
                                onRunLoop={runLoop}
                            />
                        )}
                        {route.id === 'risk' && (
                            <RiskSentinelScreen data={data} loading={loading} />
                        )}
                        {route.id === 'investigations' && (
                            <InvestigationScreen data={data} loading={loading} />
                        )}
                        {route.id === 'models' && (
                            <ModelBenchmarkScreen data={data} loading={loading} />
                        )}
                        {route.id === 'memory' && (
                            <MemoryLibraryScreen data={data} loading={loading} />
                        )}
                        {route.id === 'audit' && <AuditTrailScreen data={data} loading={loading} />}
                    </Suspense>
                </ScreenLayout>
            </div>
        </AppShell>
    );
}
