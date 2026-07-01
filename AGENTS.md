# MarketImmune — Visual System & Frontend Guide (AGENTS.md)

This file is the **single source of truth for the look and feel** of the
MarketImmune web app. Every screen, component, and future change must conform
to it so the product stays visually consistent. If a change would violate
something here, update this document first, then the code.

> **Design language:** **Geist-based pro terminal** - Vercel's Geist system
> adapted to MarketImmune: full-bleed chrome, dense data tables, Geist Sans/Mono,
> mint accent (`#97fce4`), green/red PnL semantics, light + dark themes, and
> token-driven surfaces. Flat panels with hairline borders, 6/12/16px radii,
> subtle tonal elevation, no glass blur.
> Motion follows [transitions.dev](https://transitions.dev) primitives in
> `src/styles/transitions.css`. Navigation is grouped by function (Overview /
> Market / Operations / Intelligence), not numbered sections.

**Reference mood:** Vercel-grade developer terminal for on-chain perp monitoring
- instrument ticker strip, monospace numerics, compact rows, high information
density, equally at home in light or dark. Not a marketing landing page.

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

## 1. Color & surface (International / geometric)

Defined in `src/styles/tokens.css`. Never hard-code hex in components.

| Token | Role |
|---|---|
| `--bg-0` … `--bg-2` | Cool neutral field stops (light gray, not warm cream) |
| `--grid-line`, `--grid-line-strong` | Visible blueprint grid on field + panels |
| `--surface`, `--surface-raised`, `--surface-muted` | Opaque data panels (primary reading surfaces) |
| `--surface-border`, `--surface-border-strong` | 1px hairline edges |
| `--chrome-bg`, `--chrome-border` | Sidebar / top bar matte chrome |
| `--ink` … `--faint` | Text hierarchy (body ≥4.5:1 on `--surface`) |
| `--signal` | Mint brand accent — primary action fill, hero focal, brand stroke |
| `--signal-soft` | Tinted mint wash for brand emphasis only |
| `--green`, `--amber`, `--red` | Semantic toxicity (calm → elevated → critical) |
| `--accent` | Alias of `--signal`; use `--accent-ink` for text on light surfaces |
| `--steel`, `--cyan`, `--violet` | Secondary ML / metadata only |

**Color strategy:** restrained monochrome + **mint accent used sparingly**.
Semantic green/amber/red stay for toxicity state; do not sprinkle accent color
on decorative chrome.

**Avoid:** gradient meshes as default background, frosted glass on data panels,
soft pill SaaS shadows, blue primary buttons.

**Body field:** flat neutral wash + subtle orthogonal grid (`body::before`).
Panels use opaque `--surface-raised`, 1px border, minimal shadow.

---

## 2. Typography

Fonts are self-hosted through Fontsource imports in `frontend/src/main.tsx`.
**Weight descends with hierarchy:**
larger type = heavier weight; smaller type = lighter weight.

| Role | Stack | Weight |
|---|---|---|
| Display / hero metric | Geist Sans | 600–700 |
| Page title (`.page-header h1`) | Geist Sans | 600 |
| Panel title (`h3`, section heads) | Geist Sans | 600 |
| Body / UI default | Geist Sans | 400–500 |
| Labels / captions | Geist Sans | 400, `--ink-2` or `--muted` |
| Micro metadata / trace labels | Geist Sans | 400–500, `--t-2xs`, no forced uppercase |
| Numerics / code / timestamps | Geist Mono | 500–600, `tabular-nums` |
| Chinese (`.lang-zh`, `:lang(zh)`) | Source Han Sans SC → Noto Sans SC | Same weight ladder |
| Japanese (`.lang-jp`, `:lang(ja)`) | Kozuka Gothic Pr6N → Noto Sans JP | Same weight ladder |

Kozuka is Adobe-licensed and not web-embeddable; use it only when installed,
otherwise Noto Sans JP. This is intentional.

Type scale: `--t-display`, `--t-h1` … `--t-2xs`. Helpers: `.eyebrow`,
`.mono`, `.num`, `.trace-label`.

**Rules:** Title Case for labels, buttons, titles, and tabs; sentence case for
body/helper text (no ALL CAPS body). `text-wrap: balance` on
h1–h3; `text-wrap: pretty` on prose. Cap body line length ~65–75ch.

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

**Layout shell:** matte **sidebar** + **top bar** (grouped nav) + **main canvas**
(`.app-main` on `--surface`). No numbered nav, no `01 / 08` breadcrumbs.

**Page header** (`.page-header`): `h1` + subtitle; optional actions right.
Wrap copy in `<Reveal>` where motion is appropriate.

---

## 4. Components & motifs

- **Panel** (`.data-panel`): opaque surface, 1px border, light shadow only.
  Optional `.t-resize` for height transitions. No nested panels.
- **MetricCard / MetricBlock / MiniMetric:** KPI tiles on `--surface-raised`;
  live values → `<AnimatedNumber>`; linked tiles use `.metric-card-link`.
- **StatusBadge:** flat pill, tone wash, sentence case (not uppercase eyebrows).
- **Buttons:** `.primary-action` (ink fill or signal for single primary),
  `.secondary-action` (outline hairline), `.outline-action` (ghost). **One
  primary per view.**
- **Tables:** hairline dividers, row hover, header `scope="col"`, empty state
  outside `<table>`.
- **Brand mark:** geometric shield, **signal red** stroke, no glow except hero.
- **Leader lines / dashed rules:** 1px dashed `--grid-line-strong` for instrument
  separators; never thick side-stripe accents on cards.

---

## 5. Motion ([transitions.dev](https://transitions.dev))

CSS primitives in `src/styles/transitions.css`; React helpers in
`src/components/motion/`.

| Primitive | Typical use |
|---|---|
| Card resize | `.t-resize` — panels, route wrapper |
| Number pop-in | `AnimatedNumber` — live toxicity, KPIs |
| Text swap | `TextSwap` — status labels |
| Route enter | `.route-page` — hash navigation |
| Panel reveal | `.t-panel-slide` — audit trace expand |
| Shimmer | opacity pulse only — **no gradient text** |

Engine tick 1.5s drives live numbers. Always respect `prefers-reduced-motion`.

---

## 6. Three.js (instrument hero, used with restraint)

- Stack: `three` + `@react-three/fiber` + `@react-three/drei`.
- **Signature:** `ImmuneCore.tsx` — wireframe geometry, monochrome with signal
  red pulse on critical toxicity from `useLiveRisk()`.
- **Guardrails:** cap `dpr` at 1.5; pause when hidden / reduced motion; one hero
  per screen maximum; align overlay readout to Scheme C center.

---

## 7. Consistency checklist

- [ ] Colors from tokens; signal red used sparingly; toxicity uses semantic tones.
- [ ] Type ladder: heavier weights only on larger sizes; CJK stacks on `.lang-*`.
- [ ] Screen uses Scheme A (macro) **and** Scheme B (micro) alignment.
- [ ] Decorative / hero elements align to Scheme C when present.
- [ ] Panels opaque; chrome matte; no glass on dense tables.
- [ ] One `.primary-action` per view; button labels verb + object.
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
