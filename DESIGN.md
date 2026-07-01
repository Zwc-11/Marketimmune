# MarketImmune — Design System

> Captured from `CLAUDE.md`, `frontend/src/styles/*`, and component patterns.
> Treat this as the visual contract; change `DESIGN.md` (and `CLAUDE.md`) before
> code when intentionally shifting look-and-feel.

## Identity

**Geist-based pro terminal** — Vercel's Geist design system
(`https://vercel.com/design.md`) adapted to MarketImmune: an instrument console
for adverse-selection monitoring on Hyperliquid BTC-PERP. Near-neutral surfaces,
10-step intent scales, hairline borders, opaque data surfaces, subtle tonal
elevation, and calm motion. MarketImmune keeps its **mint accent** (`#97fce4`)
as the primary/brand colour and **green/red** as PnL/toxicity semantics.

**Themes:** light **and** dark, switched by the `data-theme` attribute on
`<html>` (no-flash init in `index.html`, top-bar `ThemeToggle`, persisted to
`localStorage` as `mi-theme`).

**Scene:** Vercel-grade developer terminal — technical readout density,
traceable agent decisions, equally at home in light or dark. Not glass SaaS, not
a marketing landing page.

**Color strategy:** near-neutral field; mint for the single primary action and
brand; semantic green/amber/red for toxicity state; colour signals state, not
decoration.

See **CLAUDE.md** for the full visual contract (grid schemes A/B/C, type ladder,
checklist).

## Tokens

Source: `frontend/src/styles/tokens.css` (imported via `frontend/src/styles.css`).
Theme-agnostic tokens live in `:root`; colours are redefined per theme in
`:root`/`[data-theme="dark"]` and `[data-theme="light"]`.

### Surfaces + chrome

| Token | Role |
|---|---|
| `--bg-0` … `--bg-2` | Page field → recessed (dark `#000`→`#141414`, light `#fff`→`#f2f2f2`) |
| `--panel`, `--panel-2`, `--panel-3` | Opaque data-panel fills (raised / hover / nested) |
| `--chrome-bg`, `--chrome-border` | Sidebar / top bar |
| `--line`, `--line-2`, `--line-strong` | Hairline borders (default / hover / active), translucent |
| `--glass-bg`, `--glass-border` | Flat chrome fill (no blur — `--glass-blur: 0`) |
| `--shadow`, `--shadow-lg` | Subtle tonal elevation (Geist) |

### Ink + semantics

| Token | Role |
|---|---|
| `--ink`, `--ink-2`, `--muted`, `--faint` | Text ladder (Geist gray 1000 / · / 900 / 700) |
| `--accent`, `--signal` | Mint **fill** — primary action, brand stroke |
| `--accent-ink` | Mint **text/links** — bright on dark, darkened teal `#0f766e` on light (AA) |
| `--accent-contrast` | Label on a mint fill (near-black) |
| `--accent-border`, `--ring` | Active border / focus ring |
| `--green`, `--red` | Toxicity / PnL (calm → toxic); darkened on light for AA |
| `--amber` | Preview badge / warnings |
| `--cyan`, `--violet`, `--steel` | Secondary / metadata |

**Tone classes:** `tone-green`, `tone-amber`, `tone-red`, etc. Glow (`--glow`)
only on a single hero metric / brand mark, and only in dark (`none` in light).

### Spacing + shape

- Grid: 12-column (`.grid-12`, `.col-*`), 4px base / `--s1`…`--s24` rhythm
  (Geist: 4 8 12 16 24 32 40 64 96). Three-step rhythm: 8 in-group / 16 between
  groups / 32–40 between sections.
- Radii: `--r-sm` 6, `--r-md` 12, `--r-lg` 16, `--r-xl` 16, `--r-full` 9999.
- Shell: `--sidebar-w` 220px, collapsed 56px, `--topbar-h` 48px, `--ticker-h`
  36px, `--maxw` none (full-bleed).

### Type scale

| Token | Use |
|---|---|
| `--t-display` | Hero (clamp ~1.75–2.5rem) |
| `--t-h1` … `--t-h3` | Page / panel titles |
| `--t-body`, `--t-sm`, `--t-xs`, `--t-2xs` | Body + captions |

## Typography

Loaded through Fontsource imports in `frontend/src/main.tsx`.

| Role | Stack |
|---|---|
| Display / UI / body | Geist Sans (600 headings, 400–500 body) |
| Numerics / code | Geist Mono, `tabular-nums` |
| Chinese | Noto Sans SC (`.lang-zh`) |
| Japanese | Noto Sans JP (`.lang-jp`) |

