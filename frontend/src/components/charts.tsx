import type { SimulatorEvent, SimulatorPrediction } from '../types';
import type { Tone } from '../routes';
import { clamp, price, scoreValue } from '../lib/format';
import { EmptyState } from './ui';
import { BrandMark, Icon } from './Icon';

export function ProgressBar({ value, tone }: { value: number; tone: Tone }) {
    return (
        <div className={`progress-track tone-${tone}`}>
            <span style={{ width: `${clamp(value, 0, 100)}%` }} />
        </div>
    );
}

export function Sparkline({ values, tone }: { values: number[]; tone: Tone }) {
    if (!values.length) return <span className="sparkline-empty">No trend</span>;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const points = values
        .map((value, index) => {
            const x = (index / Math.max(values.length - 1, 1)) * 92 + 4;
            const y = 34 - ((value - min) / Math.max(max - min, 0.001)) * 26;
            return `${x},${y}`;
        })
        .join(' ');
    return (
        <svg className={`sparkline tone-${tone}`} viewBox="0 0 100 40" aria-hidden="true">
            <polyline points={points} />
        </svg>
    );
}

export function MiniScale({ value }: { value: number }) {
    return (
        <div className="mini-scale">
            <div>
                <span style={{ left: `${clamp(value / 2, 0, 1) * 100}%` }} />
            </div>
            <footer>
                <span>0</span>
                <span>0.5</span>
                <span>1</span>
                <span>1.5</span>
                <span>2</span>
            </footer>
        </div>
    );
}

export function ThresholdBar({ value }: { value: number }) {
    return (
        <div className="threshold-bar">
            <div>
                <span style={{ left: `${value * 100}%` }} />
            </div>
            <footer>
                <span>0</span>
                <span>{value.toFixed(2)}</span>
                <span>1.00</span>
            </footer>
        </div>
    );
}

export function CandleReplayChart({ events }: { events: SimulatorEvent[] }) {
    if (!events.length) {
        return (
            <div className="chart-empty">
                <EmptyState
                    title="No replay events"
                    body="No persisted market replay events are available."
                />
            </div>
        );
    }
    const width = 900;
    const height = 270;
    const pad = { top: 16, right: 68, bottom: 48, left: 22 };
    const max = Math.max(...events.map((event) => event.high));
    const min = Math.min(...events.map((event) => event.low));
    const maxVol = Math.max(...events.map((event) => event.volume), 1);
    const chartWidth = width - pad.left - pad.right;
    const chartHeight = height - pad.top - pad.bottom;
    const x = (index: number) =>
        pad.left + (index / Math.max(events.length - 1, 1)) * chartWidth;
    const y = (value: number) =>
        pad.top + ((max - value) / Math.max(max - min, 0.001)) * chartHeight;
    const candleWidth = Math.max(4, (chartWidth / events.length) * 0.48);
    const current = events[events.length - 1];

    return (
        <svg
            className="candle-chart"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label="Kline replay candlestick chart"
        >
            {[0, 1, 2, 3].map((grid) => {
                const gy = pad.top + (grid / 3) * chartHeight;
                return (
                    <line
                        key={grid}
                        x1={pad.left}
                        x2={width - pad.right}
                        y1={gy}
                        y2={gy}
                        className="chart-grid-line"
                    />
                );
            })}
            {events.map((event, index) => {
                const up = event.close >= event.open;
                const barHeight = (event.volume / maxVol) * 44;
                return (
                    <g key={`${event.id}-${index}`}>
                        <line
                            x1={x(index)}
                            x2={x(index)}
                            y1={y(event.high)}
                            y2={y(event.low)}
                            className={up ? 'candle-wick up' : 'candle-wick down'}
                        />
                        <rect
                            x={x(index) - candleWidth / 2}
                            y={Math.min(y(event.open), y(event.close))}
                            width={candleWidth}
                            height={Math.max(2, Math.abs(y(event.open) - y(event.close)))}
                            className={up ? 'candle-body up' : 'candle-body down'}
                        />
                        <rect
                            x={x(index) - candleWidth / 2}
                            y={height - 28 - barHeight}
                            width={candleWidth}
                            height={barHeight}
                            className={up ? 'volume-bar up' : 'volume-bar down'}
                        />
                    </g>
                );
            })}
            <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(current.close)}
                y2={y(current.close)}
                className="price-dash"
            />
            <text x={width - 60} y={y(current.close) - 4} className="price-tag">
                {price(current.close)}
            </text>
        </svg>
    );
}

