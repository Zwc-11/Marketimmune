import type { CSSProperties, ReactNode } from 'react';

export function SkeletonBlock({
    className = '',
    style,
}: {
    className?: string;
    style?: CSSProperties;
}) {
    return <div className={`t-skeleton ${className}`.trim()} style={style} aria-hidden />;
}

export function SkeletonReveal({
    loading,
    skeleton,
    children,
}: {
    loading: boolean;
    skeleton: ReactNode;
    children: ReactNode;
}) {
    if (loading) return <div className="t-skeleton-stack">{skeleton}</div>;
    return <div className="t-skeleton-reveal">{children}</div>;
}
