import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { BrandMark, Icon } from './Icon';
import {
    NAV_GROUPS,
    ROUTES,
    type DataSource,
    type ProductData,
    type RouteDef,
    type RouteId,
} from '../routes';
import { riskLabel } from '../lib/derive';
import { price, relativeTime } from '../lib/format';
import { AnimatedNumber } from './motion/AnimatedNumber';

const SOURCE_LABELS: Record<DataSource, string> = {
    fixtures: 'Offline fixtures',
    hybrid: 'Partial API',
    live: 'API connected',
};

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
    useEffect(() => {
        const mobile = window.matchMedia('(max-width: 960px)');
        const lockScroll = mobile.matches && !sidebarCollapsed;
        document.body.style.overflow = lockScroll ? 'hidden' : '';
        return () => {
            document.body.style.overflow = '';
        };
    }, [sidebarCollapsed]);

    return (
        <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
            <a className="skip-link" href="#main-content">
                Skip to main content
            </a>
            <button
                type="button"
                className="sidebar-backdrop"
                aria-label="Close navigation"
                onClick={onToggleSidebar}
                tabIndex={sidebarCollapsed ? -1 : 0}
            />
            <SidebarNav current={route.id} data={data} onNavigate={onToggleSidebar} />
            <div className="app-frame">
                <TopBar
                    data={data}
                    sidebarCollapsed={sidebarCollapsed}
                    onToggleSidebar={onToggleSidebar}
                />
                <MarketStrip data={data} />
                <main className="app-main" id="main-content" tabIndex={-1}>
                    {children}
                </main>
            </div>
        </div>
    );
}

function SidebarNav({
    current,
    data,
    onNavigate,
}: {
    current: RouteId;
    data: ProductData;
    onNavigate: () => void;
}) {
    const loop = data.loopState?.loop ?? null;
    const routesByGroup = NAV_GROUPS.map((group) => ({
        ...group,
        routes: ROUTES.filter((r) => r.group === group.id),
    }));

    return (
        <aside className="sidebar-nav" aria-label="Application sidebar">
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
                                        onClick={() => {
                                            if (window.matchMedia('(max-width: 960px)').matches) {
                                                onNavigate();
                                            }
                                        }}
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
                    <span className={`status-dot ${loop ? 'green' : 'steel'}`} aria-hidden="true" />
                    <div>
                        <strong>{loop ? 'Loop ready' : 'Standing by'}</strong>
                        <span>{loop ? relativeTime(loop.started_at) : 'No cycle yet'}</span>
                    </div>
                </div>
            </div>
        </aside>
    );
}

function MarketStrip({ data }: { data: ProductData }) {
    const live = data.liveMarket;
    const mid = live?.mid ?? null;
    const symbol = live?.symbol ?? 'Live market';
    const latency = live?.client_elapsed_ms ?? live?.elapsed_ms ?? null;
    const latencyText = latency != null ? `${latency.toFixed(1)} ms` : 'unavailable';
    const venueText = live
        ? `Hyperliquid - ${live.cache_hit ? 'cache' : 'API'} - ${latencyText}`
        : 'Hyperliquid unavailable';
    const spreadText = live ? `${live.spread_bps.toFixed(2)} bps` : 'unavailable';
    const regime = live ? riskLabel(Math.min(Math.abs(live.top_imbalance), 1)) : 'unavailable';

    return (
        <div className="market-strip">
            <p className="sr-only market-strip-summary">
                {symbol} {mid != null ? price(mid) : 'unavailable'}, spread {spreadText},
                latency {latencyText}, regime {regime}
            </p>

            <div className="market-strip-primary">
                <div className="market-instrument">
                    <span className="market-symbol">{symbol}</span>
                    <span className="market-price">{mid != null ? price(mid) : '-'}</span>
                    <span className="market-venue">{venueText}</span>
                </div>
                <div className="market-stat market-stat-primary">
                    <span className="market-stat-label">Spread</span>
                    <span className={`market-stat-value ${live ? 'tone-green' : 'tone-steel'}`}>
                        {live ? <AnimatedNumber value={spreadText} /> : 'Unavailable'}
                    </span>
                </div>
            </div>

            <div
                className="market-strip-secondary"
                role="region"
                aria-label="Live market details"
                tabIndex={0}
            >
                <div className="market-stat">
                    <span className="market-stat-label">Top imbalance</span>
                    <span className={`market-stat-value ${live ? 'tone-ink' : 'tone-steel'}`}>
                        {live ? live.top_imbalance.toFixed(3) : '-'}
                    </span>
                </div>
                <div className="market-stat">
                    <span className="market-stat-label">Funding</span>
                    <span
                        className={`market-stat-value ${
                            live?.asset_context ? 'tone-ink' : 'tone-steel'
                        }`}
                    >
                        {live?.asset_context ? live.asset_context.funding.toExponential(2) : '-'}
                    </span>
                </div>
                <div className="market-stat market-stat-scenario">
                    <span className="market-stat-label">Basis</span>
                    <span
                        className={`market-stat-value ${
                            live?.asset_context ? 'tone-ink' : 'tone-steel'
                        }`}
                    >
                        {live?.asset_context
                            ? `${live.asset_context.basis_bps.toFixed(2)} bps`
                            : '-'}
                    </span>
                </div>
            </div>
        </div>
    );
}

