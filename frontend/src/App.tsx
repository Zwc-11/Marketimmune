import { useEffect, useRef, useState } from 'react';
import { getRoute, ROUTES, type RouteId } from './routes';
import { AppShell } from './components/shell';
import { ErrorState } from './components/ui';
import { CommandCenterScreen } from './screens/CommandCenter';
import { LiveCockpitScreen } from './screens/LiveCockpit';
import { AgenticLoopScreen } from './screens/AgenticLoop';
import { RiskSentinelScreen } from './screens/RiskSentinel';
import { InvestigationScreen } from './screens/Investigation';
import { ModelBenchmarkScreen } from './screens/ModelBenchmark';
import { MemoryLibraryScreen } from './screens/MemoryLibrary';
import { AuditTrailScreen } from './screens/AuditTrail';
import { useAppData } from './data/provider';

const ROUTE_ORDER: RouteId[] = ROUTES.map((r) => r.id);

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
            window.scrollTo({ top: 0, behavior: 'smooth' });
        };
        window.addEventListener('hashchange', onHash);
        if (!window.location.hash) window.location.replace('#/command');
        return () => window.removeEventListener('hashchange', onHash);
    }, []);

    return getRoute(path);
}

export function App() {
    const { data, loading, runningLoop, runMessage, runLoop, refresh } = useAppData();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const route = useHashRoute();

    useEffect(() => {
        document.documentElement.dataset.theme = 'light';
    }, []);

    return (
        <AppShell
            route={route}
            data={data}
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        >
            {data.errors.length > 0 && <ErrorState errors={data.errors} />}
            <div className="route-page t-resize" key={route.id}>
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
                {route.id === 'risk' && <RiskSentinelScreen data={data} loading={loading} />}
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
            </div>
        </AppShell>
    );
}
