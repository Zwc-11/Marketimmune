import { memo, type CSSProperties } from 'react';
import { COIN } from '../config';
import { fixed } from '../lib/format';
import type { Level } from '../market/feed';
import { useMarket } from '../market/useMarket';
import { Empty } from './Panel';

/**
 * Primitive props only, so a level whose price, size and cumulative size are
 * unchanged skips rendering. The depth bar is `--total / --max` in CSS, so a new
 * deepest total restyles the bars without re-rendering every row.
 */
const BookRow = memo(function BookRow({
    px,
    sz,
    total,
    side,
    decimals,
}: {
    px: number;
    sz: number;
    total: number;
    side: 'bid' | 'ask';
    decimals: number;
}) {
    return (
        <tr className={`book-row ${side}`} style={{ '--total': String(total) } as CSSProperties}>
            <td className={`num ${side === 'bid' ? 'up' : 'down'}`}>{fixed(px, decimals)}</td>
            <td className="num">{fixed(sz, 2)}</td>
            <td className="num muted">{fixed(total, 2)}</td>
        </tr>
    );
});

export function OrderBook() {
    const book = useMarket((s) => s.book);
    const decimals = useMarket((s) => s.priceDecimals);
    if (!book) return <Empty title="Waiting for the first book snapshot" />;

    const { bids, asks, top } = book;
    const maxTotal = Math.max(bids[bids.length - 1].total, asks[asks.length - 1].total);
    const rows = (levels: Level[], side: 'bid' | 'ask') =>
        levels.map(({ px, sz, total }) => (
            <BookRow key={`${side[0]}${px}`} px={px} sz={sz} total={total} side={side} decimals={decimals} />
        ));

    return (
        <table className="book" aria-label={`${COIN} order book`} style={{ '--max': String(maxTotal) } as CSSProperties}>
            <thead>
                <tr>
                    <th className="num">Price</th>
                    <th className="num">Size ({COIN})</th>
                    <th className="num">Total ({COIN})</th>
                </tr>
            </thead>
            <tbody>
                {rows(asks, 'ask').reverse()}
                <tr className="book-spread">
                    <td className="num">{fixed(top.mid, decimals + 1)}</td>
                    <td className="num faint">Spread</td>
                    <td className="num faint">
                        {fixed(top.askPx - top.bidPx, decimals)} ({fixed(top.spreadBps, 2)} bps)
                    </td>
                </tr>
                {rows(bids, 'bid')}
            </tbody>
        </table>
    );
}
