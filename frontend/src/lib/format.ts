// Number formatting for dense tables. Every formatter returns a placeholder for
// missing or non-finite input so a stalled feed never renders "NaN".

const DASH = '–';

function finite(value: number | null | undefined): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

const fixedCache = new Map<number, Intl.NumberFormat>();
function fixedFormatter(decimals: number): Intl.NumberFormat {
    let formatter = fixedCache.get(decimals);
    if (!formatter) {
        formatter = new Intl.NumberFormat('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        fixedCache.set(decimals, formatter);
    }
    return formatter;
}

export function fixed(value: number | null | undefined, decimals = 2): string {
    return finite(value) ? fixedFormatter(decimals).format(value) : DASH;
}

export function signed(value: number | null | undefined, decimals = 2): string {
    if (!finite(value)) return DASH;
    const text = fixedFormatter(decimals).format(Math.abs(value));
    if (value > 0) return `+${text}`;
    if (value < 0) return `−${text}`;
    return text;
}

export function bps(value: number | null | undefined, decimals = 2): string {
    return finite(value) ? `${signed(value, decimals)} bps` : DASH;
}

export function percent(value: number | null | undefined, decimals = 1): string {
    return finite(value) ? `${fixed(value * 100, decimals)}%` : DASH;
}

export function signedPercent(value: number | null | undefined, decimals = 2): string {
    return finite(value) ? `${signed(value * 100, decimals)}%` : DASH;
}

const compactUsd = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 2,
});

export function usdCompact(value: number | null | undefined): string {
    return finite(value) ? compactUsd.format(value) : DASH;
}

export function integer(value: number | null | undefined): string {
    return finite(value) ? fixedFormatter(0).format(value) : DASH;
}

export function clockTime(ms: number | null | undefined): string {
    if (!finite(ms)) return DASH;
    const date = new Date(ms);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function utcDate(ms: number | null | undefined): string {
    if (!finite(ms)) return DASH;
    return new Date(ms).toISOString().slice(0, 10);
}

export function yyyymmdd(value: string): string {
    return /^\d{8}$/.test(value)
        ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`
        : value;
}

export function durationMs(value: number | null | undefined): string {
    if (!finite(value)) return DASH;
    if (value < 1) return `${fixed(value * 1000, 0)} µs`;
    if (value < 1000) return `${fixed(value, value < 10 ? 2 : 0)} ms`;
    return `${fixed(value / 1000, 1)} s`;
}

/** Decimal places to show for a price, inferred from the venue's tick strings. */
export function priceDecimals(samples: string[]): number {
    let decimals = 0;
    for (const sample of samples) {
        const dot = sample.indexOf('.');
        if (dot >= 0) decimals = Math.max(decimals, sample.length - dot - 1);
    }
    return Math.min(decimals, 6);
}
