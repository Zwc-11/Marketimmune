import { useEffect, useRef, useState } from 'react';

export function TextSwap({ text, className = '' }: { text: string; className?: string }) {
    const [display, setDisplay] = useState(text);
    const [phase, setPhase] = useState<'idle' | 'exit' | 'enter-start'>('idle');
    const ref = useRef<HTMLSpanElement>(null);

    useEffect(() => {
        if (text === display) return;
        setPhase('exit');
        const dur =
            parseFloat(
                getComputedStyle(document.documentElement).getPropertyValue('--text-swap-dur'),
            ) || 200;
        const timer = window.setTimeout(() => {
            setDisplay(text);
            setPhase('enter-start');
            requestAnimationFrame(() => {
                void ref.current?.offsetHeight;
                setPhase('idle');
            });
        }, dur);
        return () => window.clearTimeout(timer);
    }, [text, display]);

    const classNames = ['t-text-swap', className];
    if (phase === 'exit') classNames.push('is-exit');
    if (phase === 'enter-start') classNames.push('is-enter-start');

    return (
        <span ref={ref} className={classNames.filter(Boolean).join(' ')}>
            {display}
        </span>
    );
}
