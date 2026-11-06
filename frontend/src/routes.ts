export type PageId = 'terminal' | 'paper' | 'model';

export interface PageDef {
    id: PageId;
    path: string;
    label: string;
    title: string;
}

export const PAGES: PageDef[] = [
    { id: 'terminal', path: '/terminal', label: 'Terminal', title: 'SOL-PERP terminal' },
    { id: 'paper', path: '/paper', label: 'Paper trading', title: 'Live paper trading' },
    { id: 'model', path: '/model', label: 'Model', title: 'Markout model report' },
];

/** Any hash that is not a page (or a sub-path of one) opens the terminal. */
export function pageForHash(hash: string): PageDef {
    const path = hash.replace(/^#/, '').replace(/\/+$/, '');
    return PAGES.find((page) => path === page.path || path.startsWith(`${page.path}/`)) ?? PAGES[0];
}
