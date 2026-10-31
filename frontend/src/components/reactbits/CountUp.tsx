// Vendored from React Bits CountUp (https://reactbits.dev), (c) David Haz. MIT + Commons
// Clause; see ./NOTICE.md. Trimmed to the one mode MarketImmune uses: count from 0 up
// to a non-negative `to` once on mount, eased out, then stay static. Upstream drives
// this with motion's animate() and cubic-bezier(0.33, 1, 0.68, 1); here it is one
// requestAnimationFrame loop and the cubic ease-out that bezier approximates.

import { useEffect, useRef } from 'react';

const easeOut = (t: number) => 1 - (1 - t) ** 3;

export default function CountUp({ to, decimals, duration }: { to: number; decimals: number; duration: number }) {
    const ref = useRef<HTMLSpanElement>(null);
    useEffect(() => {
        const node = ref.current!;
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            node.textContent = to.toFixed(decimals);
            return undefined;
        }
        let start: number | null = null;
        let raf = 0;
        const tick = (now: number) => {
            start ??= now;
            const t = Math.min(1, (now - start) / (duration * 1000));
            node.textContent = (to * easeOut(t)).toFixed(decimals);
            if (t < 1) raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(raf);
    }, [to, decimals, duration]);
    return (
        <span ref={ref} style={{ fontVariantNumeric: 'tabular-nums' }}>
            {(0).toFixed(decimals)}
        </span>
    );
}
