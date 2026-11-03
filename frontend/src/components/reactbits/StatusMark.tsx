// Vendored from React Bits StatusMark (https://reactbits.dev), (c) David Haz. MIT +
// Commons Clause; see ./NOTICE.md. Trimmed to the 12 px glyph MarketImmune uses (no
// label, strike-through or determinate progress). Upstream morphs the ring with motion
// values; here the dash pattern is a CSS transition and the spin a CSS animation, on a
// ring normalised to pathLength 100 (StatusMark.css).

import './StatusMark.css';

export type StatusMarkStatus = 'pending' | 'running' | 'done' | 'failed';

const SPOKEN: Record<StatusMarkStatus, string> = {
    pending: 'Pending',
    running: 'In progress',
    done: 'Completed',
    failed: 'Failed',
};

export default function StatusMark({ status }: { status: StatusMarkStatus }) {
    return (
        <svg className="status-mark" data-status={status} viewBox="0 0 24 24" width="12" height="12" role="img" aria-label={SPOKEN[status]}>
            <circle className="status-mark__track" cx="12" cy="12" r="9" />
            <circle className="status-mark__ring" cx="12" cy="12" r="9" pathLength="100" transform="rotate(-90 12 12)" />
            <path className="status-mark__check" d="M7.5 12.25 10.5 15.25 16.75 8.75" pathLength="1" />
            <path className="status-mark__cross" d="M8.5 8.5 15.5 15.5M15.5 8.5 8.5 15.5" pathLength="1" />
        </svg>
    );
}
