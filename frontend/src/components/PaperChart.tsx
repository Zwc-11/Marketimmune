import { ColorType, createChart, LineSeries, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { useEffect, useRef } from 'react';
import { STRATEGY_COLORS } from '../data/paper';

const QUIET = 'rgba(158, 169, 180, 0.28)';

const PRICE = '#e1e6eb';

function points(raw: [number, number][]) {
    const seen = new Set<number>();
    const data = [];
    for (const [t, v] of raw) {
        const s = Math.floor(t / 1000);
        if (seen.has(s)) continue;
        seen.add(s);
        data.push({ time: s as UTCTimestamp, value: v });
    }
    return data;
}

/** Cumulative paper PnL per strategy, one line each; the named strategies in colour, the rest quiet.
 * ``price``: one coin's mid on the left scale, to read the PnL against the market. */
export function PaperChart({
    history,
    focus,
    price,
    colors = STRATEGY_COLORS,
}: {
    history: Record<string, [number, number][]>;
    focus: string[];
    price?: { label: string; points: [number, number][] };
    colors?: Record<string, string>;
}) {
    const host = useRef<HTMLDivElement>(null);
    const chart = useRef<IChartApi | null>(null);
    const lines = useRef(new Map<string, ISeriesApi<'Line'>>());
    const priceLine = useRef<ISeriesApi<'Line'> | null>(null);
    const fitted = useRef(false);

    useEffect(() => {
        const api = createChart(host.current!, {
            autoSize: true,
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#67737f', fontSize: 11, attributionLogo: false },
            grid: { vertLines: { color: '#171e25' }, horzLines: { color: '#171e25' } },
            rightPriceScale: { borderColor: '#222a33' },
            leftPriceScale: { borderColor: '#222a33', visible: true },
            timeScale: { borderColor: '#222a33', timeVisible: true, secondsVisible: false },
            localization: {
                priceFormatter: (v: number) => `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2 })}`,
            },
        });
        chart.current = api;
        const map = lines.current;
        return () => {
            map.clear();
            priceLine.current = null;
            api.remove();
        };
    }, []);

    useEffect(() => {
        const api = chart.current;
        if (!api) return;
        for (const [name, raw] of Object.entries(history)) {
            let line = lines.current.get(name);
            const named = focus.includes(name);
            if (!line) {
                line = api.addSeries(LineSeries, {
                    color: named ? (colors[name] ?? '#e1e6eb') : QUIET,
                    lineWidth: named ? 2 : 1,
                    lineStyle: name === 'touch' ? LineStyle.Dashed : LineStyle.Solid,
                    priceLineVisible: false,
                    lastValueVisible: named,
                    title: named ? name : '',
                    crosshairMarkerVisible: named,
                });
                lines.current.set(name, line);
            }
            line.setData(points(raw));
        }
        if (!fitted.current && Object.keys(history).length) {
            // Open on the whole run once the chart has its size; the reader's zoom is kept after.
            window.setTimeout(() => chart.current?.timeScale().fitContent(), 250);
            fitted.current = true;
        }
    }, [history, focus, colors]);

    useEffect(() => {
        const api = chart.current;
        if (!api || !price) return;
        if (!priceLine.current) {
            priceLine.current = api.addSeries(LineSeries, {
                color: PRICE,
                lineWidth: 1,
                lineStyle: LineStyle.Dotted,
                priceScaleId: 'left',
                priceLineVisible: false,
                lastValueVisible: true,
                title: price.label,
                priceFormat: { type: 'price', precision: 0, minMove: 1 },
            });
        }
        priceLine.current.setData(points(price.points));
    }, [price]);

    return <div ref={host} className="paper-chart" />;
}
