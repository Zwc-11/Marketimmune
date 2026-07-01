import type { ChartTimeframe } from '../lib/replay';
import { CHART_TIMEFRAMES } from '../lib/replay';

export function TimeframePills({
    value,
    onChange,
}: {
    value: ChartTimeframe;
    onChange: (timeframe: ChartTimeframe) => void;
}) {
    return (
        <div className="timeframe-pills" role="group" aria-label="Chart timeframe">
            {CHART_TIMEFRAMES.map((timeframe) => (
                <button
                    key={timeframe}
                    type="button"
                    className={value === timeframe ? 'active' : ''}
                    aria-pressed={value === timeframe}
                    onClick={() => onChange(timeframe)}
                >
                    {timeframe.toUpperCase()}
                </button>
            ))}
        </div>
    );
}
