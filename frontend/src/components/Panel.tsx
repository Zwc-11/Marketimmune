import type { ReactNode } from 'react';

export function Panel({
    title,
    actions,
    className,
    children,
}: {
    title: ReactNode;
    actions?: ReactNode;
    className?: string;
    children: ReactNode;
}) {
    return (
        <section className={className ? `panel ${className}` : 'panel'}>
            <header className="panel-head">
                <h2 className="panel-title">{title}</h2>
                {actions && <div className="panel-actions">{actions}</div>}
            </header>
            <div className="panel-body">{children}</div>
        </section>
    );
}

/** Underlined text tabs, the venue convention for panel switching. */
export function Tabs<T extends string>({
    tabs,
    value,
    onChange,
    label,
}: {
    tabs: { id: T; label: string }[];
    value: T;
    onChange: (id: T) => void;
    label: string;
}) {
    return (
        <div className="tabs" role="tablist" aria-label={label}>
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    role="tab"
                    type="button"
                    className="tab"
                    aria-selected={tab.id === value}
                    onClick={() => onChange(tab.id)}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
    return (
        <div className="empty">
            <p className="empty-title">{title}</p>
            {children && <div className="empty-body">{children}</div>}
        </div>
    );
}

export function Stat({
    label,
    value,
    hint,
    tone,
}: {
    label: string;
    value: string;
    hint?: string;
    tone?: 'up' | 'down';
}) {
    return (
        <div className="stat" title={hint}>
            <span className={hint ? 'stat-label has-hint' : 'stat-label'}>{label}</span>
            <span className={`stat-value num ${tone ?? ''}`}>{value}</span>
        </div>
    );
}
