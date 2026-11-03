import { useState, type ReactNode } from 'react';
import { SYMBOL } from '../config';
import { fixed, percent, signed, signedPercent, usdCompact } from '../lib/format';
import { useMarket, useNow } from '../market/useMarket';
import Counter from './reactbits/Counter';

type Tone = 'up' | 'down' | '';

/** Colour the mark by its last move, the way venues tint the headline price. */
function useTickDirection(value: number | undefined): Tone {
    const [last, setLast] = useState<{ value: number | undefined; direction: Tone }>({ value, direction: '' });
    if (Object.is(value, last.value)) return last.direction;
    // Adjusting state during render: React re-renders before committing, no extra effect pass.
    const direction = value !== undefined && last.value !== undefined ? (value > last.value ? 'up' : 'down') : last.direction;
    setLast({ value, direction });
    return direction;
}

const toneOf = (value: number | undefined): Tone => (value === undefined ? '' : value >= 0 ? 'up' : 'down');

function fundingCountdown(now: number): string {
    const left = Math.ceil(now / 3_600_000) * 3_600_000 - now;
    const m = Math.floor(left / 60_000);
    const s = Math.floor((left % 60_000) / 1000);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function MarketHeader() {
    const ctx = useMarket((s) => s.ctx);
    const book = useMarket((s) => s.book);
    const decimals = useMarket((s) => s.priceDecimals);
    const now = useNow();
    const tick = useTickDirection(ctx?.markPx);
    const changePct = ctx && ctx.prevDayPx > 0 ? (ctx.markPx - ctx.prevDayPx) / ctx.prevDayPx : undefined;

    return (
        <section className="market-header" aria-label={`${SYMBOL} market summary`}>
            <div className="symbol">
                <span className="symbol-name">{SYMBOL}</span>
                <span className="symbol-venue">Hyperliquid</span>
            </div>
            <div className={`mark ${tick}`}>
                {ctx ? (
                    <Counter value={ctx.markPx} decimals={decimals} duration={0.3} stagger={0.015} fade={0.2} fontSize={18} />
                ) : (
                    <span className="num">–</span>
                )}
            </div>
            <dl className="header-stats">
                <HeaderStat label="Oracle" hint="Oracle price used for funding and liquidations">
                    {ctx ? fixed(ctx.oraclePx, decimals) : '–'}
                </HeaderStat>
                <HeaderStat label="24h change" tone={toneOf(changePct)}>
                    {ctx ? `${signed(ctx.markPx - ctx.prevDayPx, decimals)} / ${signedPercent(changePct)}` : '–'}
                </HeaderStat>
                <HeaderStat label="24h volume">{usdCompact(ctx?.dayNtlVlm)}</HeaderStat>
                <HeaderStat label="Open interest" hint="Open interest in USD at the mark price">
                    {ctx ? usdCompact(ctx.openInterest * ctx.markPx) : '–'}
                </HeaderStat>
                <HeaderStat
                    label="Funding / next"
                    hint="Hourly funding rate and time to the next funding payment"
                    tone={toneOf(ctx?.funding)}
                >
                    {ctx ? `${percent(ctx.funding, 4)} ${fundingCountdown(now)}` : '–'}
                </HeaderStat>
                <HeaderStat label="Spread" hint="Best ask minus best bid, in basis points of mid">
                    {book ? `${fixed(book.top.spreadBps, 2)} bps` : '–'}
                </HeaderStat>
                <HeaderStat
                    label="Top imbalance"
                    hint="(bid size − ask size) / (bid size + ask size) at the touch; a model feature"
                    tone={toneOf(book?.top.imbalance)}
                >
                    {book ? signed(book.top.imbalance, 2) : '–'}
                </HeaderStat>
                <HeaderStat
                    label="10 s OFI"
                    hint="Normalized order-flow imbalance over the last 10 s; the baseline's only signal"
                    tone={toneOf(book?.ofi.ofi10s)}
                >
                    {book ? signed(book.ofi.ofi10s, 2) : '–'}
                </HeaderStat>
            </dl>
        </section>
    );
}

function HeaderStat({ label, hint, tone = '', children }: { label: string; hint?: string; tone?: Tone; children: ReactNode }) {
    return (
        <div className="header-stat" title={hint}>
            <dt className={hint ? 'has-hint' : undefined}>{label}</dt>
            <dd className={`num ${tone}`}>{children}</dd>
        </div>
    );
}
