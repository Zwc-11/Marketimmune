import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import net from 'node:net';
import { resolve } from 'node:path';

const API_HOST = '127.0.0.1';
const API_PORT = 8000;
const BACKEND_CHECK_MS = 12_000;

function probeBackend(host: string, port: number, timeoutMs = 350): Promise<boolean> {
    return new Promise((resolve) => {
        const socket = net.connect({ host, port });
        const finish = (up: boolean) => {
            socket.removeAllListeners();
            socket.destroy();
            resolve(up);
        };
        socket.setTimeout(timeoutMs);
        socket.once('connect', () => finish(true));
        socket.once('timeout', () => finish(false));
        socket.once('error', () => finish(false));
    });
}

/** Avoid ECONNREFUSED spam in the Vite terminal when Django is not running. */
function quietApiWhenOffline(): Plugin {
    let backendUp: boolean | null = null;
    let checkedAt = 0;

    return {
        name: 'quiet-api-when-offline',
        configureServer(server) {
            server.middlewares.use(async (req, res, next) => {
                const url = req.url ?? '';
                if (!url.startsWith('/api')) {
                    next();
                    return;
                }

                const now = Date.now();
                if (backendUp === null || now - checkedAt > BACKEND_CHECK_MS) {
                    backendUp = await probeBackend(API_HOST, API_PORT);
                    checkedAt = now;
                }

                if (backendUp) {
                    next();
                    return;
                }

                res.statusCode = 503;
                res.setHeader('Content-Type', 'application/json');
                res.end(
                    JSON.stringify({
                        error: 'Django API is not running on :8000. Using local fixtures.',
                        code: 'backend_offline',
                    }),
                );
            });
        },
    };
}

// Standalone static build — no Django, no backend.
//
//   Dev:   `npm run dev`     -> http://localhost:5173
//   Build: `npm run build`   -> ./dist (deployable to GitHub Pages / Vercel / Netlify)
//
// `base: './'` keeps asset URLs relative so the bundle works from any path
// (project pages, sub-directories, file://), and hash routing means there is
// no server-side rewrite to configure.
export default defineConfig({
    plugins: [react(), quietApiWhenOffline()],
    envDir: resolve(__dirname, '..'),
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: `http://${API_HOST}:${API_PORT}`,
                changeOrigin: true,
            },
        },
    },
    base: './',
    build: {
        outDir: resolve(__dirname, 'dist'),
        emptyOutDir: true,
        assetsDir: 'assets',
        // The Three.js vendor chunk is intentionally large and lazy-loaded only
        // when the 3D hero mounts, so it does not gate first paint.
        chunkSizeWarningLimit: 1000,
        rollupOptions: {
            output: {
                // Split the heavy 3D stack and React into long-cacheable vendor
                // chunks so the app shell + screen code stay small and the
                // Three.js payload is fetched in parallel / cached across visits.
                manualChunks: {
                    three: ['three', '@react-three/fiber', '@react-three/drei'],
                    react: ['react', 'react-dom'],
                },
            },
        },
    },
});
