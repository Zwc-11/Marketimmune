import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
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
