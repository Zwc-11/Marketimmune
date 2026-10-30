import {
    CandlestickSeries,
    ColorType,
    createChart,
    createSeriesMarkers,
    CrosshairMode,
    HistogramSeries,
    type IChartApi,
    type ISeriesApi,
    type ISeriesMarkersPluginApi,
    type SeriesMarker,
    type Time,
    type UTCTimestamp,
} from 'lightweight-charts';
import { useEffect, useRef } from 'react';
import { CANDLE_INTERVALS, type CandleInterval } from '../config';
import { marketFeed, type CandleBar } from '../market/feed';
import { useMarket } from '../market/useMarket';

const COLORS = {
    up: '#1fb873',
    down: '#f0464f',
    grid: '#171e25',
    text: '#67737f',
    rule: '#222a33',
};

function volumeBar(bar: CandleBar) {
    return {
        time: bar.time as UTCTimestamp,
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(31,184,115,0.35)' : 'rgba(240,70,79,0.35)',
    };
}

function candle(bar: CandleBar) {
    return { time: bar.time as UTCTimestamp, open: bar.open, high: bar.high, low: bar.low, close: bar.close };
}

/**
 * 1m candles from Hyperliquid with the model's withheld fills marked on the bar
 * they printed in. Full history is set once; live ticks go through series.update.
 */
export function PriceChart() {
    const host = useRef<HTMLDivElement>(null);
    const chart = useRef<IChartApi | null>(null);
    const candles = useRef<ISeriesApi<'Candlestick'> | null>(null);
    const volume = useRef<ISeriesApi<'Histogram'> | null>(null);
    const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

    const interval = useMarket((s) => s.candleInterval);
    const history = useMarket((s) => s.candles);
    const last = useMarket((s) => s.lastCandle);
    const resolved = useMarket((s) => s.resolved);
    const decimals = useMarket((s) => s.feed.priceDecimals);

    useEffect(() => {
        if (!host.current) return;
        const api = createChart(host.current, {
            autoSize: true,
            layout: {
                background: { type: ColorType.Solid, color: 'transparent' },
                textColor: COLORS.text,
                fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
                fontSize: 11,
                attributionLogo: false,
            },
            grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
            rightPriceScale: { borderColor: COLORS.rule },
            timeScale: { borderColor: COLORS.rule, timeVisible: true, secondsVisible: false },
            crosshair: { mode: CrosshairMode.Normal },
        });
        candles.current = api.addSeries(CandlestickSeries, {
            upColor: COLORS.up,
            downColor: COLORS.down,
            borderVisible: false,
            wickUpColor: COLORS.up,
            wickDownColor: COLORS.down,
        });
        volume.current = api.addSeries(HistogramSeries, {
            priceScaleId: 'volume',
            priceFormat: { type: 'volume' },
            lastValueVisible: false,
            priceLineVisible: false,
        });
        api.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
        markers.current = createSeriesMarkers(candles.current, []);
        chart.current = api;
        return () => {
            api.remove();
            chart.current = null;
        };
    }, []);

    useEffect(() => {
        candles.current?.applyOptions({
            priceFormat: { type: 'price', precision: decimals, minMove: 10 ** -decimals },
        });
    }, [decimals]);

    useEffect(() => {
        candles.current?.setData(history.map(candle));
        volume.current?.setData(history.map(volumeBar));
        if (history.length) chart.current?.timeScale().scrollToRealTime();
    }, [history]);

    useEffect(() => {
        if (!last) return;
        candles.current?.update(candle(last));
        volume.current?.update(volumeBar(last));
    }, [last]);

    useEffect(() => {
        const bucket = CANDLE_INTERVALS[interval] / 1000;
        const marks: SeriesMarker<Time>[] = resolved
            .filter((fill) => fill.action === 'withhold')
            .slice(0, 40)
            .map(
                (fill): SeriesMarker<Time> => ({
                    time: (Math.floor(fill.time / 1000 / bucket) * bucket) as UTCTimestamp,
                    position: fill.makerSide === 1 ? 'belowBar' : 'aboveBar',
                    shape: 'circle',
                    size: 0.6,
                    color: fill.regret ? COLORS.down : COLORS.text,
                }),
            )
            .sort((a, b) => Number(a.time) - Number(b.time));
        markers.current?.setMarkers(marks);
    }, [resolved, interval]);

    return <div ref={host} className="chart-host" aria-label={`SOL-PERP ${interval} candles`} role="img" />;
}

export function ChartIntervals() {
    const interval = useMarket((s) => s.candleInterval);
    return (
        <div className="pills" role="radiogroup" aria-label="Candle interval">
            {(Object.keys(CANDLE_INTERVALS) as CandleInterval[]).map((option) => (
                <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={option === interval}
                    className="pill"
                    onClick={() => marketFeed.setCandleInterval(option)}
                >
                    {option}
                </button>
            ))}
        </div>
    );
}
