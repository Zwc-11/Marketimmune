# MarketImmune — Visual System & Frontend Guide (CLAUDE.md)

This file is the **single source of truth for the look and feel** of the
MarketImmune web app. Every screen, component, and future change must conform
to it so the product stays visually consistent. If a change would violate
something here, update this document first, then the code.

> **Design language:** **Geist-based pro terminal** — Vercel's Geist system
> (`https://vercel.com/design.md`) adapted to MarketImmune. Near-neutral
> surfaces, 10-step intent scales, Geist Sans/Mono, tight radii (6/12/16px),
> subtle tonal elevation, calm motion. **Light + dark**, switched via the
> `data-theme` attribute on `<html>` (toggle in the top bar). MarketImmune keeps
> its **mint accent** (`#97fce4`) as the primary/brand colour and **green/red**
> as PnL/toxicity semantics. Full-bleed chrome, dense data tables, hairline
> borders, no glass blur. Navigation is grouped by function (Overview / Market /
> Operations / Intelligence), not numbered sections.

**Reference mood:** Vercel-grade developer terminal — instrument ticker strip,
monospace numerics, compact rows, high information density, equally at home in
light or dark. Not a marketing landing page.

---

## 0. Architecture (so visuals stay decoupled from data)

- **Static-first hybrid SPA.** React + TypeScript + Vite + Three.js. The app
  boots with **no backend** from a bundled, typed data layer and `npm run build`
  → `frontend/dist/` (deployable to any static host). When a Django API is
  reachable it **hydrates** the persisted slices from live data; offline is a
  fully supported mode, not a degraded one. Routing is **hash-based**
  (`#/command`, `#/live`, …).
- **Data** comes from a bundled, typed layer first, the network second:
  - `src/data/seed.ts` — fixtures for every persisted entity (loop, agents +
    tool traces, cases, decisions, memories, promotion, metrics).
  - `src/data/simEngine.ts` — deterministic, seeded live stream (market events,
    predictions, alerts, features, orders, trades + live toxicity) ported from
    the old `dashboard/demo_data.py` math, rebased onto BTC-PERP / markout.
  - `src/data/provider.tsx` — `DataProvider` context + `useAppData()` /
    `useLiveRisk()` hooks. Exposes the `ProductData` shape the screens consume
    plus `runLoop()` / `refresh()` / `setScenario()`. **Hybrid:** the simulator
    slice + live risk always come from the local engine; loop state, LLM status,
    and metrics hydrate from Django (`src/api.ts`) when `/api` answers, else stay
    on fixtures.
- **Dynamic, not static:** the engine ticks every 1.5s (4s under reduced
  motion, paused when the tab is hidden) so charts, tickers, and the 3D hero
  feel live.
- **Build/serve pipeline.** `vite build` emits to `frontend/dist/`. Django
  optionally serves a copy from `dashboard/static/agentic/` (`AgenticReactView`);
  if you want Django to serve the latest UI, copy `frontend/dist/*` →
  `dashboard/static/agentic/` after building (the bundle there is otherwise a
  stale snapshot). Pure static hosts deploy `frontend/dist/` directly.

**Dev note:** Vite proxies `/api` → `:8000`. Proxy `ECONNREFUSED` logs are
normal when Django is not running; fixtures keep the UI fully usable.

### Product vocabulary (v2)

The app's domain is **adverse selection (toxic order flow) on Hyperliquid
perpetual swaps**, not simulated CEX spoofing. Keep UI copy on this vocabulary:

- Venue/instrument: **Hyperliquid**, `BTC-PERP` (perp microstructure), not Binance / `BTCUSDT`.
- Detection target: **toxicity / adverse-selection score** measured by **markout** (realized 10s markout in bps), not generic "risk" or "spoofing".
- Signals: order-flow imbalance (OFI), microprice vs. mid, perp-oracle basis, funding rate-of-change, open-interest delta, liquidation intensity, queue-position proxy.
- Scenarios: **replays of real historical toxic episodes** (e.g. the Oct-2025 cascade, the JELLY playbook), not fabricated adversaries.
- Metrics are **honest and leakage-proof**: the headline is realized **markout lift (bps)** under a quoting policy; PR-AUC sits in an honest range (~0.76–0.84) under **purged/embargoed walk-forward** CV with isotonic calibration (Brier).
- Models: CatBoost markout classifiers (champion/challenger), with an OFI-only baseline for lift.
- Persistent **"Preview · simulated data"** badge until real Hyperliquid backfill is wired end-to-end.

---

## 1. Color & surface (Geist, light + dark)

