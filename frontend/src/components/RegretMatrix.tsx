import { integer } from '../lib/format';
import type { ResolvedFill } from '../lib/regret';
import { useMarket } from '../market/useMarket';

const CELLS = 100;

function cellClass(fill: ResolvedFill): string {
    const base = fill.regret ? 'cell regret' : fill.markoutBps >= 0 ? 'cell gain' : 'cell small-loss';
    return fill.action === 'withhold' ? `${base} withheld` : base;
}

/**
 * The last 100 resolved maker fills, oldest top-left. One square per fill:
 * red regretted, green kept with a gain, grey kept with a loss inside the 1 bps fee.
 * A hollow square is a fill the model would have withheld.
 */
export function RegretMatrix() {
    const resolved = useMarket((s) => s.resolved);
    const shown = Math.min(CELLS, resolved.length);
    const cells = [];
    let regret = 0;
    let gain = 0;
    let withheld = 0;
    // `resolved` is newest first; walk it backwards so the oldest lands top-left.
    for (let i = shown - 1; i >= 0; i -= 1) {
        const fill = resolved[i];
        if (fill.regret) regret += 1;
        else if (fill.markoutBps >= 0) gain += 1;
        if (fill.action === 'withhold') withheld += 1;
        cells.push(<span key={fill.id} className={cellClass(fill)} />);
    }
    for (let i = shown; i < CELLS; i += 1) cells.push(<span key={`empty-${i}`} className="cell" />);

    return (
        <figure className="matrix" aria-label={`Last ${shown} resolved fills: ${regret} regretted`}>
            <div className="matrix-grid" aria-hidden="true">
                {cells}
            </div>
            <figcaption className="matrix-legend">
                <span className="matrix-title">Last {CELLS} resolved fills</span>
                <span />
                <span><i className="swatch regret" />Regretted</span>
                <span className="num">{integer(regret)}</span>
                <span><i className="swatch gain" />Kept, maker gained</span>
                <span className="num">{integer(gain)}</span>
                <span><i className="swatch small-loss" />Kept, under the fee</span>
                <span className="num">{integer(shown - regret - gain)}</span>
                {withheld > 0 && (
                    <>
                        <span><i className="swatch withheld" />Model would withhold</span>
                        <span className="num">{integer(withheld)}</span>
                    </>
                )}
            </figcaption>
        </figure>
    );
}
