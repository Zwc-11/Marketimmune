// Copy the freshly built frontend (frontend/dist) into the folder Django serves
// the SPA from (dashboard/static/agentic), so http://localhost:8000/dashboard/
// shows the current UI instead of a stale snapshot. Cross-platform, no deps.
import { rmSync, cpSync, existsSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'frontend/dist');
const dest = resolve(root, 'dashboard/static/agentic');

if (!existsSync(dist)) {
    console.error('frontend/dist not found — run "npm run build" first.');
    process.exit(1);
}

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(dist, dest, { recursive: true });
console.log(`Synced ${dist} -> ${dest}`);
