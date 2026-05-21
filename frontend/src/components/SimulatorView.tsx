import { useCallback, useEffect, useMemo, useState } from 'react';
import { fetchSimulatorState, startSimulatorReplay } from '../api';
import type { SimulatorEvent, SimulatorState } from '../types';

const WINDOWS = [
    { value: 120, label: '120 minutes' },
    { value: 360, label: '6 hours' },
    { value: 720, label: '12 hours' },
    { value: 1440, label: 'Full day' },
];

export function SimulatorView() {
    const [state, setState] = useState<SimulatorState | null>(null);
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
        } catch (e) {
            setError((e as Error).message);
        }
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    useEffect(() => {
        if (!playing || !state) return undefined;
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
    const orders = useMemo(
        () => (state?.agent_orders ?? []).filter((o) => o.timestamp === currentTime).slice(0, 12),
        [currentTime, state],
    );

    const rebuild = useCallback(async () => {
        if (!date) return;
        setPlaying(false);
        setMessage(`Building ${limit} minute replay for ${date}...`);
        try {
            await startSimulatorReplay({ scenario, date, limit, speed });
            await load();
        } catch (e) {
            setError((e as Error).message);
        }
    }, [date, limit, load, scenario, speed]);

    return (
        <div className="shell simulator-page">
            <SimulatorNav />
            <header className="sim-header">
                <div>
                    <div className="eyebrow">React simulator</div>
                    <h1>Exchange Replay Cockpit</h1>
                    <p className="muted">
                        Full-day BTCUSDT replay from the local Binance USD-M lake with simulated agent
                        overlays, detector output, EMA 20/50, and volume.
                    </p>
                </div>
                <div className="sim-coverage">
                    <strong>{state?.market_coverage.available_start ?? '-'} to {state?.market_coverage.available_end ?? '-'}</strong>
                    <span>{state?.market_coverage.aligned_date_count ?? 0} aligned kline + bookDepth days</span>
                </div>
            </header>

            <section className="sim-toolbar">
                <label>
                    Scenario
                    <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                        {(state?.scenarios ?? []).map((s) => (
                            <option key={s.name} value={s.name}>{s.label}</option>
                        ))}
                    </select>
                </label>
                <label>
                    Date
                    <select value={date} onChange={(e) => setDate(e.target.value)}>
                        {(state?.market_coverage.aligned_dates ?? []).slice().reverse().map((d) => (
                            <option key={d} value={d}>{d}</option>
                        ))}
                    </select>
                </label>
                <label>
                    Window
                    <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
                        {WINDOWS.map((w) => (
                            <option key={w.value} value={w.value}>{w.label}</option>
                        ))}
                    </select>
                </label>
                <button className="btn" onClick={rebuild} disabled={!date}>Rebuild replay</button>
                <span className="muted">{error || message}</span>
            </section>

            {state && current ? (
                <>
                    <div className="sim-stat-grid">
                        <SimStat label="Last price" value={`$${current.close.toFixed(2)}`} />
                        <SimStat label="1m volume" value={`${current.volume.toFixed(2)} BTC`} />
                        <SimStat label="Spread" value={current.spread ? `$${current.spread.toFixed(2)}` : 'n/a'} />
                        <SimStat label="Risk score" value={prediction ? prediction.risk_score.toFixed(2) : '-'} tone={prediction?.risk_label === 'BLOCK' ? 'red' : 'green'} />
                        <SimStat label="Step" value={`${index + 1} / ${state.events.length}`} />
                    </div>

                    <main className="sim-grid">
                        <section className="sim-main">
                            <div className="sim-card chart-card">
                                <div className="sim-card-head">
                                    <strong>BTCUSDT 1m candles - EMA 20/50 - volume</strong>
                                    <span>Binance parquet</span>
                                </div>
                                <MarketChart events={state.events} index={index} />
                            </div>

                            <div className="sim-card">
                                <div className="sim-card-head">
                                    <strong>Playback</strong>
                                    <span>{formatTime(current.timestamp)}</span>
                                </div>
                                <div className="sim-playbar">
                                    <button className="btn secondary" onClick={() => setPlaying((v) => !v)}>
                                        {playing ? 'Pause' : 'Play'}
                                    </button>
                                    <button className="btn secondary" onClick={() => { setPlaying(false); setIndex(0); }}>
                                        Reset
                                    </button>
                                    <input
                                        type="range"
                                        min={0}
                                        max={state.events.length - 1}
                                        value={index}
                                        onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }}
                                    />
                                    <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                                        {[1, 5, 10, 25, 50, 100].map((s) => (
                                            <option key={s} value={s}>{s}x</option>
                                        ))}
                                    </select>
                                </div>
                            </div>

                            <div className="sim-two">
                                <Tape title="Per-minute kline tape" rows={state.events.slice(Math.max(0, index - 10), index + 1).reverse().map((e) => `${e.close >= e.open ? 'UP' : 'DOWN'} ${formatShortTime(e.timestamp)} - ${e.volume.toFixed(3)} BTC - $${e.close.toFixed(2)}`)} />
                                <Tape title="Simulated agent orders" rows={orders.map((o) => `${o.agent_id} - ${o.side} ${o.quantity.toFixed(4)} @ $${o.price.toFixed(2)}`)} />
                            </div>
                        </section>

                        <aside className="sim-side">
                            <DepthLadder event={current} />
                            <FeaturePanel features={featureSnapshot?.features ?? {}} />
                            <div className="sim-card risk-card">
                                <div className="sim-card-head">
                                    <strong>Detector</strong>
                                    <span>{prediction?.model_name ?? 'RuleEngine'}</span>
                                </div>
                                <div className="risk-score">{prediction ? prediction.risk_score.toFixed(2) : '-'}</div>
                                <div className={`pill ${prediction?.risk_label === 'BLOCK' ? 'red' : 'green'}`}>{prediction?.risk_label ?? 'ALLOW'}</div>
                                <p className="muted">{prediction?.explanation ?? 'No prediction at this tick.'}</p>
                            </div>
                            <div className="sim-card">
                                <div className="sim-card-head">
                                    <strong>Decision audit</strong>
                                    <span>{trace?.policy_decision ?? 'waiting'}</span>
                                </div>
                                <p>{trace?.observation ?? 'No trace at this tick.'}</p>
                                <p className="muted">{trace?.model_interpretation ?? ''}</p>
                                <p className="mono">{trace?.recommended_control ?? ''}</p>
                            </div>
                        </aside>
                    </main>
                </>
            ) : (
                <div className="empty">{error || 'Loading simulator state...'}</div>
            )}
        </div>
    );
}

