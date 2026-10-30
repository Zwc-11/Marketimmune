import { integer } from '../lib/format';
import type { TapeFill } from '../lib/regret';
import { useMarket } from '../market/useMarket';

const CELLS = 100;

function cellClass(fill: TapeFill | undefined): string {
    if (!fill) return 'cell';
    const base = fill.regret ? 'cell regret' : (fill.markoutBps ?? 0) >= 0 ? 'cell gain' : 'cell small-loss';
    return fill.action === 'withhold' ? `${base} withheld` : base;
}

/**
 * The last 100 resolved maker fills, oldest top-left. One square per fill:
 * red regretted, green kept with a gain, grey kept with a loss inside the 1 bps fee.
 * A hollow square is a fill the model would have withheld.
 */
export function RegretMatrix() {
    const resolved = useMarket((s) => s.resolved);
    const recent = resolved.slice(0, CELLS);
    const ordered = [...recent].reverse();
    const cells = Array.from({ length: CELLS }, (_, i) => ordered[i]);
    const regret = recent.filter((f) => f.regret).length;
    const gain = recent.filter((f) => !f.regret && (f.markoutBps ?? 0) >= 0).length;
    const withheld = recent.filter((f) => f.action === 'withhold').length;

    return (
        <figure className="matrix" aria-label={`Last ${recent.length} resolved fills: ${regret} regretted`}>
            <div className="matrix-grid" aria-hidden="true">
                {cells.map((fill, i) => (
                    <span key={fill?.id ?? `empty-${i}`} className={cellClass(fill)} />
                ))}
            </div>
            <figcaption className="matrix-legend">
                <span className="matrix-title">Last {CELLS} resolved fills</span>
                <span />
                <span><i className="swatch regret" />Regretted</span>
                <span className="num">{integer(regret)}</span>
                <span><i className="swatch gain" />Kept, maker gained</span>
                <span className="num">{integer(gain)}</span>
                <span><i className="swatch small-loss" />Kept, under the fee</span>
                <span className="num">{integer(recent.length - regret - gain)}</span>
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
