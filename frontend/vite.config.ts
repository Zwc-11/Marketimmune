import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

// Standalone static build — no Django, no backend.
//
//   Dev:   `npm run dev`     -> http://localhost:5173
//   Build: `npm run build`   -> ./dist (deployable to GitHub Pages / Vercel / Netlify)
//
// `base: './'` keeps asset URLs relative so the bundle works from any path
// (project pages, sub-directories, file://), and hash routing means there is
// no server-side rewrite to configure.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
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
