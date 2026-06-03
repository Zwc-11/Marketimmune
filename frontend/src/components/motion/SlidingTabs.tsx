import { useEffect, useRef, useState } from 'react';

export function SlidingTabs<T extends string>({
    tabs,
    value,
    onChange,
}: {
    tabs: Array<{ id: T; label: string }>;
    value: T;
    onChange: (id: T) => void;
}) {
    const listRef = useRef<HTMLDivElement>(null);
    const [indicator, setIndicator] = useState({ left: 0, width: 0 });

    useEffect(() => {
        const root = listRef.current;
        if (!root) return;
        const active = root.querySelector<HTMLButtonElement>(`[data-tab-id="${value}"]`);
        if (!active) return;
        setIndicator({ left: active.offsetLeft, width: active.offsetWidth });
    }, [value, tabs]);

    return (
        <div className="t-tabs" ref={listRef} role="tablist">
            <span
                className="t-tabs-indicator"
                style={{ left: indicator.left, width: indicator.width }}
                aria-hidden
            />
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    data-tab-id={tab.id}
                    aria-selected={value === tab.id}
                    onClick={() => onChange(tab.id)}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );
}
