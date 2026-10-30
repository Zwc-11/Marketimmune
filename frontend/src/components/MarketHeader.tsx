import { useEffect, useRef, useState } from 'react';
import { SYMBOL } from '../config';
import { fixed, percent, signed, signedPercent, usdCompact } from '../lib/format';
import { useMarket, useNow } from '../market/useMarket';
import Counter from './reactbits/Counter';

/** Colour the mark by its last move, the way venues tint the headline price. */
function useTickDirection(value: number | undefined): 'up' | 'down' | '' {
    const previous = useRef<number | undefined>(undefined);
    const [direction, setDirection] = useState<'up' | 'down' | ''>('');
    useEffect(() => {
        if (value !== undefined && previous.current !== undefined && value !== previous.current) {
            setDirection(value > previous.current ? 'up' : 'down');
        }
        previous.current = value;
    }, [value]);
    return direction;
}

function fundingCountdown(now: number): string {
    const next = Math.ceil(now / 3_600_000) * 3_600_000;
    const left = Math.max(0, next - now);
    const m = Math.floor(left / 60_000);
    const s = Math.floor((left % 60_000) / 1000);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function MarketHeader() {
    const ctx = useMarket((s) => s.ctx);
    const book = useMarket((s) => s.book);
    const decimals = useMarket((s) => s.feed.priceDecimals);
    const now = useNow();
    const tick = useTickDirection(ctx?.markPx);
    const change = ctx ? ctx.markPx - ctx.prevDayPx : undefined;
    const changePct = ctx && ctx.prevDayPx > 0 ? (ctx.markPx - ctx.prevDayPx) / ctx.prevDayPx : undefined;

    return (
        <section className="market-header" aria-label={`${SYMBOL} market summary`}>
            <div className="symbol">
                <span className="symbol-name">{SYMBOL}</span>
                <span className="symbol-venue">Hyperliquid</span>
            </div>
            <div className={`mark ${tick}`}>
                {ctx ? (
                    <Counter
                        value={ctx.markPx}
                        decimals={decimals}
                        duration={0.3}
                        bounce={0}
                        stagger={0.015}
                        motionBlur={false}
                        intro={false}
                        fade={0.2}
                        fontSize={18}
                        fontWeight={500}
                        textColor="currentColor"
                    />
                ) : (
                    <span className="num">–</span>
                )}
            </div>
            <dl className="header-stats">
                <HeaderStat label="Oracle" hint="Oracle price used for funding and liquidations">
                    {ctx ? fixed(ctx.oraclePx, decimals) : '–'}
                </HeaderStat>
                <HeaderStat label="24h change" tone={changePct === undefined ? '' : changePct >= 0 ? 'up' : 'down'}>
                    {change === undefined ? '–' : `${signed(change, decimals)} / ${signedPercent(changePct)}`}
                </HeaderStat>
                <HeaderStat label="24h volume">{usdCompact(ctx?.dayNtlVlm)}</HeaderStat>
                <HeaderStat label="Open interest" hint="Open interest in USD at the mark price">
                    {ctx ? usdCompact(ctx.openInterest * ctx.markPx) : '–'}
                </HeaderStat>
                <HeaderStat
                    label="Funding / next"
                    hint="Hourly funding rate and time to the next funding payment"
                    tone={ctx ? (ctx.funding >= 0 ? 'up' : 'down') : ''}
                >
                    {ctx ? `${percent(ctx.funding, 4)} ${fundingCountdown(now)}` : '–'}
                </HeaderStat>
                <HeaderStat label="Spread" hint="Best ask minus best bid, in basis points of mid">
                    {book ? `${fixed(book.top.spreadBps, 2)} bps` : '–'}
                </HeaderStat>
                <HeaderStat
                    label="Top imbalance"
                    hint="(bid size − ask size) / (bid size + ask size) at the touch; a model feature"
                    tone={book ? (book.top.imbalance >= 0 ? 'up' : 'down') : ''}
                >
                    {book ? signed(book.top.imbalance, 2) : '–'}
                </HeaderStat>
                <HeaderStat
                    label="10 s OFI"
                    hint="Normalized order-flow imbalance over the last 10 s; the baseline's only signal"
                    tone={book ? (book.ofi.ofi10s >= 0 ? 'up' : 'down') : ''}
                >
                    {book ? signed(book.ofi.ofi10s, 2) : '–'}
                </HeaderStat>
            </dl>
        </section>
    );
}

function HeaderStat({
    label,
    hint,
    tone = '',
    children,
}: {
    label: string;
    hint?: string;
    tone?: string;
    children: React.ReactNode;
}) {
    return (
        <div className="header-stat" title={hint}>
            <dt className={hint ? 'has-hint' : undefined}>{label}</dt>
            <dd className={`num ${tone}`}>{children}</dd>
        </div>
    );
}
