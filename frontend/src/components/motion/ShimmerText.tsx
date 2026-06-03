export function ShimmerText({
    children,
    className = '',
}: {
    children: string;
    className?: string;
}) {
    return <span className={`t-shimmer ${className}`.trim()}>{children}</span>;
}
