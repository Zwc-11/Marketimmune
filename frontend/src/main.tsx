import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/geist-sans/latin-400.css';
import '@fontsource/geist-sans/latin-500.css';
import '@fontsource/geist-sans/latin-600.css';
import '@fontsource/geist-sans/latin-700.css';
import '@fontsource/geist-mono/latin-400.css';
import '@fontsource/geist-mono/latin-500.css';
import '@fontsource/geist-mono/latin-600.css';
import { App } from './App';
import { DataProvider } from './data/provider';
import './styles.css';
import './styles/transitions.css';

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root');
createRoot(container).render(
    <StrictMode>
        <DataProvider>
            <App />
        </DataProvider>
    </StrictMode>,
);