function LiveClock() {
    const [now, setNow] = useState(() => new Date());
    useEffect(() => {
        const id = window.setInterval(() => setNow(new Date()), 1000);
        return () => window.clearInterval(id);
    }, []);
    return (
        <time className="live-clock" dateTime={now.toISOString()}>
            {now.toISOString().slice(11, 19)} UTC
        </time>
    );
}

type Theme = 'light' | 'dark';

function ThemeToggle() {
    const [theme, setTheme] = useState<Theme>(() => {
        if (typeof document !== 'undefined') {
            const attr = document.documentElement.getAttribute('data-theme');
            if (attr === 'light' || attr === 'dark') return attr;
        }
        return 'dark';
    });

    useEffect(() => {
        const root = document.documentElement;
        root.setAttribute('data-theme', theme);
        root.style.colorScheme = theme;
        try {
            localStorage.setItem('mi-theme', theme);
        } catch {
            /* storage unavailable — keep in-memory only */
        }
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            const themeColor = getComputedStyle(root).getPropertyValue('--bg-0').trim();
            meta.setAttribute('content', themeColor || (theme === 'light' ? 'white' : 'black'));
        }
    }, [theme]);

    const next: Theme = theme === 'light' ? 'dark' : 'light';
    return (
        <button
            type="button"
            className="icon-button theme-toggle"
            onClick={() => setTheme(next)}
            aria-label={`Switch to ${next} theme`}
            title={`Switch to ${next} theme`}
        >
            <span className="t-icon-swap" data-state={theme === 'dark' ? 'a' : 'b'}>
                <span className="t-icon" data-icon="a">
                    <Icon name="moon" />
                </span>
                <span className="t-icon" data-icon="b">
                    <Icon name="sun" />
                </span>
            </span>
        </button>
    );
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
    const previewLabel = data.liveMarket ? 'Live market - preview models' : 'Preview models';
    const previewTitle = data.liveMarket
        ? 'Market strip is live from Hyperliquid; model and agent views remain preview fixtures.'
        : 'Model and agent views use preview fixtures until the real training pipeline is wired.';

    return (
        <header className="top-bar">
            <button
                className="icon-button"
                type="button"
                aria-label={sidebarCollapsed ? 'Open navigation' : 'Close navigation'}
                aria-expanded={!sidebarCollapsed}
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

            <span className="preview-badge" title={previewTitle}>
                <span className="preview-badge-dot" aria-hidden="true" />
                <span>{previewLabel}</span>
            </span>

            <span
                className={`source-chip ${data.dataSource}`}
                title={SOURCE_LABELS[data.dataSource]}
            >
                <span className="status-dot" aria-hidden="true" />
                <span className="source-chip-label">{SOURCE_LABELS[data.dataSource]}</span>
            </span>

            <div className="top-bar-spacer" />

            <LiveClock />

            <ThemeToggle />

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
                MI
            </a>
        </header>
    );
}
