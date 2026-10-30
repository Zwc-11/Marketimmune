import { PAGES, type PageId } from '../routes';

const REPO_URL = 'https://github.com/Zwc-11/Marketimmune';

/** Two offset bars: a resting bid and the ask that lifted it. */
function Mark() {
    return (
        <svg className="brand-mark" viewBox="0 0 16 16" aria-hidden="true">
            <rect x="1" y="3" width="9" height="4" rx="1" fill="var(--bid)" />
            <rect x="6" y="9" width="9" height="4" rx="1" fill="var(--ask)" />
        </svg>
    );
}

export function TopNav({ current }: { current: PageId }) {
    return (
        <header className="topnav">
            <a className="brand" href="#/terminal" aria-label="MarketImmune terminal">
                <Mark />
                <span>MarketImmune</span>
            </a>
            <nav aria-label="Pages">
                {PAGES.map((page) => (
                    <a
                        key={page.id}
                        href={`#${page.path}`}
                        className="nav-link"
                        aria-current={page.id === current ? 'page' : undefined}
                    >
                        {page.label}
                    </a>
                ))}
            </nav>
            <a className="nav-source" href={REPO_URL} target="_blank" rel="noreferrer">
                Source
            </a>
        </header>
    );
}
