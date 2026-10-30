import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/ibm-plex-sans/latin-400.css';
import '@fontsource/ibm-plex-sans/latin-500.css';
import '@fontsource/ibm-plex-sans/latin-600.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/shell.css';
import './styles/panels.css';
import { App } from './App';
import { DjangoProvider } from './data/django';

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root');

createRoot(container).render(
    <StrictMode>
        <DjangoProvider>
            <App />
        </DjangoProvider>
    </StrictMode>,
);
