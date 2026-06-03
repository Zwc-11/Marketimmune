# MarketImmune — Visual System & Frontend Guide (CLAUDE.md)

This file is the **single source of truth for the look and feel** of the
MarketImmune web app. Every screen, component, and future change must conform
to it so the product stays visually consistent. If a change would violate
something here, update this document first, then the code.

> Design language: **Glassmorphism on a soft gradient mesh** (macOS Big Sur /
> modern SaaS register) — frosted panels with `backdrop-filter`, translucent
> borders, subtle depth shadows, and restrained accent color. Motion follows
> [transitions.dev](https://transitions.dev) primitives in `src/styles/transitions.css`.
> Navigation is grouped by function (Overview / Market / Operations /
> Intelligence), not numbered sections. Clean and production-ready over decorative.

---

## 0. Architecture (so visuals stay decoupled from data)

- **Pure static SPA.** React + TypeScript + Vite + Three.js. No Django, no
  server at runtime. `npm run build` → `frontend/dist/` (deploy to any static
  host). Routing is **hash-based** (`#/command`, `#/live`, …).
- **Data** comes from a bundled, typed layer, not the network:
  - `src/data/seed.ts` — fixtures for every persisted entity (loop, agents +
    tool traces, cases, decisions, 138 memories, promotion, metrics).
  - `src/data/simEngine.ts` — deterministic live stream (market events,
    predictions, alerts, features, orders, trades) ported from the old
    `dashboard/demo_data.py` math.
  - `src/data/provider.tsx` — `DataProvider` context + `useAppData()` /
    `useLiveRisk()` hooks. Exposes the same `ProductData` shape the screens
    already consumed, plus a simulated `runLoop()`.
- **Dynamic, not static:** the engine ticks every 1.5s (4s under reduced
  motion, paused when the tab is hidden) so charts, tickers, and the 3D hero
  feel live.

### Product vocabulary (v2)

The app's domain is **adverse selection (toxic order flow) on Hyperliquid
perpetual swaps**, not simulated CEX spoofing. Keep UI copy on this vocabulary:

- Venue/instrument: **Hyperliquid**, `BTC-PERP` (perp microstructure), not Binance / `BTCUSDT`.
- Detection target: **toxicity / adverse-selection score** measured by **markout** (realized 10s markout in bps), not generic "risk" or "spoofing".
- Signals: order-flow imbalance (OFI), microprice vs. mid, perp-oracle basis, funding rate-of-change, open-interest delta, liquidation intensity, queue-position proxy.
- Scenarios: **replays of real historical toxic episodes** (e.g. the Oct-2025 cascade, the JELLY playbook), not fabricated adversaries.
- Metrics are **honest and leakage-proof**: the headline is realized **markout lift (bps)** under a quoting policy; PR-AUC sits in an honest range (~0.76–0.84) under **purged/embargoed walk-forward** CV with isotonic calibration (Brier).
- Models: CatBoost markout classifiers (champion/challenger), with an OFI-only baseline for lift.

---

## 1. Color palette (glass on gradient)

Defined as CSS variables in `src/styles.css`. Never hard-code hex in
components — use the token.

| Token | Role |
|---|---|
| `--bg-0` … `--bg-2` | Page mesh base stops (cool blue / violet wash) |
| `--glass-bg`, `--glass-bg-strong` | Frosted panel fill (rgba white + alpha) |
| `--glass-border`, `--glass-highlight`, `--glass-inset` | Edge + inner highlight |
| `--glass-blur`, `--glass-saturate` | `backdrop-filter` strength |
| `--glass-shadow`, `--glass-shadow-sm` | Elevation (no neumorphic dual shadows) |
| `--ink` … `--faint` | Text hierarchy on light glass |
| `--green`, `--amber`, `--red`, `--cyan`, `--violet` | Semantic state + ML |
| `--accent` | Primary actions (blue, not copper) |

**Tone rule:** semantic state drives color. Toxicity/severity: `green` (calm) →
`amber` (elevated) → `red` (critical). Apply via `tone-{green|amber|red|…}`
classes. **Glow** only on the single hero metric per screen and the brand mark.

**Body background:** multi-stop radial mesh on `body` (blue / violet / mint).
Panels use glass, not opaque beige.

---

## 2. Typography

Fonts are loaded in `frontend/index.html`.

- **English display:** `Montserrat` (700/800 for hero & titles).
- **English UI/body:** `Outfit` (400 body, 300 captions, 500 labels).
- **Numerics/code:** `JetBrains Mono`, always `font-variant-numeric: tabular-nums`.
- **Chinese:** `Source Han Sans SC` → `Noto Sans SC` (`--font-zh`, `.lang-zh` / `:lang(zh)`).
- **Japanese:** `Kozuka Gothic Pr6N` → `Noto Sans JP` (`--font-jp`, `.lang-jp` / `:lang(ja)`).
  Kozuka is Adobe-licensed and not web-embeddable; it is used only if the
  visitor has it installed, otherwise Noto Sans JP. This is intentional and honest.

**Weight descends with hierarchy (bold → light):**

| Level | Font / weight |
|---|---|
| Hero / display | Montserrat 800 |
| Page title (`h1` in `.page-header`) | Montserrat 700 |
| Panel title (h3) | Montserrat/Outfit 600 |
| Body | Outfit 400 |
| Caption / secondary | Outfit 400, `--muted` |
| Nav group label | Outfit 600, sentence case, `--muted` |

Type scale tokens: `--t-display, --t-h1, --t-h2, --t-h3, --t-body, --t-sm,
--t-xs, --t-2xs`. Use the `.eyebrow`, `.mono`, `.num` helpers.

---

## 3. Grid system + layout shell

Built on a **12-column grid** (`.grid-12`, `.col-3/4/5/6/7/8/9/12`) and a
**4px base / 8px rhythm** spacing scale (`--s1…--s16`).

**Layout shell:** floating **glass sidebar** (grouped nav) + **glass top bar**
(menu icon swap, live clock, notification badge) + **main canvas** (scrollable
content). No numbered nav, no `01 / 08` breadcrumbs, no scanline background.

**Scheme A — Page header** (`.page-header`): `h1` + subtitle; optional actions
on the right. Wrap copy in `<Reveal>` for staggered text reveal.

**Scheme B — Data grid** (`.grid-12`, tables, KPIs): tabular numerics;
table headers sentence case.

---

## 4. Components & motifs

- **Panel** (`.data-panel`): glass surface + `backdrop-filter`, hairline border,
  `--glass-shadow`. Add `.t-resize` for smooth height changes.
- **MetricCard / MetricBlock / MiniMetric**: KPI tiles; live values use
  `<AnimatedNumber>`; status strings use `<TextSwap>`.
- **StatusBadge**: soft pill, tone-tinted background, sentence case.
- **Buttons:** `.primary-action` (accent gradient), `.secondary-action` (glass),
  `.outline-action` (ghost border). One primary per view.
- **Tables:** light dividers, row hover, staggered `rowIn` entry.
- **Brand mark:** geometric shield, accent stroke, soft glow allowed.

---

## 5. Motion ([transitions.dev](https://transitions.dev))

CSS primitives live in `src/styles/transitions.css` (imported from `main.tsx`).
React helpers in `src/components/motion/`:

| Primitive | CSS / component | Typical use |
|---|---|---|
| Card resize | `.t-resize` | Panels, route page wrapper |
| Number pop-in | `.t-digit-*`, `AnimatedNumber` | Live toxicity, KPIs |
| Notification badge | `.t-badge` | Top-bar alerts |
| Text swap | `.t-text-swap`, `TextSwap` | Status labels |
| Menu icon swap | `.t-icon-swap` | Sidebar toggle |
| Panel reveal | `.t-panel-slide` | Audit trace expand |
| Route enter | `.route-page`, `--route-dir` | Hash navigation |
| Text reveal | `.t-reveal`, `Reveal` | Page headers, tab panels |
| Sliding tabs | `SlidingTabs` | Agent detail |
| Shimmer | `ShimmerText` | Hero emphasis (Command Center) |
| Skeleton | `SkeletonBlock`, `LoadingState` | Initial load |

- Engine tick 1.5s drives live numbers; pair with `AnimatedNumber` / `TextSwap`.
- **Always** respect `prefers-reduced-motion` (global guard in `transitions.css`;
  engine slows to 4s).
- Easing: transitions.dev token curves; 120–600ms. Subtle, never bouncy.

---

## 6. Three.js (the "WOW", used with restraint)

- Stack: `three` + `@react-three/fiber` + `@react-three/drei`.
- **Signature piece:** `src/components/three/ImmuneCore.tsx` — wireframe icosahedron
  with orbiting agent nodes; pulses with **live toxicity** from `useLiveRisk()`.
  Colors tuned for the light glass theme.
- **Guardrails:** cap `dpr` at 1.5; pause when offscreen/hidden or reduced motion;
  `.three-fallback` static CSS. One hero per screen, maximum.

---

## 7. Consistency checklist (run before calling any UI change done)

- [ ] Colors come from glass tokens; semantic tone matches state.
- [ ] Type uses Montserrat/Outfit/Mono; numerics tabular.
- [ ] CJK strings carry `.lang-zh` / `.lang-jp` (or `lang` attr).
- [ ] Layout uses `.grid-12` + spacing scale.
- [ ] Each screen uses `.page-header` when it needs a toolbar.
- [ ] Panels are glass (`.data-panel`); one `.primary-action` per view.
- [ ] Live metrics use motion helpers where values change on engine tick.
- [ ] Sidebar uses grouped nav (`NAV_GROUPS`), not numbered lists.
- [ ] All relevant fixture fields are surfaced.
- [ ] Motion respects `prefers-reduced-motion`; Three.js has fallback + pause.
- [ ] `npm run typecheck` and `npm run build` pass.

---

## 8. Commands

```bash
cd frontend
npm install      # one-time
npm run dev      # http://localhost:5173
npm run typecheck
npm run build    # -> frontend/dist (static, deployable anywhere)
npm run preview
```

Deploy `frontend/dist/` to GitHub Pages, Vercel, or Netlify. No environment
variables, no backend.
