import { memo, useState } from 'react';
import { HORIZON_MS } from '../config';
import { fixed, signed } from '../lib/format';
import type { TapeFill } from '../lib/regret';
import { marketFeed } from '../market/feed';
import { useMarket } from '../market/useMarket';
import { Empty } from './Panel';

/**
 * The 10-second regret clock. Each pending fill draws a bar that fills over the
 * label horizon (pure CSS, started at mount with a negative delay so it is in
 * phase with the exchange clock); when the horizon's mid prints, the row settles
 * into the realized maker markout.
 */
const TapeRow = memo(function TapeRow({ fill, decimals }: { fill: TapeFill; decimals: number }) {
    const [delay] = useState(() => {
        const exchangeNow = Date.now() - marketFeed.getSnapshot().feed.clockOffsetMs;
        return -Math.min(HORIZON_MS, Math.max(0, exchangeNow - fill.time));
    });
    const side = fill.makerSide === 1 ? 'Bid' : 'Ask';
    return (
        <tr className={fill.regret ? 'tape-row regret' : 'tape-row'}>
            <td className="num">{fixed(fill.px, decimals)}</td>
            <td className="num">{fixed(fill.sz, 2)}</td>
            <td className={`tape-side ${fill.makerSide === 1 ? 'up' : 'down'}`}>{side}</td>
            <td className={`num ${fill.action === 'withhold' ? 'down' : 'muted'}`}>
                {fill.score === null ? '–' : fixed(fill.score, 2)}
            </td>
            <td className="tape-outcome num">
                {fill.markoutBps === null ? (
                    <span
                        className="clock-bar"
                        style={
                            {
                                '--clock-delay': `${delay}ms`,
                                '--clock-duration': `${HORIZON_MS}ms`,
                            } as React.CSSProperties
                        }
                        aria-label="Waiting for the 10 s mid"
                    />
                ) : (
                    <span className={fill.regret ? 'down' : fill.markoutBps >= 0 ? 'up' : 'muted'}>
                        {signed(fill.markoutBps, 2)}
                    </span>
                )}
            </td>
        </tr>
    );
});

export function RegretTape() {
    const tape = useMarket((s) => s.tape);
    const decimals = useMarket((s) => s.feed.priceDecimals);
    if (!tape.length) return <Empty title="Waiting for SOL-PERP fills" />;
    return (
        <table className="tape" aria-label="Maker fills and their 10 s markout">
            <thead>
                <tr>
                    <th className="num">Price</th>
                    <th className="num">Size</th>
                    <th title="Which resting side was filled: a bid hit by a seller, or an ask lifted by a buyer">Rested</th>
                    <th className="num" title="Model probability the maker regrets this fill at 10 s">p(regret)</th>
                    <th className="num" title="Maker markout 10 s after the fill, in bps of fill price">10 s bps</th>
                </tr>
            </thead>
            <tbody>
                {tape.map((fill) => (
                    <TapeRow key={fill.id} fill={fill} decimals={decimals} />
                ))}
            </tbody>
        </table>
    );
}