Utilities: `.heading-xl|lg|md|sm`, `.copy-md|sm`, `.label-md`, `.label-mono`,
`.eyebrow`, `.mono`, `.num`. Headings use zero tracking. Cap prose
~65–75ch.

**Voice (Geist):** Title Case for labels/buttons/titles/tabs; sentence case for
body/helper/toasts. Actions are verb + noun (`Run Immune Loop`); in-progress
uses the ellipsis (`Running…`).

## Layout shell

`AppShell` (`frontend/src/components/shell.tsx`):

- Left **nav rail** with grouped nav (`NAV_GROUPS`)
- **Top bar** (menu toggle, live UTC clock, **theme toggle**, preview badge,
  alert badge)
- **Market ticker strip** (`MarketStrip`) under the top bar
- Full-bleed scrollable **main canvas** (`.app-main`)

No numbered nav, no breadcrumbs like `01 / 08`.

## Components

| Pattern | Class / component | Notes |
|---|---|---|
| Panel | `.data-panel`, `DataPanel` | Default surface, 6px radius; `.t-resize` for height |
| KPI | `MetricCard`, `MetricBlock`, `MiniMetric` | Live values → `AnimatedNumber` |
| Status | `StatusBadge`, `StatusLine` | Flat pill, tone-tinted |
| Buttons | `.primary-action` (mint fill), `.secondary-action`, `.outline-action` | One primary per view |
| Theme | `ThemeToggle` | Sun/moon in top bar; flips `data-theme` |
| Tables | `.data-table` | Hairline dividers, row hover, compact |
| Brand | `BrandMark` | Geometric shield, mint stroke |
| Empty / load | `EmptyState`, `LoadingState`, `SkeletonBlock` | |
| Charts | `frontend/src/components/charts.tsx` | Sparklines, bars, mini scales |
| Tabs | `SlidingTabs` | Agent detail |
| Reveal | `Reveal`, `.t-reveal` | Page headers |

## Motion

CSS: `frontend/src/styles/motion.css` + transitions.dev variables in tokens,
tuned to **Geist motion** (short, physical, no decoration). Base easing
`cubic-bezier(0.175, 0.885, 0.32, 1.1)` (`--ease`); ~150/200/300ms; blur and
bounce removed. Live-data motion is kept (signals real change).

React helpers in `frontend/src/components/motion/`: `AnimatedNumber`, `TextSwap`,
`Reveal`, `ShimmerText`, `SlidingTabs`, `SkeletonBlock`.

Global: respect `prefers-reduced-motion` (engine slows 1.5s → 4s). Route enter:
`.route-page` + `--route-dir`.

## Three.js

- `ImmuneCore` via `LazyImmuneCore` — wireframe icosahedron, orbiting agent nodes
- Pulses green→amber→red with `useLiveRisk()` toxicity; colours read from theme
  tokens via `useThemePalette()`, so the hero re-tints on light/dark toggle
- Guardrails: `dpr` cap 1.5, pause offscreen/hidden/reduced motion,
  `.three-fallback`
- **One hero per screen maximum** (Command Center today)

## Screen styles

Per-screen CSS under `frontend/src/styles/screens/`:

`command`, `live`, `agentic`, `risk`, `investigation`, `models`, `memory`,
`audit`, `shared`, `components`.

## Style import order

```text
tokens → base → typography → shell → primitives → charts → three
→ screens/* → motion → glass
```

Keep each partial under 1000 lines (`CLAUDE.md` §7).

## Accessibility + quality bar

- Body text ≥4.5:1 **in both themes**; bump `--muted` toward `--ink-2` if
  contrast fails. Mint is a fill — use `--accent-ink` for text/links on light.
- Placeholder text same 4.5:1 minimum.
- Icon buttons need `aria-label`; nav uses `aria-current="page"`.
- Preview badge explains simulated data (do not remove without real data path).
- Run `npm run typecheck` and `npm run build` before shipping UI changes.

## Anti-patterns (do not introduce)

- Hard-coded hex/rgba in components or CSS partials (use tokens so both themes follow)
- Mint as text on light surfaces (use `--accent-ink`)
- Mixing rounded and sharp corners, or more than two font weights, in one view
- Gradient text (`background-clip: text`)
- Glass blur on dense tables
- Numbered section scaffolding without real sequence
- Nested `.data-panel` inside `.data-panel`
- Arbitrary z-index (`9999`)

## Dev workflow

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run typecheck
npm run build    # → frontend/dist/
```

Django static copy (optional): build then copy `frontend/dist/*` →
`dashboard/static/agentic/`.
