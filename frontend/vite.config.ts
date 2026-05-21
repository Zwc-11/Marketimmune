import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// Build the React bundle straight into Django's static-file tree so a
// single `python manage.py runserver` serves the whole stack — no
// node sidecar process required for production.
//
//   Dev:   `npm run dev`     -> http://localhost:5173 (proxies /api -> :8000)
//   Build: `npm run build`   -> ../dashboard/static/agentic/{index.html,assets/}
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            '/api': 'http://127.0.0.1:8000',
        },
    },
    base: '/static/agentic/',
    build: {
        outDir: resolve(__dirname, '../dashboard/static/agentic'),
        emptyOutDir: true,
        assetsDir: 'assets',
    },
});
