import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchSimulatorState, startSimulatorReplay } from '../api';
const WINDOWS = [
    { value: 120, label: '120 minutes' },
    { value: 360, label: '6 hours' },
    { value: 720, label: '12 hours' },
    { value: 1440, label: 'Full day' },
];
export function SimulatorView() {
    const [state, setState] = useState(null);
    const [index, setIndex] = useState(0);
    const [playing, setPlaying] = useState(false);
    const [scenario, setScenario] = useState('spoofing_layering');
    const [date, setDate] = useState('');
    const [limit, setLimit] = useState(1440);
    const [speed, setSpeed] = useState(10);
    const [message, setMessage] = useState('Loading simulator...');
    const [error, setError] = useState('');
    const load = useCallback(async () => {
        try {
            const next = await fetchSimulatorState();
            setState(next);
            setIndex(0);
            setPlaying(false);
            setScenario(next.scenario_name);
            setDate(next.session_date || next.market_coverage.available_end || '');
            setLimit(next.event_count || next.market_coverage.default_limit || 1440);
            setSpeed(next.speed || 10);
            setMessage(`Loaded ${next.event_count} one-minute ticks from ${next.session_date}.`);
            setError('');
        }
        catch (e) {
            setError(e.message);
        }
    }, []);
    useEffect(() => {
        load();
    }, [load]);
    useEffect(() => {
        if (!playing || !state)
            return undefined;
        const max = Math.max(0, state.events.length - 1);
        const intervalMs = Math.max(40, 1000 / speed);
        const timer = window.setInterval(() => {
            setIndex((current) => {
                if (current >= max) {
                    window.clearInterval(timer);
                    setPlaying(false);
                    return current;
                }
                return current + 1;
            });
        }, intervalMs);
        return () => window.clearInterval(timer);
    }, [playing, speed, state]);
    const current = state?.events[index] ?? null;
    const currentTime = current?.timestamp ?? '';
    const prediction = state?.predictions.find((p) => p.timestamp === currentTime) ?? null;
    const trace = state?.decision_traces.find((t) => t.timestamp === currentTime) ?? null;
    const featureSnapshot = state?.feature_snapshots.find((f) => f.timestamp === currentTime) ?? null;
    const orders = useMemo(() => (state?.agent_orders ?? []).filter((o) => o.timestamp === currentTime).slice(0, 12), [currentTime, state]);
    const rebuild = useCallback(async () => {
        if (!date)
            return;
        setPlaying(false);
        setMessage(`Building ${limit} minute replay for ${date}...`);
        try {
            await startSimulatorReplay({ scenario, date, limit, speed });
            await load();
        }
        catch (e) {
            setError(e.message);
        }
    }, [date, limit, load, scenario, speed]);
    return (_jsxs("div", { className: "shell simulator-page", children: [_jsx(SimulatorNav, {}), _jsxs("header", { className: "sim-header", children: [_jsxs("div", { children: [_jsx("div", { className: "eyebrow", children: "React simulator" }), _jsx("h1", { children: "Exchange Replay Cockpit" }), _jsx("p", { className: "muted", children: "Full-day BTCUSDT replay from the local Binance USD-M lake with simulated agent overlays, detector output, EMA 20/50, and volume." })] }), _jsxs("div", { className: "sim-coverage", children: [_jsxs("strong", { children: [state?.market_coverage.available_start ?? '-', " to ", state?.market_coverage.available_end ?? '-'] }), _jsxs("span", { children: [state?.market_coverage.aligned_date_count ?? 0, " aligned kline + bookDepth days"] })] })] }), _jsxs("section", { className: "sim-toolbar", children: [_jsxs("label", { children: ["Scenario", _jsx("select", { value: scenario, onChange: (e) => setScenario(e.target.value), children: (state?.scenarios ?? []).map((s) => (_jsx("option", { value: s.name, children: s.label }, s.name))) })] }), _jsxs("label", { children: ["Date", _jsx("select", { value: date, onChange: (e) => setDate(e.target.value), children: (state?.market_coverage.aligned_dates ?? []).slice().reverse().map((d) => (_jsx("option", { value: d, children: d }, d))) })] }), _jsxs("label", { children: ["Window", _jsx("select", { value: limit, onChange: (e) => setLimit(Number(e.target.value)), children: WINDOWS.map((w) => (_jsx("option", { value: w.value, children: w.label }, w.value))) })] }), _jsx("button", { className: "btn", onClick: rebuild, disabled: !date, children: "Rebuild replay" }), _jsx("span", { className: "muted", children: error || message })] }), state && current ? (_jsxs(_Fragment, { children: [_jsxs("div", { className: "sim-stat-grid", children: [_jsx(SimStat, { label: "Last price", value: `$${current.close.toFixed(2)}` }), _jsx(SimStat, { label: "1m volume", value: `${current.volume.toFixed(2)} BTC` }), _jsx(SimStat, { label: "Spread", value: current.spread ? `$${current.spread.toFixed(2)}` : 'n/a' }), _jsx(SimStat, { label: "Risk score", value: prediction ? prediction.risk_score.toFixed(2) : '-', tone: prediction?.risk_label === 'BLOCK' ? 'red' : 'green' }), _jsx(SimStat, { label: "Step", value: `${index + 1} / ${state.events.length}` })] }), _jsxs("main", { className: "sim-grid", children: [_jsxs("section", { className: "sim-main", children: [_jsxs("div", { className: "sim-card chart-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "BTCUSDT 1m candles - EMA 20/50 - volume" }), _jsx("span", { children: "Binance parquet" })] }), _jsx(MarketChart, { events: state.events, index: index })] }), _jsxs("div", { className: "sim-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "Playback" }), _jsx("span", { children: formatTime(current.timestamp) })] }), _jsxs("div", { className: "sim-playbar", children: [_jsx("button", { className: "btn secondary", onClick: () => setPlaying((v) => !v), children: playing ? 'Pause' : 'Play' }), _jsx("button", { className: "btn secondary", onClick: () => { setPlaying(false); setIndex(0); }, children: "Reset" }), _jsx("input", { type: "range", min: 0, max: state.events.length - 1, value: index, onChange: (e) => { setPlaying(false); setIndex(Number(e.target.value)); } }), _jsx("select", { value: speed, onChange: (e) => setSpeed(Number(e.target.value)), children: [1, 5, 10, 25, 50, 100].map((s) => (_jsxs("option", { value: s, children: [s, "x"] }, s))) })] })] }), _jsxs("div", { className: "sim-two", children: [_jsx(Tape, { title: "Per-minute kline tape", rows: state.events.slice(Math.max(0, index - 10), index + 1).reverse().map((e) => `${e.close >= e.open ? 'UP' : 'DOWN'} ${formatShortTime(e.timestamp)} - ${e.volume.toFixed(3)} BTC - $${e.close.toFixed(2)}`) }), _jsx(Tape, { title: "Simulated agent orders", rows: orders.map((o) => `${o.agent_id} - ${o.side} ${o.quantity.toFixed(4)} @ $${o.price.toFixed(2)}`) })] })] }), _jsxs("aside", { className: "sim-side", children: [_jsx(DepthLadder, { event: current }), _jsx(FeaturePanel, { features: featureSnapshot?.features ?? {} }), _jsxs("div", { className: "sim-card risk-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "Detector" }), _jsx("span", { children: prediction?.model_name ?? 'RuleEngine' })] }), _jsx("div", { className: "risk-score", children: prediction ? prediction.risk_score.toFixed(2) : '-' }), _jsx("div", { className: `pill ${prediction?.risk_label === 'BLOCK' ? 'red' : 'green'}`, children: prediction?.risk_label ?? 'ALLOW' }), _jsx("p", { className: "muted", children: prediction?.explanation ?? 'No prediction at this tick.' })] }), _jsxs("div", { className: "sim-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "Decision audit" }), _jsx("span", { children: trace?.policy_decision ?? 'waiting' })] }), _jsx("p", { children: trace?.observation ?? 'No trace at this tick.' }), _jsx("p", { className: "muted", children: trace?.model_interpretation ?? '' }), _jsx("p", { className: "mono", children: trace?.recommended_control ?? '' })] })] })] })] })) : (_jsx("div", { className: "empty", children: error || 'Loading simulator state...' }))] }));
}
function SimulatorNav() {
    return (_jsxs("nav", { className: "top-nav", "aria-label": "Primary", children: [_jsx("a", { className: "brand-link", href: "/dashboard/agentic/v2/", children: "MarketImmune" }), _jsxs("div", { className: "nav-links", children: [_jsx("a", { href: "/dashboard/agentic/v2/", children: "Immune Loop V2" }), _jsx("a", { "aria-current": "page", href: "/dashboard/agentic/v2/simulator/", children: "Simulator" }), _jsx("a", { href: "/simulator/risk/", children: "Risk" }), _jsx("a", { href: "/simulator/data/", children: "Data" }), _jsx("a", { href: "/simulator/audit/", children: "Audit" }), _jsx("a", { href: "/dashboard/agentic/", children: "Classic Loop" })] })] }));
}
function MarketChart({ events, index }) {
    const windowSize = 120;
    const start = Math.max(0, Math.min(index - Math.floor(windowSize / 2), events.length - windowSize));
    const end = Math.min(events.length, start + windowSize);
    const cursor = index - start;
    const visible = events.slice(start, end);
    const ema20 = ema(events, 20).slice(start, end);
    const ema50 = ema(events, 50).slice(start, end);
    if (visible.length === 0)
        return _jsx("div", { className: "empty", children: "No events." });
    const width = 960;
    const height = 420;
    const pad = { top: 18, right: 60, bottom: 70, left: 28 };
    const chartH = height - pad.top - pad.bottom;
    const chartW = width - pad.left - pad.right;
    const minPrice = Math.min(...visible.map((e) => e.low), ...ema20.map((e) => e.value), ...ema50.map((e) => e.value));
    const maxPrice = Math.max(...visible.map((e) => e.high), ...ema20.map((e) => e.value), ...ema50.map((e) => e.value));
    const maxVolume = Math.max(...visible.map((e) => e.volume), 1);
    const x = (i) => pad.left + (visible.length === 1 ? chartW : (i / (visible.length - 1)) * chartW);
    const y = (value) => pad.top + ((maxPrice - value) / Math.max(maxPrice - minPrice, 1)) * chartH;
    const volumeY = height - 20;
    const candleW = Math.max(3, Math.min(10, chartW / Math.max(visible.length, 1) * 0.55));
    const linePath = (points) => points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p.value)}`).join(' ');
    const current = events[index] ?? visible[0];
    return (_jsxs("svg", { className: "react-market-chart", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "BTCUSDT candle chart with EMA and volume", children: [[0, 1, 2, 3].map((g) => {
                const gy = pad.top + (g / 3) * chartH;
                return _jsx("line", { x1: pad.left, x2: width - pad.right, y1: gy, y2: gy, className: "chart-grid" }, g);
            }), visible.map((e, i) => {
                const up = e.close >= e.open;
                const barH = (e.volume / maxVolume) * 54;
                return (_jsxs("g", { children: [_jsx("line", { x1: x(i), x2: x(i), y1: y(e.high), y2: y(e.low), className: up ? 'wick up' : 'wick down' }), _jsx("rect", { x: x(i) - candleW / 2, y: Math.min(y(e.open), y(e.close)), width: candleW, height: Math.max(2, Math.abs(y(e.open) - y(e.close))), className: up ? 'candle up' : 'candle down' }), _jsx("rect", { x: x(i) - candleW / 2, y: volumeY - barH, width: candleW, height: barH, className: up ? 'volume up' : 'volume down' })] }, e.id || e.timestamp));
            }), _jsx("path", { d: linePath(ema20), className: "ema ema20" }), _jsx("path", { d: linePath(ema50), className: "ema ema50" }), _jsx("line", { x1: pad.left, x2: width - pad.right, y1: y(current.close), y2: y(current.close), className: "price-line" }), _jsx("line", { x1: x(cursor), x2: x(cursor), y1: pad.top, y2: height - 20, className: "cursor-line" }), _jsxs("text", { x: width - 118, y: y(current.close) - 5, className: "price-label", children: ["$", current.close.toFixed(2)] }), _jsx("text", { x: pad.left, y: height - 8, className: "chart-legend", children: "EMA20" }), _jsx("text", { x: pad.left + 60, y: height - 8, className: "chart-legend blue", children: "EMA50" }), _jsx("text", { x: width - 230, y: height - 8, className: "chart-legend", children: "Volume = real Binance kline" })] }));
}
function DepthLadder({ event }) {
    const levels = event.depth_levels ?? [];
    const orderedLevels = [
        ...levels.filter((l) => l.percentage > 0).sort((a, b) => b.percentage - a.percentage),
        ...levels.filter((l) => l.percentage < 0).sort((a, b) => b.percentage - a.percentage),
    ];
    const maxDepth = Math.max(...levels.map((l) => l.depth), 1);
    return (_jsxs("div", { className: "sim-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "Aggregated depth ladder" }), _jsx("span", { children: "Binance bookDepth" })] }), _jsx("table", { className: "sim-table", children: _jsx("tbody", { children: orderedLevels.map((l) => (_jsxs("tr", { children: [_jsx("td", { className: l.percentage > 0 ? 'ask' : 'bid', children: l.percentage > 0 ? 'ASK' : 'BID' }), _jsxs("td", { children: [l.percentage.toFixed(1), "%"] }), _jsx("td", { children: (event.close * (1 + l.percentage / 100)).toFixed(2) }), _jsxs("td", { children: [l.depth.toFixed(2), " BTC"] }), _jsx("td", { children: _jsx("span", { className: "depth-bar", style: { width: `${(l.depth / maxDepth) * 100}%` } }) })] }, l.percentage))) }) })] }));
}
function FeaturePanel({ features }) {
    return (_jsxs("div", { className: "sim-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: "Feature evidence" }), _jsx("span", { children: "cursor" })] }), _jsx("div", { className: "feature-list", children: Object.entries(features).slice(0, 8).map(([key, value]) => (_jsxs("div", { children: [_jsx("span", { children: key }), _jsx("strong", { children: Number(value).toFixed(2) })] }, key))) })] }));
}
function Tape({ title, rows }) {
    return (_jsxs("div", { className: "sim-card", children: [_jsxs("div", { className: "sim-card-head", children: [_jsx("strong", { children: title }), _jsxs("span", { children: [rows.length, " rows"] })] }), _jsx("div", { className: "react-tape", children: rows.length ? rows.map((row) => _jsx("div", { children: row }, row)) : _jsx("div", { className: "muted", children: "No rows at this tick." }) })] }));
}
function SimStat({ label, value, tone }) {
    return (_jsxs("div", { className: `sim-stat ${tone ?? ''}`, children: [_jsx("strong", { children: value }), _jsx("span", { children: label })] }));
}
function ema(events, period) {
    const multiplier = 2 / (period + 1);
    let current = null;
    return events.map((event) => {
        current = current === null ? event.close : (event.close * multiplier) + (current * (1 - multiplier));
        return { timestamp: event.timestamp, value: current };
    });
}
function formatTime(value) {
    return new Date(value).toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}
function formatShortTime(value) {
    return new Date(value).toISOString().slice(11, 19) + 'Z';
}
