import type { CSSProperties, ReactNode } from 'react';
import { Icon, type IconName } from './Icon';
import { Reveal } from './motion/Reveal';
import { SkeletonBlock } from './motion/Skeleton';
import type { Tone } from '../routes';

export function DataPanel({
    title,
    eyebrow,
    badge,
    className = '',
    style,
    children,
}: {
    title?: string;
    eyebrow?: string;
    badge?: ReactNode;
    className?: string;
    style?: CSSProperties;
    children?: ReactNode;
}) {
    return (
        <section className={`data-panel t-resize ${className}`} style={style}>
            {(title || eyebrow || badge) && (
                <div className="panel-title-row">
                    <div>
                        {title && <h3>{title}</h3>}
                        {eyebrow && <p>{eyebrow}</p>}
                    </div>
                    {badge && <div className="panel-badge">{badge}</div>}
                </div>
            )}
            {children}
        </section>
    );
}

export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
    return <span className={`status-badge tone-${tone}`}>{children}</span>;
}

export function PageHeader({
    title,
    subtitle,
    right,
}: {
    title: string;
    subtitle: string;
    right?: ReactNode;
}) {
    return (
        <header className="page-header">
            <Reveal className="page-header-copy">
                <h1>{title}</h1>
                {subtitle ? <p>{subtitle}</p> : null}
            </Reveal>
            {right ? <div className="page-header-actions">{right}</div> : null}
        </header>
    );
}

export function MetricCard({
    icon,
    label,
    value,
    caption,
    tone = 'ink',
    children,
}: {
    icon?: IconName;
    label: string;
    value: ReactNode;
    caption?: ReactNode;
    tone?: Tone;
    children?: ReactNode;
}) {
    return (
        <article className={`metric-card tone-${tone}`}>
            <div className="metric-head">
                {icon && <Icon name={icon} />}
                <span>{label}</span>
            </div>
            <div className="metric-value">{value}</div>
            {caption && <div className="metric-caption">{caption}</div>}
            {children}
        </article>
    );
}

export function MetricBlock({
    icon,
    label,
    value,
    helper,
    tone,
    children,
}: {
    icon: IconName;
    label: string;
    value: ReactNode;
    helper: ReactNode;
    tone: Tone;
    children?: ReactNode;
}) {
    return (
        <div className={`metric-block tone-${tone}`}>
            <div className="metric-head">
                <Icon name={icon} />
                <span>{label}</span>
            </div>
            <strong>{value}</strong>
            <span>{helper}</span>
            {children}
        </div>
    );
}

export function KeyValueList({ rows }: { rows: Array<[ReactNode, ReactNode]> }) {
    return (
        <div className="kv-list">
            {rows.map(([key, value], index) => (
                <div key={`${String(key)}-${index}`}>
                    <span>{key}</span>
                    <strong>{value}</strong>
                </div>
            ))}
        </div>
    );
}

export function StatusLine({ icon, label, tone }: { icon: IconName; label: string; tone: Tone }) {
    return (
        <div className={`status-line tone-${tone}`}>
            <Icon name={icon} />
            <span>{label}</span>
        </div>
    );
}

export function MiniMetric({
    label,
    value,
    helper,
    tone = 'ink',
}: {
    label: string;
    value: string;
    helper: string;
    tone?: Tone;
}) {
    return (
        <div className={`mini-metric tone-${tone}`}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{helper}</small>
        </div>
    );
}

export function LegendItem({
    tone,
    label,
    hollow,
}: {
    tone: Tone;
    label: string;
    hollow?: boolean;
}) {
    return (
        <span className={`legend-item tone-${tone} ${hollow ? 'hollow' : ''}`}>
            <i />
            {label}
        </span>
    );
}

export function FilterLine({
    icon,
    label,
    value,
    active,
    onClick,
}: {
    icon: IconName;
    label: string;
    value: number;
    active?: boolean;
    onClick: () => void;
}) {
    return (
        <button
            className={`filter-line ${active ? 'active' : ''}`}
            type="button"
            onClick={onClick}
            aria-pressed={active}
        >
            <Icon name={icon} />
            <span>{label}</span>
            <strong>{value}</strong>
        </button>
    );
}

