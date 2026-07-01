import type { ReactNode } from 'react';
import type { RouteDef } from '../routes';
import { PageHeader } from './ui';

export function ScreenLayout({
    route,
    headerRight,
    hideHeader = false,
    children,
}: {
    route: RouteDef;
    headerRight?: ReactNode;
    hideHeader?: boolean;
    children: ReactNode;
}) {
    return (
        <div className="screen-layout">
            {!hideHeader && (
                <PageHeader title={route.title} subtitle={route.subtitle} right={headerRight} />
            )}
            {children}
        </div>
    );
}