export function DepthChart({ event }: { event: SimulatorEvent | null }) {
    const levels = event?.depth_levels ?? [];
    const bids = levels.filter((level) => level.percentage < 0).sort((a, b) => a.percentage - b.percentage);
    const asks = levels.filter((level) => level.percentage > 0).sort((a, b) => a.percentage - b.percentage);
    const maxDepth = Math.max(...levels.map((level) => level.depth), 1);
    const makePath = (items: typeof levels, side: 'bid' | 'ask') => {
        const originX = side === 'bid' ? 420 : 430;
        const points = items.map((level, index) => {
            const x = side === 'bid' ? originX - index * 58 : originX + index * 58;
            const y = 130 - (level.depth / maxDepth) * 100;
            return `${x},${y}`;
        });
        return `M ${originX},130 L ${points.join(' L ')} L ${side === 'bid' ? 70 : 790},130 Z`;
    };
    return (
        <div className="depth-card">
            <h4>Order Book Depth (Top 20)</h4>
            <svg viewBox="0 0 860 150" aria-hidden="true">
                <path className="depth-area bid" d={makePath(bids, 'bid')} />
                <path className="depth-area ask" d={makePath(asks, 'ask')} />
                <line x1="430" x2="430" y1="10" y2="136" className="midline" />
                <text x="398" y="145" className="depth-label">
                    {price(event?.close)}
                </text>
            </svg>
        </div>
    );
}

export function RiskTrendChart({ predictions }: { predictions: SimulatorPrediction[] }) {
    const values = predictions.map((prediction) => prediction.risk_score);
    if (!values.length) {
        return (
            <div className="chart-empty small">
                <EmptyState title="No toxicity trend" body="No persisted predictions are available." />
            </div>
        );
    }
    const width = 720;
    const height = 170;
    const pad = 22;
    const points = values.map((value, index) => {
        const x = pad + (index / Math.max(values.length - 1, 1)) * (width - pad * 2);
        const y = height - pad - clamp(value, 0, 1) * (height - pad * 2);
        return { x, y };
    });
    const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ');
    const area = `${line} L ${width - pad} ${height - pad} L ${pad} ${height - pad} Z`;
    return (
        <svg
            className="risk-trend-chart"
            viewBox={`0 0 ${width} ${height}`}
            aria-label="Toxicity score over time"
        >
            {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
                <line
                    key={tick}
                    x1={pad}
                    x2={width - pad}
                    y1={height - pad - tick * (height - pad * 2)}
                    y2={height - pad - tick * (height - pad * 2)}
                    className="chart-grid-line"
                />
            ))}
            <path className="risk-area" d={area} />
            <path className="risk-line" d={line} />
        </svg>
    );
}

export function RiskGauge({ value, label }: { value: number; label: string }) {
    const angle = -180 + clamp(value, 0, 1) * 180;
    const needleX = 120 + Math.cos((angle * Math.PI) / 180) * 76;
    const needleY = 120 + Math.sin((angle * Math.PI) / 180) * 76;
    return (
        <div className="risk-gauge">
            <svg viewBox="0 0 240 155" aria-label={`Toxicity gauge ${value.toFixed(2)}`}>
                <path className="gauge-arc low" d="M 35 120 A 85 85 0 0 1 87 42" />
                <path className="gauge-arc mid" d="M 87 42 A 85 85 0 0 1 153 42" />
                <path className="gauge-arc high" d="M 153 42 A 85 85 0 0 1 205 120" />
                <line className="gauge-needle" x1="120" y1="120" x2={needleX} y2={needleY} />
                <circle className="gauge-pivot" cx="120" cy="120" r="5" />
                <text x="28" y="142">
                    0
                </text>
                <text x="105" y="28">
                    0.50
                </text>
                <text x="195" y="142">
                    1.00
                </text>
            </svg>
            <strong>{scoreValue(value)}</strong>
            <span>{label}</span>
        </div>
    );
}

export function RadialLoopDiagram({ activeIndex }: { activeIndex: number }) {
    const stages = [
        ['Red Team', 'Replay real toxic episodes', 'users'],
        ['Simulate', 'Replay Hyperliquid microstructure', 'play-circle'],
        ['Detect', 'Score fills for adverse selection', 'target'],
        ['Investigate', 'Investigate toxic-flow episodes', 'search'],
        ['Decide', 'Choose quoting controls', 'gavel'],
        ['Memory', 'Store learnings & improve', 'database'],
    ] as const;
    return (
        <div className="radial-loop">
            <svg viewBox="0 0 520 520" aria-hidden="true">
                <circle className="outer-ring" cx="260" cy="260" r="235" />
                <circle className="animated-ring" cx="260" cy="260" r="220" />
                {stages.map((_, index) => (
                    <line
                        key={index}
                        className="loop-spoke"
                        x1="260"
                        y1="260"
                        x2={260 + Math.cos((index * Math.PI) / 3 - Math.PI / 2) * 235}
                        y2={260 + Math.sin((index * Math.PI) / 3 - Math.PI / 2) * 235}
                    />
                ))}
            </svg>
            {stages.map(([title, body, icon], index) => (
                <div
                    key={title}
                    className={`loop-stage stage-${index} ${index === activeIndex ? 'active' : ''}`}
                >
                    <Icon name={icon} />
                    <strong>
                        {index + 1}. {title}
                    </strong>
                    <span>{body}</span>
                </div>
            ))}
            <div className="loop-center">
                <BrandMark />
                <strong>IMMUNE LOOP</strong>
                <span>Continuous Protection</span>
            </div>
        </div>
    );
}