export function CheckLine({
    label,
    value,
    checked,
    onChange,
}: {
    label: string;
    value: number;
    checked: boolean;
    onChange: () => void;
}) {
    return (
        <label className={`check-line ${checked ? 'active' : ''}`}>
            <input type="checkbox" checked={checked} onChange={onChange} /> <span />{' '}
            <em>{label}</em>
            <strong>{value}</strong>
        </label>
    );
}

export function SplitCard({
    title,
    subtitle,
    active,
    badge,
    icon,
    onClick,
}: {
    title: string;
    subtitle: string;
    active?: boolean;
    badge?: string;
    icon?: IconName;
    onClick: () => void;
}) {
    return (
        <button
            className={`data-panel split-card ${active ? 'active' : ''}`}
            type="button"
            onClick={onClick}
            aria-pressed={active}
        >
            {icon && <Icon name={icon} />}
            <div>
                <strong>{title}</strong>
                <span>{subtitle}</span>
            </div>
            {badge && <StatusBadge tone="green">{badge}</StatusBadge>}
        </button>
    );
}

export function DataTable({
    title,
    columns,
    rows,
    badge,
    footer,
    footerHref = '#/audit',
}: {
    title: string;
    columns: string[];
    rows: Array<Array<ReactNode>>;
    badge?: ReactNode;
    footer?: string;
    footerHref?: string;
}) {
    return (
        <DataPanel className="table-panel" title={title} badge={badge}>
            <div className="table-scroll">
                {rows.length ? (
                    <table aria-label={title}>
                        <thead>
                            <tr>
                                {columns.map((column) => (
                                    <th key={column} scope="col">
                                        {column}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, rowIndex) => (
                                <tr
                                    key={rowIndex}
                                    style={{ '--delay': `${rowIndex * 45}ms` } as CSSProperties}
                                >
                                    {row.map((cell, cellIndex) => (
                                        <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                ) : (
                    <EmptyState
                        title="No persisted rows"
                        body="This table is empty because the backend did not return records."
                    />
                )}
            </div>
            {footer && (
                <a className="panel-link" href={footerHref}>
                    {footer} <Icon name="chevron" />
                </a>
            )}
        </DataPanel>
    );
}

export function LoadingState({ label }: { label: string }) {
    return (
        <div
            className="state-panel loading-state"
            role="status"
            aria-busy="true"
            aria-label={label}
        >
            <div className="t-skeleton-stack" style={{ width: '100%', maxWidth: 420 }}>
                <SkeletonBlock style={{ height: 14, width: '55%' }} />
                <SkeletonBlock style={{ height: 48, width: '100%' }} />
                <SkeletonBlock style={{ height: 120, width: '100%' }} />
            </div>
            <strong className="t-shimmer">{label}</strong>
        </div>
    );
}

export function WarningBanner({
    warnings,
    onDismiss,
}: {
    warnings: string[];
    onDismiss?: () => void;
}) {
    if (!warnings.length) return null;
    return (
        <div className="state-panel warning-banner" role="status" aria-live="polite">
            <Icon name="alert" />
            <div>
                <strong>Partial data load</strong>
                <p>{warnings.join(' · ')}</p>
                {onDismiss && (
                    <button className="outline-action" type="button" onClick={onDismiss}>
                        Dismiss Notice
                    </button>
                )}
            </div>
        </div>
    );
}

export function ErrorState({
    errors,
    onRetry,
}: {
    errors: string[];
    onRetry?: () => void;
}) {
    return (
        <div className="state-panel error-state" role="alert">
            <Icon name="alert" />
            <div>
                <strong>Some persisted data did not load</strong>
                <p>{errors.join(' · ')}</p>
                {onRetry && (
                    <button className="outline-action" type="button" onClick={onRetry}>
                        Retry Hydration
                    </button>
                )}
            </div>
        </div>
    );
}

export function EmptyState({
    title,
    body,
    action,
}: {
    title: string;
    body: string;
    action?: { label: string; href: string };
}) {
    return (
        <div className="state-panel empty-state">
            <Icon name="file" />
            <strong>{title}</strong>
            <p>{body}</p>
            {action && (
                <a className="outline-action" href={action.href}>
                    {action.label}
                </a>
            )}
        </div>
    );
}
