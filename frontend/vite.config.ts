import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import net from 'node:net';
import { resolve } from 'node:path';

const API_HOST = '127.0.0.1';
const API_PORT = 8000;
const BACKEND_CHECK_MS = 12_000;

function probeBackend(host: string, port: number, timeoutMs = 350): Promise<boolean> {
    return new Promise((done) => {
        const socket = net.connect({ host, port });
        const finish = (up: boolean) => {
            socket.removeAllListeners();
            socket.destroy();
            done(up);
        };
        socket.setTimeout(timeoutMs);
        socket.once('connect', () => finish(true));
        socket.once('timeout', () => finish(false));
        socket.once('error', () => finish(false));
    });
}

/** Answer /api with a 503 instead of proxy errors when Django is not running. */
function quietApiWhenOffline(): Plugin {
    let backendUp: boolean | null = null;
    let checkedAt = 0;
    return {
        name: 'quiet-api-when-offline',
        configureServer(server) {
            server.middlewares.use(async (req, res, next) => {
                if (!(req.url ?? '').startsWith('/api')) return next();
                const now = Date.now();
                if (backendUp === null || now - checkedAt > BACKEND_CHECK_MS) {
                    backendUp = await probeBackend(API_HOST, API_PORT);
                    checkedAt = now;
                }
                if (backendUp) return next();
                res.statusCode = 503;
                res.setHeader('Content-Type', 'application/json');
                res.end(JSON.stringify({ error: 'Django API is not running on :8000.', code: 'backend_offline' }));
            });
        },
    };
}

// Static-first build: the terminal talks to Hyperliquid directly, so `dist/` works on
// any static host. Django is optional and only adds loop state and promoted-model health.
export default defineConfig({
    plugins: [react(), quietApiWhenOffline()],
    envDir: resolve(__dirname, '..'),
    server: {
        port: 5173,
        // The model page imports the committed benchmark report from ../eval.
        fs: { allow: [resolve(__dirname, '..')] },
        proxy: {
            '/api': { target: `http://${API_HOST}:${API_PORT}`, changeOrigin: true },
        },
    },
    base: './',
    build: {
        outDir: resolve(__dirname, 'dist'),
        emptyOutDir: true,
        assetsDir: 'assets',
        rollupOptions: {
            output: {
                manualChunks: {
                    react: ['react', 'react-dom'],
                    charts: ['lightweight-charts'],
                    motion: ['motion'],
                },
            },
        },
    },
    test: {
        include: ['src/**/*.test.ts'],
    },
});
