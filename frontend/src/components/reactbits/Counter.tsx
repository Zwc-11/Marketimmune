// Vendored from React Bits Counter (https://reactbits.dev), (c) David Haz. MIT + Commons
// Clause; see ./NOTICE.md. Trimmed to what MarketImmune uses: en-US digits with fixed
// decimals, critically damped digit springs (upstream bounce 0), tabular widths. The
// upstream affixes, custom formats, intro spin and motion blur are removed.

import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import './Counter.css';

interface CounterProps {
    value: number;
    decimals: number;
    /** Spring period, seconds. */
    duration: number;
    /** Start delay between successive moving digits, seconds. */
    stagger: number;
    /** Height of the top and bottom fade, em. */
    fade: number;
    fontSize: number;
}

interface Slot {
    key: string;
    kind: 'digit' | 'symbol';
    digit: number;
    text: string;
    rank: number;
}

interface ListSlot extends Slot {
    start: number;
}

interface Item {
    kind: Slot['kind'];
    rank: number;
    pos: number;
    vel: number;
    target: number;
    shown: number;
    shownVel: number;
    shownTarget: number;
    wait: number;
    exiting: boolean;
    natural: number;
    el: HTMLElement | null;
    numerals: HTMLElement[] | null;
}

interface Engine {
    items: Map<string, Item>;
    raf: number;
    last: number;
    ready: boolean;
    value: number;
    widths: number[];
}

type Trend = 'up' | 'down' | 'shortest';

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
const TAU = Math.PI * 2;
const NUMERIC = new Set(['integer', 'group', 'decimal', 'fraction']);
const REDUCED_MOTION = window.matchMedia('(prefers-reduced-motion: reduce)');

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const mod = (value: number, base: number) => ((value % base) + base) % base;
const wrap = (offset: number) => mod(offset + 5, 10) - 5;

function stepBetween(from: number, to: number, trend: Trend): number {
    const up = mod(to - from, 10);
    if (trend === 'up') return up;
    if (trend === 'down') return up === 0 ? 0 : up - 10;
    return up > 5 ? up - 10 : up;
}

/** One slot per rendered glyph; keys are stable per decimal place so digits roll in place. */
function slotsFor(formatter: Intl.NumberFormat, value: number): Slot[] {
    const parts = formatter.formatToParts(value);
    let first = -1;
    let last = -1;
    let place = 0;
    parts.forEach((part, index) => {
        if (!NUMERIC.has(part.type)) return;
        if (first < 0) first = index;
        last = index;
        if (part.type === 'integer') place += part.value.length;
    });
    let fraction = 0;
    const counts: Record<string, number> = {};
    const slots: Slot[] = [];
    parts.forEach((part, index) => {
        if (part.type === 'integer' || part.type === 'fraction') {
            for (const char of part.value) {
                const digit = Number(char);
                if (part.type === 'integer') {
                    place -= 1;
                    slots.push({ key: `i${place}`, kind: 'digit', digit, text: '', rank: -2 * place });
                } else {
                    slots.push({ key: `f${fraction}`, kind: 'digit', digit, text: '', rank: 1 + fraction });
                    fraction += 1;
                }
            }
        } else if (part.type === 'group') {
            slots.push({ key: `g${place}`, kind: 'symbol', digit: 0, text: part.value, rank: 1 - 2 * place });
        } else if (part.type === 'decimal') {
            slots.push({ key: 'd', kind: 'symbol', digit: 0, text: part.value, rank: 0.5 });
        } else {
            const before = first < 0 || index < first;
            const name = `${before ? 'p' : 's'}-${part.type}`;
            counts[name] = (counts[name] || 0) + 1;
            slots.push({
                key: `${name}-${counts[name]}`,
                kind: 'symbol',
                digit: 0,
                text: part.value,
                rank: before ? -10000 - (first - index) : 10000 + (index - last),
            });
        }
    });
    return slots;
}

const makeItem = (slot: Slot, position: number, shown: number): Item => ({
    kind: slot.kind,
    rank: slot.rank,
    pos: position,
    vel: 0,
    target: position,
    shown,
    shownVel: 0,
    shownTarget: shown,
    wait: 0,
    exiting: false,
    natural: 0,
    el: null,
    numerals: null,
});

