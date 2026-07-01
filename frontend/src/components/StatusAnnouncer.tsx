export function StatusAnnouncer({
    message,
    className = 'status-announcer',
}: {
    message: string;
    className?: string;
}) {
    if (!message) return null;
    return (
        <div className={className} role="status" aria-live="polite">
            {message}
        </div>
    );
}
