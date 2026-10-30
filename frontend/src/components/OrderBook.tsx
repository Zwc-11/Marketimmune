import { memo } from 'react';
import { COIN } from '../config';
import { fixed } from '../lib/format';
import type { Level } from '../market/feed';
import { useMarket } from '../market/useMarket';
import { Empty } from './Panel';

interface Row extends Level {
    total: number;
}

function withTotals(levels: Level[]): Row[] {
    let total = 0;
    return levels.map((level) => {
        total += level.sz;
        return { ...level, total };
    });
}

const BookRow = memo(function BookRow({
    row,
    side,
    maxTotal,
    decimals,
}: {
    row: Row;
    side: 'bid' | 'ask';
    maxTotal: number;
    decimals: number;
}) {
    const depth = maxTotal > 0 ? (row.total / maxTotal) * 100 : 0;
    return (
        <tr className={`book-row ${side}`} style={{ '--depth': `${depth}%` } as React.CSSProperties}>
            <td className={`num ${side === 'bid' ? 'up' : 'down'}`}>{fixed(row.px, decimals)}</td>
            <td className="num">{fixed(row.sz, 2)}</td>
            <td className="num muted">{fixed(row.total, 2)}</td>
        </tr>
    );
});

export function OrderBook() {
    const book = useMarket((s) => s.book);
    const decimals = useMarket((s) => s.feed.priceDecimals);
    if (!book) return <Empty title="Waiting for the first book snapshot" />;

    const bids = withTotals(book.bids);
    const asks = withTotals(book.asks);
    const maxTotal = Math.max(bids[bids.length - 1]?.total ?? 0, asks[asks.length - 1]?.total ?? 0);
    const spread = book.top.askPx - book.top.bidPx;

    return (
        <table className="book" aria-label={`${COIN} order book`}>
            <thead>
                <tr>
                    <th className="num">Price</th>
                    <th className="num">Size ({COIN})</th>
                    <th className="num">Total ({COIN})</th>
                </tr>
            </thead>
            <tbody>
                {[...asks].reverse().map((row) => (
                    <BookRow key={`a${row.px}`} row={row} side="ask" maxTotal={maxTotal} decimals={decimals} />
                ))}
                <tr className="book-spread">
                    <td className="num">{fixed(book.top.mid, decimals + 1)}</td>
                    <td className="num faint">Spread</td>
                    <td className="num faint">
                        {fixed(spread, decimals)} ({fixed(book.top.spreadBps, 2)} bps)
                    </td>
                </tr>
                {bids.map((row) => (
                    <BookRow key={`b${row.px}`} row={row} side="bid" maxTotal={maxTotal} decimals={decimals} />
                ))}
            </tbody>
        </table>
    );
}