function SimulatorNav() {
    return (
        <nav className="top-nav" aria-label="Primary">
            <a className="brand-link" href="/dashboard/agentic/v2/">MarketImmune</a>
            <div className="nav-links">
                <a href="/dashboard/agentic/v2/">Immune Loop V2</a>
                <a aria-current="page" href="/dashboard/agentic/v2/simulator/">Simulator</a>
                <a href="/simulator/risk/">Risk</a>
                <a href="/simulator/data/">Data</a>
                <a href="/simulator/audit/">Audit</a>
                <a href="/dashboard/agentic/">Classic Loop</a>
            </div>
        </nav>
    );
}

function MarketChart({ events, index }: { events: SimulatorEvent[]; index: number }) {
    const windowSize = 120;
    const start = Math.max(0, Math.min(index - Math.floor(windowSize / 2), events.length - windowSize));
    const end = Math.min(events.length, start + windowSize);
    const cursor = index - start;
    const visible = events.slice(start, end);
    const ema20 = ema(events, 20).slice(start, end);
    const ema50 = ema(events, 50).slice(start, end);
    if (visible.length === 0) return <div className="empty">No events.</div>;

    const width = 960;
    const height = 420;
    const pad = { top: 18, right: 60, bottom: 70, left: 28 };
    const chartH = height - pad.top - pad.bottom;
    const chartW = width - pad.left - pad.right;
    const minPrice = Math.min(...visible.map((e) => e.low), ...ema20.map((e) => e.value), ...ema50.map((e) => e.value));
    const maxPrice = Math.max(...visible.map((e) => e.high), ...ema20.map((e) => e.value), ...ema50.map((e) => e.value));
    const maxVolume = Math.max(...visible.map((e) => e.volume), 1);
    const x = (i: number) => pad.left + (visible.length === 1 ? chartW : (i / (visible.length - 1)) * chartW);
    const y = (value: number) => pad.top + ((maxPrice - value) / Math.max(maxPrice - minPrice, 1)) * chartH;
    const volumeY = height - 20;
    const candleW = Math.max(3, Math.min(10, chartW / Math.max(visible.length, 1) * 0.55));
    const linePath = (points: Array<{ value: number }>) => points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(p.value)}`).join(' ');
    const current = events[index] ?? visible[0];

    return (
        <svg className="react-market-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="BTCUSDT candle chart with EMA and volume">
            {[0, 1, 2, 3].map((g) => {
                const gy = pad.top + (g / 3) * chartH;
                return <line key={g} x1={pad.left} x2={width - pad.right} y1={gy} y2={gy} className="chart-grid" />;
            })}
            {visible.map((e, i) => {
                const up = e.close >= e.open;
                const barH = (e.volume / maxVolume) * 54;
                return (
                    <g key={e.id || e.timestamp}>
                        <line x1={x(i)} x2={x(i)} y1={y(e.high)} y2={y(e.low)} className={up ? 'wick up' : 'wick down'} />
                        <rect x={x(i) - candleW / 2} y={Math.min(y(e.open), y(e.close))} width={candleW} height={Math.max(2, Math.abs(y(e.open) - y(e.close)))} className={up ? 'candle up' : 'candle down'} />
                        <rect x={x(i) - candleW / 2} y={volumeY - barH} width={candleW} height={barH} className={up ? 'volume up' : 'volume down'} />
                    </g>
                );
            })}
            <path d={linePath(ema20)} className="ema ema20" />
            <path d={linePath(ema50)} className="ema ema50" />
            <line x1={pad.left} x2={width - pad.right} y1={y(current.close)} y2={y(current.close)} className="price-line" />
            <line x1={x(cursor)} x2={x(cursor)} y1={pad.top} y2={height - 20} className="cursor-line" />
            <text x={width - 118} y={y(current.close) - 5} className="price-label">${current.close.toFixed(2)}</text>
            <text x={pad.left} y={height - 8} className="chart-legend">EMA20</text>
            <text x={pad.left + 60} y={height - 8} className="chart-legend blue">EMA50</text>
            <text x={width - 230} y={height - 8} className="chart-legend">Volume = real Binance kline</text>
        </svg>
    );
}

function DepthLadder({ event }: { event: SimulatorEvent }) {
    const levels = event.depth_levels ?? [];
    const orderedLevels = [
        ...levels.filter((l) => l.percentage > 0).sort((a, b) => b.percentage - a.percentage),
        ...levels.filter((l) => l.percentage < 0).sort((a, b) => b.percentage - a.percentage),
    ];
    const maxDepth = Math.max(...levels.map((l) => l.depth), 1);
    return (
        <div className="sim-card">
            <div className="sim-card-head">
                <strong>Aggregated depth ladder</strong>
                <span>Binance bookDepth</span>
            </div>
            <table className="sim-table">
                <tbody>
                    {orderedLevels.map((l) => (
                        <tr key={l.percentage}>
                            <td className={l.percentage > 0 ? 'ask' : 'bid'}>{l.percentage > 0 ? 'ASK' : 'BID'}</td>
                            <td>{l.percentage.toFixed(1)}%</td>
                            <td>{(event.close * (1 + l.percentage / 100)).toFixed(2)}</td>
                            <td>{l.depth.toFixed(2)} BTC</td>
                            <td><span className="depth-bar" style={{ width: `${(l.depth / maxDepth) * 100}%` }} /></td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function FeaturePanel({ features }: { features: Record<string, number> }) {
    return (
        <div className="sim-card">
            <div className="sim-card-head">
                <strong>Feature evidence</strong>
                <span>cursor</span>
            </div>
            <div className="feature-list">
                {Object.entries(features).slice(0, 8).map(([key, value]) => (
                    <div key={key}>
                        <span>{key}</span>
                        <strong>{Number(value).toFixed(2)}</strong>
                    </div>
                ))}
            </div>
        </div>
    );
}

function Tape({ title, rows }: { title: string; rows: string[] }) {
    return (
        <div className="sim-card">
            <div className="sim-card-head">
                <strong>{title}</strong>
                <span>{rows.length} rows</span>
            </div>
            <div className="react-tape">
                {rows.length ? rows.map((row) => <div key={row}>{row}</div>) : <div className="muted">No rows at this tick.</div>}
            </div>
        </div>
    );
}

function SimStat({ label, value, tone }: { label: string; value: string; tone?: 'red' | 'green' }) {
    return (
        <div className={`sim-stat ${tone ?? ''}`}>
            <strong>{value}</strong>
            <span>{label}</span>
        </div>
    );
}

function ema(events: SimulatorEvent[], period: number) {
    const multiplier = 2 / (period + 1);
    let current: number | null = null;
    return events.map((event) => {
        current = current === null ? event.close : (event.close * multiplier) + (current * (1 - multiplier));
        return { timestamp: event.timestamp, value: current };
    });
}

function formatTime(value: string) {
    return new Date(value).toISOString().replace('T', ' ').slice(0, 19) + 'Z';
}

function formatShortTime(value: string) {
    return new Date(value).toISOString().slice(11, 19) + 'Z';
}
