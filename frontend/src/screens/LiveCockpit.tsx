import { useState } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import {
    DataPanel,
    DataTable,
    LoadingState,
    MiniMetric,
    StatusBadge,
    ToolbarPills,
} from '../components/ui';
import {
    CandleReplayChart,
    DepthChart,
    RiskTrendChart,
    Sparkline,
} from '../components/charts';
import {
    eventMove,
    eventTypeLabel,
    latestEventFrom,
    latestPredictionFrom,
    marketImpact,
    riskLabel,
    sessionDuration,
    toneForRisk,
    uniqueAgentCount,
} from '../lib/derive';
import {
    formatClock,
    formatDuration,
    formatNumber,
    formatTimestamp,
    price,
    scoreValue,
    sentenceCase,
    shortId,
} from '../lib/format';
import { useAppData } from '../data/provider';
import { AnimatedNumber } from '../components/motion/AnimatedNumber';
import { TextSwap } from '../components/motion/TextSwap';

export function LiveCockpitScreen({
    data,
    loading,
    onRefresh,
}: {
    data: ProductData;
    loading: boolean;
    onRefresh?: () => Promise<void> | void;
}) {
    const simulator = data.simulator;
    const currentEvent = latestEventFrom(simulator);
    const latestPrediction = latestPredictionFrom(simulator);
    const eventRows = (simulator?.events ?? []).slice(-5).reverse();
    const orders = (simulator?.agent_orders ?? []).slice(-5).reverse();
    const trades = (simulator?.agent_trades ?? []).slice(-5).reverse();
    const scenarios = simulator?.scenarios ?? [];
    const [selectedScenario, setSelectedScenario] = useState<string>(
        simulator?.scenario_name ?? '',
    );
    const [rebuilding, setRebuilding] = useState(false);
    const [controlNotice, setControlNotice] = useState('');
    const { setScenario } = useAppData();

    async function rebuildReplay() {
        const scenario = selectedScenario || simulator?.scenario_name;
        if (!scenario) {
            setControlNotice('No scenario selected; cannot rebuild replay.');
            return;
        }
        setRebuilding(true);
        setControlNotice('Rebuilding replay session...');
        setScenario(scenario);
        await new Promise((resolve) => setTimeout(resolve, 600));
        if (onRefresh) await onRefresh();
        setControlNotice(`Replay session rebuilt for scenario "${scenario}".`);
        setRebuilding(false);
    }

    if (loading && !simulator) return <LoadingState label="Loading replay cockpit" />;

    const riskScore = latestPrediction?.risk_score ?? 0;
    const replayDurationMs = sessionDuration(simulator);
    const sessionStatus = simulator?.status ?? 'idle';
    const persistedTone = sessionStatus === 'completed' ? 'green' : 'amber';

    return (
        <section className="screen-stack">
            <DataPanel className="control-strip">
                <div className="strip-cell wide">
                    <span>Scenario</span>
                    <strong>{sentenceCase(simulator?.scenario_name)}</strong>
                    <StatusBadge tone="amber">Simulated overlay</StatusBadge>
                </div>
                <div className="strip-cell">
                    <span>Session ID</span>
                    <strong>{shortId(simulator?.session_id)}</strong>
                </div>
                <div className="strip-cell">
                    <span>Last Event</span>
                    <strong>{shortId(currentEvent?.id)}</strong>
                </div>
                <div className="strip-cell">
                    <span>Session Status</span>
                    <strong>
                        <span className={`status-dot ${sessionStatus === 'completed' ? 'green' : ''}`} />{' '}
                        {sentenceCase(sessionStatus)}
                    </strong>
                    <small>{formatDuration(replayDurationMs)} of persisted ticks</small>
                </div>
                <div className="strip-actions">
                    {scenarios.length > 0 && (
                        <select
                            className="model-select"
                            value={selectedScenario || simulator?.scenario_name || ''}
                            onChange={(event) => setSelectedScenario(event.target.value)}
                            disabled={rebuilding}
                        >
                            {scenarios.map((scenario) => (
                                <option key={scenario.name} value={scenario.name}>
                                    {scenario.label}
                                </option>
                            ))}
                        </select>
                    )}
                    <button
                        className="outline-action green"
                        type="button"
                        onClick={rebuildReplay}
                        disabled={rebuilding}
                    >
                        <Icon name="reset" /> {rebuilding ? 'Rebuilding…' : 'Rebuild Replay'}
                    </button>
                    {onRefresh && (
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => onRefresh()}
                            disabled={loading}
                        >
                            <Icon name="reset" /> Refresh
                        </button>
                    )}
                </div>
                {controlNotice && <span className="control-notice">{controlNotice}</span>}
            </DataPanel>

            <div className="live-grid">
                <DataPanel className="market-panel" title="Hyperliquid BTC-PERP Kline Replay">
                    <ToolbarPills labels={['1m', '5m', '15m', '1H', '4H', '1D']} />
                    <div className="market-meta">
                        <span>{formatTimestamp(currentEvent?.timestamp)}</span>
                        <span>O {price(currentEvent?.open)}</span>
                        <span>H {price(currentEvent?.high)}</span>
                        <span>L {price(currentEvent?.low)}</span>
                        <span>C {price(currentEvent?.close)}</span>
                        <span
                            className={
                                eventMove(currentEvent).startsWith('+') ? 'positive' : 'danger-text'
                            }
                        >
                            {eventMove(currentEvent)}
                        </span>
                    </div>
                    <CandleReplayChart events={(simulator?.events ?? []).slice(-96)} />
                    <DepthChart event={currentEvent} />
                </DataPanel>

                <div className="live-side">
                    <DataPanel
                        title="Toxicity Score Over Time"
                        badge={<StatusBadge tone={persistedTone}>{sentenceCase(sessionStatus)}</StatusBadge>}
                    >
                        <div className="risk-current">
                            <span>Current Toxicity Score</span>
                            <strong>
                                <AnimatedNumber value={scoreValue(riskScore)} />
                            </strong>
                            <StatusBadge tone={toneForRisk(riskScore)}>
                                <TextSwap text={riskLabel(riskScore)} />
                            </StatusBadge>
                        </div>
                        <RiskTrendChart predictions={(simulator?.predictions ?? []).slice(-120)} />
                    </DataPanel>
                    <DataPanel title="Simulation Status">
                        <div className="status-card-grid">
                            <MiniMetric
                                label="Agents Active"
                                value={formatNumber(uniqueAgentCount(simulator))}
                                helper="persisted agents"
                            />
                            <MiniMetric
                                label="Orders Sent"
                                value={formatNumber(simulator?.agent_orders.length ?? 0)}
                                helper="persisted orders"
                            />
                            <MiniMetric
                                label="Trades Simulated"
                                value={formatNumber(simulator?.agent_trades.length ?? 0)}
                                helper="persisted fills"
                            />
                            <MiniMetric
                                label="Market Impact (Est.)"
                                value={marketImpact(currentEvent)}
                                helper="spread / close"
                                tone="amber"
                            />
                            <MiniMetric
                                label="Confidence"
                                value={latestPrediction?.confidence.toFixed(2) ?? '-'}
                                helper={latestPrediction ? 'model output' : 'unavailable'}
                                tone="green"
                            />
                        </div>
                    </DataPanel>
                    <DataPanel title="Quick Sparkline">
                        <Sparkline
                            values={(simulator?.predictions ?? []).slice(-32).map((p) => p.risk_score)}
                            tone="amber"
                        />
                    </DataPanel>
                </div>
            </div>

            <div className="three-table-grid">
                <DataTable
                    title="Live Market Event Stream"
                    badge={<StatusBadge tone={persistedTone}>{sentenceCase(sessionStatus)}</StatusBadge>}
                    columns={['Time (UTC+0)', 'Event Type', 'Symbol', 'Details']}
                    rows={eventRows.map((event) => [
                        formatClock(event.timestamp),
                        eventTypeLabel(event),
                        event.symbol ?? data.simulator?.symbol ?? 'BTC-PERP',
                        `${event.volume.toFixed(2)} BTC @ ${price(event.close)}`,
                    ])}
                    footer="View full event stream"
                />
                <DataTable
                    title="Simulated Agent Orders"
                    badge={<StatusBadge tone="steel">Simulated</StatusBadge>}
                    columns={['Time', 'Agent', 'Side', 'Price', 'Size', 'Status']}
                    rows={orders.map((order) => [
                        formatClock(order.timestamp),
                        order.agent_id,
                        order.side,
                        price(order.price),
                        order.quantity.toFixed(2),
                        order.status,
                    ])}
                    footer="View all agent orders"
                />
                <DataTable
                    title="Simulated Trades"
                    badge={<StatusBadge tone="steel">Simulated</StatusBadge>}
                    columns={['Time', 'Agent', 'Side', 'Price', 'Size', 'Notional ($)']}
                    rows={trades.map((trade) => [
                        formatClock(trade.timestamp),
                        trade.agent_id,
                        trade.side,
                        price(trade.price),
                        trade.quantity.toFixed(2),
                        price(trade.notional ?? trade.price * trade.quantity),
                    ])}
                    footer={
                        trades.length
                            ? 'View all simulated trades'
                            : 'No persisted simulated trades for this replay'
                    }
                />
            </div>

            <div className="bottom-readout">
                <span>
                    Simulation Time <strong>{formatTimestamp(currentEvent?.timestamp)}</strong>
                </span>
                <span>
                    Replay Speed <strong>{simulator?.speed ?? 1}.0x</strong>
                </span>
                <span>
                    Data Source <strong>{simulator?.market_coverage.source ?? 'Unavailable'}</strong>
                </span>
                <span>
                    Market <strong>{simulator?.symbol ?? '-'}</strong>
                </span>
                <span>
                    Replay Window <strong>{simulator?.session_date ?? '-'}</strong>
                </span>
                <label className="toggle-label">
                    Auto-Scroll <span className="toggle on" />
                </label>
            </div>
        </section>
    );
}
