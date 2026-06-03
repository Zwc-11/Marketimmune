import { lazy, Suspense } from 'react';
import type { ReactNode } from 'react';

// Code-split boundary for the signature 3D piece. The Three.js stack is a
// large vendor chunk, so we only fetch it when a screen actually mounts the
// hero — non-3D routes (Risk, Investigation, Audit, …) never pay for it.
// The fallback keeps the panel's footprint and the live overlay visible while
// the chunk streams in, so there is no layout shift.
const ImmuneCore = lazy(() =>
    import('./ImmuneCore').then((module) => ({ default: module.ImmuneCore })),
);

export function LazyImmuneCore({
    children,
    compact = false,
}: {
    children?: ReactNode;
    compact?: boolean;
}) {
    return (
        <Suspense
            fallback={
                <div className={`hero-three ${compact ? 'compact' : ''}`}>
                    <div className="three-fallback">Initializing immune core…</div>
                    {children}
                </div>
            }
        >
            <ImmuneCore compact={compact}>{children}</ImmuneCore>
        </Suspense>
    );
}
