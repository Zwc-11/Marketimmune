import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { BrandMark, Icon } from './Icon';
import { NAV_GROUPS, ROUTES, type ProductData, type RouteDef, type RouteId } from '../routes';
import { relativeTime } from '../lib/format';

export function AppShell({
    route,
    data,
    sidebarCollapsed,
    onToggleSidebar,
    children,
}: {
    route: RouteDef;
    data: ProductData;
    sidebarCollapsed: boolean;
    onToggleSidebar: () => void;
    children: ReactNode;
}) {
    return (
        <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
            <SidebarNav current={route.id} data={data} />
            <div className="app-frame">
                <TopBar
                    data={data}
                    sidebarCollapsed={sidebarCollapsed}
                    onToggleSidebar={onToggleSidebar}
                />
                <main className="app-main">{children}</main>
            </div>
        </div>
    );
}

function SidebarNav({ current, data }: { current: RouteId; data: ProductData }) {
    const loop = data.loopState?.loop ?? null;
    const routesByGroup = NAV_GROUPS.map((group) => ({
        ...group,
        routes: ROUTES.filter((r) => r.group === group.id),
    }));

    return (
        <aside className="sidebar-nav">
            <a className="brand" href="#/command" aria-label="MarketImmune home">
                <BrandMark />
                <span className="brand-word">MarketImmune</span>
            </a>

            <nav className="nav-groups" aria-label="Main navigation">
                {routesByGroup.map((group) => (
                    <div key={group.id} className="nav-group">
                        <span className="nav-group-label">{group.label}</span>
                        <ul className="nav-list">
                            {group.routes.map((item) => (
                                <li key={item.id}>
                                    <a
                                        className={`nav-item ${current === item.id ? 'active' : ''}`}
                                        href={`#${item.path}`}
                                        aria-current={current === item.id ? 'page' : undefined}
                                    >
                                        <span className="nav-icon-wrap">
                                            <Icon name={item.icon} />
                                        </span>
                                        <span className="nav-label">{item.label}</span>
                                    </a>
                                </li>
                            ))}
                        </ul>
                    </div>
                ))}
            </nav>

            <div className="sidebar-footer">
                <div className="sidebar-status">
                    <span className={`status-dot ${loop ? 'green' : 'steel'}`} />
                    <div>
                        <strong>{loop ? 'Loop ready' : 'Standing by'}</strong>
                        <span>{loop ? relativeTime(loop.started_at) : 'No cycle yet'}</span>
                    </div>
                </div>
            </div>
        </aside>
    );
}

function LiveClock() {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const id = window.setInterval(() => setNow(new Date()), 1000);
        return () => window.clearInterval(id);
    }, []);
    return <time className="live-clock">{now.toISOString().slice(11, 19)} UTC</time>;
}

function TopBar({
    data,
    sidebarCollapsed,
    onToggleSidebar,
}: {
    data: ProductData;
    sidebarCollapsed: boolean;
    onToggleSidebar: () => void;
}) {
    const alertCount = data.loopState?.loop?.alert_count ?? 0;

    return (
        <header className="top-bar">
            <button
                className="icon-button"
                type="button"
                aria-label="Toggle navigation"
                onClick={onToggleSidebar}
            >
                <span className="t-icon-swap" data-state={sidebarCollapsed ? 'b' : 'a'}>
                    <span className="t-icon" data-icon="a">
                        <Icon name="menu" />
                    </span>
                    <span className="t-icon" data-icon="b">
                        <Icon name="close" />
                    </span>
                </span>
            </button>

            <div className="top-bar-spacer" />

            <LiveClock />

            <a
                className="alert-chip-wrap icon-button"
                href="#/risk"
                title="Open toxicity alerts"
                aria-label={`${alertCount} active alerts`}
            >
                <Icon name="bell" />
                <span className="t-badge" data-open={alertCount > 0 ? 'true' : 'false'}>
                    <span className="t-badge-dot">{alertCount > 99 ? '99+' : alertCount}</span>
                </span>
            </a>

            <a className="avatar" href="#/models" title="Models and benchmarks">
                AK
            </a>
        </header>
    );
}