function paint(item: Item, widths: number[]): void {
    const el = item.el;
    if (!el) return;
    const shown = clamp(item.shown, 0, 1);
    if (item.kind === 'digit') {
        item.numerals?.forEach((numeral, n) => {
            numeral.style.transform = `translateY(${(wrap(n - item.pos) * 100).toFixed(3)}%)`;
        });
        if (shown >= 1) {
            el.style.width = '';
        } else {
            const at = mod(item.pos, 10);
            const low = Math.floor(at);
            const from = widths[low % 10] ?? 0;
            const to = widths[(low + 1) % 10] ?? from;
            el.style.width = `${((from + (to - from) * (at - low)) * shown).toFixed(2)}px`;
        }
    } else {
        el.style.width = shown >= 1 ? '' : `${(item.natural * shown).toFixed(2)}px`;
    }
    el.style.setProperty('--counter-shown', shown >= 1 ? '' : shown.toFixed(3));
}

function Counter({ value, decimals, duration, stagger, fade, fontSize }: CounterProps) {
    const rowRef = useRef<HTMLSpanElement>(null);
    const measureRef = useRef<HTMLSpanElement>(null);
    const amount = Object.is(value, -0) ? 0 : value;
    const formatter = useMemo(
        () => new Intl.NumberFormat('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
        [decimals],
    );
    const slots = useMemo(() => slotsFor(formatter, amount), [formatter, amount]);
    const [list, setList] = useState<ListSlot[]>(() =>
        slots.map((slot) => ({ ...slot, start: slot.kind === 'digit' ? slot.digit : 0 })),
    );
    const engine = useRef<Engine>({ items: new Map(), raf: 0, last: 0, ready: false, value: amount, widths: [] });
    const settings = useRef({ duration, stagger });
    settings.current = { duration, stagger };

    const frame = (now: number) => {
        const e = engine.current;
        e.raf = 0;
        const elapsed = clamp((now - e.last) / 1000, 0, 1 / 20);
        e.last = now;
        const reduced = REDUCED_MOTION.matches;
        const omega = TAU / settings.current.duration;
        const presence = TAU / (settings.current.duration * 0.85);
        const done: string[] = [];
        let busy = false;
        e.items.forEach((item, key) => {
            if (reduced) {
                item.wait = 0;
                item.pos = item.target;
                item.vel = 0;
                item.shown = item.shownTarget;
                item.shownVel = 0;
            } else {
                let left = elapsed;
                if (item.wait > 0) {
                    const used = Math.min(item.wait, left);
                    item.wait -= used;
                    left -= used;
                }
                if (left > 0) {
                    const steps = Math.ceil(left * 240);
                    const dt = left / steps;
                    for (let i = 0; i < steps; i++) {
                        // Damping ratio 1: the digit settles without overshoot.
                        item.vel += (-omega * omega * (item.pos - item.target) - 2 * omega * item.vel) * dt;
                        item.pos += item.vel * dt;
                        item.shownVel +=
                            (-presence * presence * (item.shown - item.shownTarget) - 2 * presence * item.shownVel) * dt;
                        item.shown += item.shownVel * dt;
                    }
                }
            }
            const settled =
                item.wait <= 0 &&
                Math.abs(item.pos - item.target) < 0.002 &&
                Math.abs(item.vel) < 0.02 &&
                Math.abs(item.shown - item.shownTarget) < 0.002 &&
                Math.abs(item.shownVel) < 0.02;
            if (settled) {
                item.target = mod(Math.round(item.target), 10);
                item.pos = item.target;
                item.vel = 0;
                item.shown = item.shownTarget;
                item.shownVel = 0;
                if (item.exiting) done.push(key);
            } else {
                busy = true;
            }
            paint(item, e.widths);
        });
        if (done.length) {
            done.forEach((key) => e.items.delete(key));
            setList((previous) => previous.filter((slot) => !done.includes(slot.key)));
        }
        if (busy) e.raf = requestAnimationFrame(frame);
    };

    useLayoutEffect(() => {
        const e = engine.current;
        if (!e.ready) {
            slots.forEach((slot) => e.items.set(slot.key, makeItem(slot, slot.kind === 'digit' ? slot.digit : 0, 1)));
            e.ready = true;
            e.value = amount;
            return;
        }
        const previous = Math.abs(e.value);
        e.value = amount;
        const trend: Trend = Math.abs(amount) > previous ? 'up' : Math.abs(amount) < previous ? 'down' : 'shortest';
        const next = new Set(slots.map((slot) => slot.key));
        const moving: Item[] = [];
        slots.forEach((slot) => {
            let item = e.items.get(slot.key);
            if (!item) {
                item = makeItem(slot, 0, 0);
                e.items.set(slot.key, item);
            }
            item.exiting = false;
            item.shownTarget = 1;
            item.rank = slot.rank;
            if (slot.kind !== 'digit') return;
            const step = stepBetween(mod(Math.round(item.target), 10), slot.digit, trend);
            if (step !== 0 || item.shown < 1) {
                item.target += step;
                moving.push(item);
            }
        });
        e.items.forEach((item, key) => {
            if (next.has(key) || item.exiting) return;
            item.exiting = true;
            item.shownTarget = 0;
            if (item.kind !== 'digit') return;
            item.target += stepBetween(mod(Math.round(item.target), 10), 0, trend);
            moving.push(item);
        });
        moving
            .sort((a, b) => b.rank - a.rank)
            .forEach((item, order) => {
                item.wait = order * settings.current.stagger;
            });
        // A group separator appears and leaves together with the digit it follows.
        e.items.forEach((item, key) => {
            if (item.kind !== 'symbol' || key[0] !== 'g') return;
            const owner = e.items.get(`i${key.slice(1)}`);
            if (owner && (owner.shown < 1 || owner.shownTarget < 1)) item.wait = owner.wait;
        });
        setList((previous) => {
            const known = new Map(previous.map((slot) => [slot.key, slot]));
            const merged = slots.map((slot) => ({ ...slot, start: known.get(slot.key)?.start ?? 0 }));
            previous.forEach((slot) => {
                if (!next.has(slot.key)) merged.push(slot);
            });
            merged.sort((a, b) => a.rank - b.rank);
            const same =
                merged.length === previous.length &&
                merged.every(
                    (slot, index) =>
                        slot.key === previous[index].key &&
                        slot.digit === previous[index].digit &&
                        slot.text === previous[index].text,
                );
            return same ? previous : merged;
        });
        if (!e.raf) {
            e.last = performance.now();
            e.raf = requestAnimationFrame(frame);
        }
    }, [slots]);

    useLayoutEffect(() => {
        const e = engine.current;
        rowRef.current!.querySelectorAll<HTMLElement>('[data-slot]').forEach((el) => {
            const item = e.items.get(el.dataset.slot!);
            if (!item) return;
            item.el = el;
            if (item.kind === 'digit') {
                item.numerals = [...el.querySelectorAll<HTMLElement>('[data-numeral]')];
            } else if (item.shown < 1 || item.shownTarget < 1) {
                item.natural = el.firstElementChild!.getBoundingClientRect().width;
            }
            paint(item, e.widths);
        });
    }, [list]);

    useLayoutEffect(() => {
        const row = measureRef.current!;
        let alive = true;
        const measure = () => {
            if (alive) engine.current.widths = [...row.children].map((child) => child.getBoundingClientRect().width);
        };
        measure();
        void document.fonts.ready.then(measure);
        const observer = new ResizeObserver(measure);
        observer.observe(row);
        return () => {
            alive = false;
            observer.disconnect();
        };
    }, []);

    useEffect(() => {
        const e = engine.current;
        return () => cancelAnimationFrame(e.raf);
    }, []);

    return (
        <span className="counter" style={{ fontSize: `${fontSize}px`, '--counter-fade': `${fade}em` } as CSSProperties}>
            <span className="counter__sr">{formatter.format(amount)}</span>
            <span ref={rowRef} className="counter__row" aria-hidden="true">
                {list.map((slot) =>
                    slot.kind === 'digit' ? (
                        <span key={slot.key} data-slot={slot.key} className="counter__digit">
                            <span className="counter__sizer">{slot.digit}</span>
                            <span className="counter__window">
                                <span className="counter__strip">
                                    {DIGITS.map((n) => (
                                        <span
                                            key={n}
                                            className="counter__numeral"
                                            data-numeral=""
                                            style={{ transform: `translateY(${wrap(n - slot.start) * 100}%)` }}
                                        >
                                            {n}
                                        </span>
                                    ))}
                                </span>
                            </span>
                        </span>
                    ) : (
                        <span key={slot.key} data-slot={slot.key} className="counter__symbol">
                            <span className="counter__symbol-text">{slot.text}</span>
                        </span>
                    ),
                )}
            </span>
            <span ref={measureRef} className="counter__measure" aria-hidden="true">
                {DIGITS.map((n) => (
                    <span key={n}>{n}</span>
                ))}
            </span>
        </span>
    );
}

export default memo(Counter);
