import { useEffect, useRef, useState } from 'react';

export function SlidingTabs<T extends string>({
    tabs,
    value,
    onChange,
    idPrefix = 'tab',
}: {
    tabs: Array<{ id: T; label: string }>;
    value: T;
    onChange: (id: T) => void;
    idPrefix?: string;
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
        <div className="t-tabs" ref={listRef} role="tablist" aria-label="Section tabs">
            <span
                className="t-tabs-indicator"
                style={{ left: indicator.left, width: indicator.width }}
                aria-hidden="true"
            />
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    id={`${idPrefix}-${tab.id}`}
                    data-tab-id={tab.id}
                    aria-selected={value === tab.id}
                    aria-controls={`${idPrefix}-${tab.id}-panel`}
                    tabIndex={value === tab.id ? 0 : -1}
                    onClick={() => onChange(tab.id)}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );
}
