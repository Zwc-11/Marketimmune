import { useEffect, useRef, useState } from 'react';

function formatDigits(value: string): Array<{ char: string; stagger?: string }> {
    const chars = value.split('');
    return chars.map((char, index) => {
        const stagger =
            index === chars.length - 2 ? '1' : index === chars.length - 1 ? '2' : undefined;
        return { char, stagger };
    });
}

export function AnimatedNumber({
    value,
    className = '',
    live = false,
}: {
    value: string | number;
    className?: string;
    /** Screen-reader announcements; off for engine-ticked metrics (default). */
    live?: boolean;
}) {
    const text = String(value);
    const [animating, setAnimating] = useState(true);
    const prev = useRef(text);

    useEffect(() => {
        if (prev.current === text) return;
        prev.current = text;
        setAnimating(false);
        const id = requestAnimationFrame(() => {
            void document.body.offsetHeight;
            setAnimating(true);
        });
        return () => cancelAnimationFrame(id);
    }, [text]);

    const digits = formatDigits(text);

    return (
        <span
            className={`t-digit-group mono num ${animating ? 'is-animating' : ''} ${className}`.trim()}
            {...(live ? { role: 'status', 'aria-live': 'polite' as const } : {})}
        >
            {digits.map((digit, index) => (
                <span
                    key={`${index}-${digit.char}`}
                    className="t-digit"
                    data-stagger={digit.stagger}
                >
                    {digit.char}
                </span>
            ))}
        </span>
    );
}