Defined in `src/styles/tokens.css`: theme-agnostic tokens in `:root`, plus
per-theme colour blocks (`:root`/`[data-theme="dark"]` and
`[data-theme="light"]`). The no-flash init script in `index.html` sets
`data-theme` before paint; the top-bar `ThemeToggle` flips it and persists to
`localStorage` (`mi-theme`). **Never hard-code hex in components** — every colour
reads a token so both themes follow automatically.

| Token | Role (Geist intent) |
|---|---|
| `--bg-0` … `--bg-2` | Page field → recessed (dark `#000`→`#141414`, light `#fff`→`#f2f2f2`) |
| `--panel`, `--panel-2`, `--panel-3` | Flat data-panel fills (raised / hover / nested) |
| `--line`, `--line-2`, `--line-strong` | Hairline borders (default / hover / active), translucent |
| `--chrome-bg`, `--chrome-border` | Sidebar / top bar |
| `--ink`, `--ink-2`, `--muted`, `--faint` | Text ladder (Geist gray 1000 / · / 900 / 700) |
| `--accent`, `--signal` | Mint **fill** — primary actions, brand stroke |
| `--accent-ink` | Mint **text/links** — bright mint on dark, darkened teal (`#0f766e`) on light (AA) |
| `--accent-contrast` | Label on a mint fill (near-black, both themes) |
| `--accent-border`, `--ring` | Active-card border / focus ring |
| `--green`, `--red` | Calm/long vs toxic/short (PnL semantics; darkened on light for AA) |
| `--amber` | Preview badge, elevated warnings |
| `--steel`, `--cyan`, `--violet` | Secondary metadata |

**Color strategy:** near-neutral field; **mint** for the single primary action
and brand; **green/red** reserved for toxicity and markout direction; colour
signals state, not decoration. Mint is a *fill* — for text/links (esp. on light)
use `--accent-ink`. No gradient meshes, no frosted glass. Elevation is tonal
first (`--shadow`, `--shadow-lg` stay subtle, per Geist).

**Layout chrome:** full-bleed shell (no floating card canvas), market ticker
strip under top bar (`MarketStrip` in `shell.tsx`), left nav rail.

---

## 2. Typography

Fonts are self-hosted through Fontsource imports in `frontend/src/main.tsx`.

| Role | Stack | Weight |
|---|---|---|
| UI / headings | Geist Sans | 600 |
| Body | Geist Sans | 400–500 |
| Labels / captions | Geist Sans | 400, `--muted` |
| Micro metadata | Geist Sans | 400-500, `--t-2xs` |
| Numerics / code / timestamps | Geist Mono | 500–600, `tabular-nums` |
| Chinese (`.lang-zh`) | Noto Sans SC | Same ladder |
| Japanese (`.lang-jp`) | Noto Sans JP | Same ladder |

Type scale: `--t-display`, `--t-h1` … `--t-2xs`, mapped onto the Geist ladder
(heading / label / copy / button). Utilities: `.heading-xl|lg|md|sm`,
`.copy-md|sm`, `.label-md`, `.label-mono`, `.eyebrow`, `.mono`, `.num`,
`.trace-label`. Headings use zero tracking so compact panels and buttons do not
drift on mobile.

**Rules (Geist voice):** **Title Case** for labels, buttons, titles and tabs;
**sentence case** for body, helper text and toasts. Name actions verb + noun
(`Run Immune Loop`), never a bare `Confirm`/`OK`; in-progress uses the ellipsis
(`Running…`). `text-wrap: balance` on h1–h3; `pretty` on prose; body ~65–75ch.

---

## 3. Grid & alignment (two schemes + instrument tier)

**Base rhythm:** 4px unit, spacing `--s1`…`--s16`, **12-column macro grid**
(`.grid-12`, `.col-*`).

Every screen must use **at least two alignment schemes** so information and
decoration sit on intentional axes:

### Scheme A — Macro grid (page composition)

- **What:** shell columns, `.grid-12`, page headers, panel placement.
- **Axes:** 12 equal columns + outer margin `--grid-margin` (matches shell padding).
- **Use for:** Command Center hero column, side stacks, model benchmark splits.
- **Classes:** `.grid-12`, `.col-*`, `.align-macro` (full-width snap to macro gutters).

### Scheme B — Micro baseline (data density)

- **What:** KPI rows, `.kv-list`, tables, metric captions, form labels.
- **Axes:** shared left label margin `--grid-micro-offset`; numerics right-aligned
  on `.num-cell` / `.metric-value` / table amount columns.
- **Use for:** telemetry blocks, audit meta, investigation evidence tables.
- **Classes:** `.align-micro`, `.kv-list`, `.num-cell`.

### Scheme C — Instrument / decorative (hero & traces)

