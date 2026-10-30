import { lazy, Suspense, useEffect, useState } from 'react';
import { StatusBar } from './components/StatusBar';
import { TopNav } from './components/TopNav';
import { pageForHash, type PageDef } from './routes';

const TerminalPage = lazy(() => import('./pages/Terminal'));
const ModelPage = lazy(() => import('./pages/ModelReport'));

function useHashPage(): PageDef {
    const [page, setPage] = useState(() => pageForHash(window.location.hash));
    useEffect(() => {
        const onHash = () => {
            setPage(pageForHash(window.location.hash));
            window.scrollTo({ top: 0 });
        };
        if (!window.location.hash) window.location.replace('#/terminal');
        window.addEventListener('hashchange', onHash);
        return () => window.removeEventListener('hashchange', onHash);
    }, []);
    return page;
}

export function App() {
    const page = useHashPage();

    useEffect(() => {
        document.title = `${page.title} | MarketImmune`;
    }, [page.title]);

    return (
        <>
            <TopNav current={page.id} />
            <main id="main" className={`page page-${page.id}`}>
                <Suspense fallback={<div className="page-loading" aria-busy="true" />}>
                    {page.id === 'terminal' && <TerminalPage />}
                    {page.id === 'model' && <ModelPage />}
                </Suspense>
            </main>
            <StatusBar />
        </>
    );
}
