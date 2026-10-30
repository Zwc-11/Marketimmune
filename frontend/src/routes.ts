export type PageId = 'terminal' | 'model';

export interface PageDef {
    id: PageId;
    path: string;
    label: string;
    title: string;
}

export const PAGES: PageDef[] = [
    { id: 'terminal', path: '/terminal', label: 'Terminal', title: 'SOL-PERP terminal' },
    { id: 'model', path: '/model', label: 'Model', title: 'Markout model report' },
];

// Hash routes from the previous dashboard keep working (bookmarks, Django links).
const LEGACY: Record<string, PageId> = {
    '/command': 'terminal',
    '/live': 'terminal',
    '/risk': 'terminal',
    '/models': 'model',
};

export function pageForHash(hash: string): PageDef {
    const path = hash.replace(/^#/, '').replace(/\/+$/, '') || '/terminal';
    const direct = PAGES.find((page) => path === page.path || path.startsWith(`${page.path}/`));
    if (direct) return direct;
    const legacy = Object.entries(LEGACY).find(([prefix]) => path.startsWith(prefix));
    return PAGES.find((page) => page.id === legacy?.[1]) ?? PAGES[0];
}
