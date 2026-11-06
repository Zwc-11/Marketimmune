import { ColorType, createChart, LineSeries, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts';
import { useEffect, useRef } from 'react';
import { STRATEGY_COLORS } from '../data/paper';

const QUIET = 'rgba(158, 169, 180, 0.28)';

/** Cumulative paper PnL per strategy, one line each; the named strategies in colour, the rest quiet. */
export function PaperChart({ history, focus }: { history: Record<string, [number, number][]>; focus: string[] }) {
    const host = useRef<HTMLDivElement>(null);
    const chart = useRef<IChartApi | null>(null);
    const lines = useRef(new Map<string, ISeriesApi<'Line'>>());

    useEffect(() => {
        const api = createChart(host.current!, {
            autoSize: true,
            layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#67737f', fontSize: 11, attributionLogo: false },
            grid: { vertLines: { color: '#171e25' }, horzLines: { color: '#171e25' } },
            rightPriceScale: { borderColor: '#222a33' },
            timeScale: { borderColor: '#222a33', timeVisible: true, secondsVisible: false },
            localization: { priceFormatter: (v: number) => `${v < 0 ? '−' : ''}$${Math.abs(v).toFixed(0)}` },
        });
        chart.current = api;
        const map = lines.current;
        return () => {
            map.clear();
            api.remove();
        };
    }, []);

    useEffect(() => {
        const api = chart.current;
        if (!api) return;
        for (const [name, points] of Object.entries(history)) {
            let line = lines.current.get(name);
            const named = focus.includes(name);
            if (!line) {
                line = api.addSeries(LineSeries, {
                    color: named ? (STRATEGY_COLORS[name] ?? '#e1e6eb') : QUIET,
                    lineWidth: named ? 2 : 1,
                    lineStyle: name === 'touch' ? LineStyle.Dashed : LineStyle.Solid,
                    priceLineVisible: false,
                    lastValueVisible: named,
                    title: named ? name : '',
                    crosshairMarkerVisible: named,
                });
                lines.current.set(name, line);
            }
            const seen = new Set<number>();
            const data = [];
            for (const [t, v] of points) {
                const s = Math.floor(t / 1000);
                if (seen.has(s)) continue;
                seen.add(s);
                data.push({ time: s as UTCTimestamp, value: v });
            }
            line.setData(data);
        }
    }, [history, focus]);

    return <div ref={host} className="paper-chart" />;
}