- **What:** Three.js hero, orbital motifs, trace leader lines, footer status strips.
- **Axes:** radial center of hero viewport; bottom **status baseline**
  `--grid-instrument-baseline` for decorative ticks and legends.
- **Use for:** ImmuneCore overlay readout, agent orchestrator rings, audit footer.
- **Rule:** decoration aligns to C; **data** still reads on A/B. Never float
  labels without a grid line or leader.

**Layout shell:** fixed **left nav rail** + **top bar** + **market ticker strip**
(`MarketStrip`) + full-bleed **main canvas** (`.app-main` on `--bg-0`). No floating
card wrapper, no numbered nav.

**Page header** (`.page-header`): `h1` + subtitle; optional actions right.
Wrap copy in `<Reveal>` where motion is appropriate.

---

## 4. Components & motifs

- **Panel** (`.data-panel`): flat `--panel`, 1px `--line` border, **6px radius**
  (`--r-sm`); 24px padding (16 compact, 32 hero). Menus/modals 12px (`--r-lg`),
  fullscreen 16px (`--r-xl`). One radius family per view.
- **MetricCard / MetricBlock / MiniMetric:** compact KPI tiles; numerics in mono;
  live values → `<AnimatedNumber>`.
- **StatusBadge:** flat pill, tone wash, mono labels for terminal readout.
- **Buttons:** `.primary-action` (mint fill, `--accent-contrast` label),
  `.secondary-action` (surface + hairline), `.outline-action` (ghost). **One
  primary per view.** Focus shows the `--ring` outline.
- **Theme toggle:** sun/moon `icon-button` in the top bar (`ThemeToggle`),
  persists to `localStorage`.
- **Tables:** uppercase headers, mono body cells, compact row height — density
  survives (tables/ticker stay tight while cards breathe).
- **Brand mark:** geometric shield, mint stroke.

---

## 5. Motion ([transitions.dev](https://transitions.dev))

CSS primitives in `src/styles/transitions.css`; React helpers in
`src/components/motion/`. Tuned to **Geist motion** — short, physical, never
decorative. Base easing `cubic-bezier(0.175, 0.885, 0.32, 1.1)` (token `--ease`);
~150ms state changes, 200ms popovers, 300ms overlays; motion blur and bounce
removed. Live-data motion (`AnimatedNumber`) is kept because it signals real
change, not decoration.

| Primitive | Typical use |
|---|---|
| Card resize | `.t-resize` — panels, route wrapper |
| Number pop-in | `AnimatedNumber` — live toxicity, KPIs (functional — kept) |
| Text swap | `TextSwap` — status labels |
| Route enter | `.route-page` — hash navigation |
| Panel reveal | `.t-panel-slide` — audit trace expand |
| Shimmer | opacity pulse only — **no gradient text** |

Engine tick 1.5s drives live numbers. Always respect `prefers-reduced-motion`.

---

## 6. Three.js (instrument hero, used with restraint)

- Stack: `three` + `@react-three/fiber` + `@react-three/drei`.
- **Signature:** `ImmuneCore.tsx` — wireframe geometry that pulses green→amber→red
  with `useLiveRisk()` toxicity. Colours read live from theme tokens
  (`--green`/`--amber`/`--red`/`--accent-ink`) via `useThemePalette()`, so the
  hero re-tints on the light/dark toggle.
- **Guardrails:** cap `dpr` at 1.5; pause when hidden / reduced motion; one hero
  per screen maximum; align overlay readout to Scheme C center.

---

## 7. Consistency checklist

- [ ] Colours from tokens (both themes follow); mint used sparingly; toxicity uses semantic tones.
- [ ] **Light and dark both pass** — surfaces, text and mint hold WCAG AA (4.5:1 body).
- [ ] Type ladder: heavier weights only on larger sizes; CJK stacks on `.lang-*`.
- [ ] Screen uses Scheme A (macro) **and** Scheme B (micro) alignment.
- [ ] Decorative / hero elements align to Scheme C when present.
- [ ] Radii 6/12/16, one family per view; panels opaque; chrome matte; no glass.
- [ ] One `.primary-action` per view; **Title Case** labels, verb + noun.
- [ ] Live metrics use motion helpers; reduced motion respected.
- [ ] Preview honesty badge visible while data is simulated.
- [ ] `npm run typecheck` and `npm run build` pass from repo root.

---

## 8. Commands

From repo root (delegates to `frontend/`):

```bash
npm run setup:frontend   # one-time
npm run dev:frontend     # http://localhost:5173
npm run typecheck
npm run build            # -> frontend/dist
```

Backend (separate terminal):

```bash
python manage.py runserver   # http://127.0.0.1:8000 — enables API hydration
```

Deploy `frontend/dist/` to any static host. Copy to `dashboard/static/agentic/`
when serving via Django.
