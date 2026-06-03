export function clamp(value: number, min: number, max: number): number {
    return Math.min(max, Math.max(min, value));
}

export function formatNumber(value: number): string {
    return new Intl.NumberFormat('en-US').format(value);
}

export function price(value: number | undefined | null): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
    return value.toLocaleString('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 2,
    });
}

export function formatDuration(ms: number | undefined | null): string {
    if (!ms || ms < 1) return ms === 0 ? '0 ms' : '-';
    if (ms < 1000) return `${Math.round(ms)} ms`;
    const seconds = ms / 1000;
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function formatTimestamp(value: string | undefined | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleString('en-US', {
        month: 'short',
        day: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    });
}

export function formatClock(value: string | undefined | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
    });
}

export function formatDate(value: string | undefined | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function relativeTime(value: string | undefined | null): string {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '-';
    const seconds = Math.max(1, Math.round((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours}h ago`;
    return formatDate(value);
}

export function shortId(value: string | undefined | null): string {
    if (!value) return '-';
    if (value.length <= 18) return value;
    return value.replace(/^loop_/, 'IL-').replace(/^case_/, 'INV-').slice(0, 18);
}

export function shortCycle(value: string | undefined | null): string {
    if (!value) return '-';
    const digits = value.replace(/\D/g, '').slice(-5);
    return digits ? Number(digits).toLocaleString('en-US') : shortId(value);
}

export function sentenceCase(value: string | undefined | null): string {
    if (!value) return '-';
    return value
        .replaceAll('_', ' ')
        .replaceAll('-', ' ')
        .split(' ')
        .filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

export function compactScenario(value: string | undefined | null): string {
    const clean = sentenceCase(value);
    const families = [
        'Cascade Replay',
        'Liquidation Cascade',
        'Liquidation Sweep',
        'Funding Dislocation',
        'Basis Dislocation',
        'Momentum Ignition',
        'Latency Arb',
    ];
    const match = families.find((family) => clean.toLowerCase().includes(family.toLowerCase()));
    if (match) return match;
    return truncate(clean, 34);
}

export function humanizeFeature(value: string): string {
    return sentenceCase(value.replace(/^w\d+_/, '').replaceAll('/', ' '));
}

export function cleanText(value: string): string {
    return value.replace(/\*\*/g, '').replace(/`/g, '').replace(/\s+/g, ' ').trim();
}

export function truncate(value: string, maxLength: number): string {
    if (value.length <= maxLength) return value;
    return `${value.slice(0, maxLength - 1).trim()}…`;
}

export function signed(value: number): string {
    return `${value >= 0 ? '+' : ''}${value.toFixed(Math.abs(value) >= 10 ? 0 : 2)}`;
}

export function scoreValue(value: number | undefined | null): string {
    return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '-';
}

export function metricValue(value: unknown, suffix = ''): string {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '-';
    return `${numeric.toFixed(Math.abs(numeric) >= 10 ? 1 : 3)}${suffix}`;
}
