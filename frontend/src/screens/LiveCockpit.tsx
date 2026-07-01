import { useState } from 'react';
import type { ProductData } from '../routes';
import { Icon } from '../components/Icon';
import { TimeframePills } from '../components/TimeframePills';
import {
    DataPanel,
    DataTable,
    EmptyState,
    LoadingState,
    MiniMetric,
    StatusBadge,
} from '../components/ui';
import { LiveCandleChart, LiveDepthChart } from '../components/charts';
import {
    aggregateLiveCandles,
    chartWindowSize,
    type ChartTimeframe,
} from '../lib/replay';
import { formatClock, formatNumber, formatTimestamp, price } from '../lib/format';

export function LiveCockpitScreen({
    data,
    loading,
    onRefresh,
}: {
    data: ProductData;
    loading: boolean;
    onRefresh?: () => Promise<void> | void;
}) {
    const [timeframe, setTimeframe] = useState<ChartTimeframe>('1m');
    const liveCandles = data.liveCandles?.candles ?? [];
    const chartCandles = aggregateLiveCandles(liveCandles, timeframe).slice(
        -chartWindowSize(timeframe),
    );
    const latestCandle = chartCandles[chartCandles.length - 1] ?? null;
    const latestCandleTime = latestCandle
        ? new Date(latestCandle.close_ts_ms).toISOString()
        : null;
    const bookLevels =
        (data.liveMarket?.bids.length ?? 0) + (data.liveMarket?.asks.length ?? 0);
    const marketBadge = data.liveCandles ? (
        <StatusBadge tone={data.liveCandles.cache_hit ? 'steel' : 'green'}>
            {data.liveCandles.cache_hit ? 'Live cache' : 'Live API'}
        </StatusBadge>
    ) : (
        <StatusBadge tone="amber">Awaiting live API</StatusBadge>
    );

    if (loading && !data.liveCandles && !data.liveMarket) {
        return <LoadingState label="Loading live Hyperliquid market" />;
    }

    return (
        <section className="screen-stack">
            <DataPanel className="control-strip">
                <div className="strip-cell wide">
                    <span>Market</span>
                    <strong>
                        {data.liveMarket?.symbol ?? data.liveCandles?.symbol ?? 'Hyperliquid'}
                    </strong>
                    {marketBadge}
                </div>
                <div className="strip-cell">
                    <span>Mid</span>
                    <strong>{price(data.liveMarket?.mid ?? latestCandle?.close)}</strong>
                </div>
                <div className="strip-cell">
                    <span>Spread</span>
                    <strong>
                        {data.liveMarket ? `${data.liveMarket.spread_bps.toFixed(2)} bps` : '-'}
                    </strong>
                </div>
                <div className="strip-cell">
                    <span>Live source</span>
                    <strong>
                        <span
                            className={`status-dot ${data.liveMarket ? 'green' : ''}`}
                            aria-hidden="true"
                        />{' '}
                        {data.liveMarket ? 'Connected' : 'Unavailable'}
                    </strong>
                    <small>{data.liveMarket?.client_elapsed_ms?.toFixed(1) ?? '-'} ms client</small>
                </div>
                <div className="strip-actions">
                    {onRefresh && (
                        <button
                            className="outline-action"
                            type="button"
                            onClick={() => onRefresh()}
                            disabled={loading}
                        >
                            <Icon name="reset" /> Refresh API
                        </button>
                    )}
                </div>
            </DataPanel>

            <div className="live-grid">
                <DataPanel
                    className="market-panel"
                    title="Hyperliquid live market"
                    badge={marketBadge}
                >
                    <TimeframePills value={timeframe} onChange={setTimeframe} />
                    <div className="market-meta">
                        <span>{formatTimestamp(latestCandleTime)}</span>
                        <span>O {price(latestCandle?.open)}</span>
                        <span>H {price(latestCandle?.high)}</span>
                        <span>L {price(latestCandle?.low)}</span>
                        <span>C {price(latestCandle?.close)}</span>
                        <span
                            className={
                                latestCandle && latestCandle.close >= latestCandle.open
                                    ? 'positive'
                                    : 'danger-text'
                            }
                        >
                            {latestCandle && latestCandle.open
                                ? `${(((latestCandle.close - latestCandle.open) / latestCandle.open) * 100).toFixed(3)}%`
                                : '-'}
                        </span>
                    </div>
                    <LiveCandleChart candles={chartCandles} />
                    <LiveDepthChart snapshot={data.liveMarket} />
                </DataPanel>

                <div className="live-side">
                    <DataPanel title="Live market status" badge={marketBadge}>
                        <div className="status-card-grid">
                            <MiniMetric
                                label="Candles"
                                value={formatNumber(liveCandles.length)}
                                helper={data.liveCandles?.interval ?? 'awaiting API'}
                                tone={liveCandles.length ? 'green' : 'steel'}
                            />
                            <MiniMetric
                                label="Book levels"
                                value={formatNumber(bookLevels)}
                                helper={data.liveMarket ? 'top 20 each side' : 'awaiting API'}
                                tone={bookLevels ? 'green' : 'steel'}
                            />
                            <MiniMetric
                                label="Open interest"
                                value={formatNumber(data.liveMarket?.asset_context?.open_interest ?? 0)}
                                helper={
                                    data.liveMarket?.asset_context ? 'from asset context' : 'awaiting API'
                                }
                            />
                            <MiniMetric
                                label="Funding"
                                value={
                                    data.liveMarket?.asset_context
                                        ? data.liveMarket.asset_context.funding.toExponential(2)
                                        : '-'
                                }
                                helper="Hyperliquid perp"
                            />
                            <MiniMetric
                                label="Basis"
                                value={
                                    data.liveMarket?.asset_context
                                        ? `${data.liveMarket.asset_context.basis_bps.toFixed(2)} bps`
                                        : '-'
                                }
                                helper="mark vs oracle"
                                tone="green"
                            />
                        </div>
                    </DataPanel>
                    <DataPanel title="Model overlay" badge={<StatusBadge tone="steel">Disabled</StatusBadge>}>
                        <EmptyState
                            title="No real model stream"
                            body="This page now shows only live Hyperliquid market data. Toxicity scoring stays disabled until real fills/backfill are connected."
                        />
                    </DataPanel>
                </div>
            </div>

            <div className="three-table-grid">
                <DataTable
                    title="Live Hyperliquid candles"
                    badge={marketBadge}
                    columns={['Time (UTC)', 'Interval', 'Symbol', 'Close', 'Volume']}
                    rows={liveCandles.slice(-10).reverse().map((candle) => [
                        formatClock(new Date(candle.close_ts_ms).toISOString()),
                        candle.interval,
                        data.liveCandles?.symbol ?? `${candle.coin}-PERP`,
                        price(candle.close),
                        candle.volume.toFixed(4),
                    ])}
                    footer="Live market data from Hyperliquid public Info API"
                />
                <DataTable
                    title="Live bids"
                    badge={data.liveMarket ? <StatusBadge tone="green">Live</StatusBadge> : marketBadge}
                    columns={['Price', 'Size', 'Orders']}
                    rows={(data.liveMarket?.bids ?? []).slice(0, 10).map((level) => [
                        price(level.px),
                        level.sz.toFixed(4),
                        String(level.n),
                    ])}
                    footer="Hyperliquid L2 book bid side"
                />
                <DataTable
                    title="Live asks"
                    badge={data.liveMarket ? <StatusBadge tone="green">Live</StatusBadge> : marketBadge}
                    columns={['Price', 'Size', 'Orders']}
                    rows={(data.liveMarket?.asks ?? []).slice(0, 10).map((level) => [
                        price(level.px),
                        level.sz.toFixed(4),
                        String(level.n),
                    ])}
                    footer="Hyperliquid L2 book ask side"
                />
            </div>

            <div className="bottom-readout">
                <span>
                    Live candle time <strong>{formatTimestamp(latestCandleTime)}</strong>
                </span>
                <span>
                    Candle source <strong>{data.liveCandles?.source ?? 'Unavailable'}</strong>
                </span>
                <span>
                    Book source <strong>{data.liveMarket?.source ?? 'Unavailable'}</strong>
                </span>
                <span>
                    Market <strong>{data.liveMarket?.symbol ?? data.liveCandles?.symbol ?? '-'}</strong>
                </span>
                <span>
                    Model overlay <strong>Disabled until real fills are connected</strong>
                </span>
            </div>
        </section>
    );
}
