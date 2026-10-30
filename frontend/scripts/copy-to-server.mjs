// Copy the built terminal (frontend/dist) to where Django serves it
// (server/api/static/terminal), so http://localhost:8000/ shows the current UI.
import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(frontend, 'dist');
const dest = resolve(frontend, '../server/api/static/terminal');

if (!existsSync(dist)) {
    console.error('frontend/dist not found: run "npm run build" first.');
    process.exit(1);
}
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(dist, dest, { recursive: true });
console.log(`Copied ${dist} -> ${dest}`);
