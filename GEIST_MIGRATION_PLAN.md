# MarketImmune x Geist - Migration Plan

> Goal: adopt **Vercel's Geist design system** across the whole MarketImmune app, with a **light + dark theme toggle**, while keeping MarketImmune's **mint brand accent** (`#97fce4`) and green/red toxicity semantics.
>
> This is an adaptation, not a clone: Geist is a published, open system and Geist Sans/Mono are OFL fonts meant to be built on. We take the system - scales, type ladder, component tokens, motion discipline, content voice - and dress it in MarketImmune's brand. We do not copy vercel.com's chrome, copy, or logo.

Decisions locked with the user:

- **Theme:** both light + dark, with a toggle.
- **Scope:** the whole app: all screens, shell, and shared components.
- **Brand:** keep mint accent and green/red PnL semantics; adopt Geist's structure.

---

## 1. Why This Is Low-Risk Plumbing

The codebase already centralizes styling through CSS custom properties, especially `frontend/src/styles/tokens.css`. The migration should keep existing token names where possible and repoint values to Geist-inspired scales, minimizing component churn.

The real risk is not the token swap. The risk is visual QA:

1. **Dual-theme contrast:** every surface/text pair must hold readable contrast in both themes. Mint fails as body text on white, so it remains a fill/brand accent while light-theme text links use a darker `--accent-ink`.
2. **Per-screen sweep:** radius, padding, casing, and shadows need review across every screen.
3. **Density vs. whitespace:** Geist is airier than a trading terminal. Panels can breathe, but ticker strips, tables, order-book style blocks, and dense KPI rows must stay compact.

---

## 2. Token Mapping

Keep MarketImmune token names and define theme values under `[data-theme="light"]` and `[data-theme="dark"]`.

| MarketImmune token | Dark value | Light value | Notes |
|---|---:|---:|---|
| `--bg-0` | `#0a0a0a` | `#ffffff` | Near-black dark field avoids OLED smear. |
| `--bg-1` | `#111111` | `#fafafa` | Page/subtle field. |
| `--surface-raised` | `#1a1a1a` | `#f2f2f2` | Raised card/panel surface. |
| `--surface-muted` | `#1f1f1f` | `#fafafa` | Nested or secondary surface. |
| `--surface-border` | `#ffffff24` | `#00000014` | Translucent Geist-style border. |
| `--surface-border-strong` | `#ffffff3d` | `#00000036` | Hover/active border. |
| `--ink` | `#ededed` | `#171717` | Primary text. |
| `--ink-2` / `--muted` | `#a0a0a0` | `#4d4d4d` | Secondary text. |
| `--faint` | `#8f8f8f` | `#8f8f8f` | Disabled text. |
| `--accent` / `--signal` | `#97fce4` | `#97fce4` | MarketImmune mint fill/accent. |
| `--accent-ink` | `#97fce4` | `#0e9b86` | Link/brand text on light surfaces. |
| `--green` | `#3fd68b` | `#28a948` | Calm / PnL up. |
| `--red` | `#f6465d` | `#ea001d` | Toxic / PnL down. |
| `--amber` | `#f0b429` | `#a35200` | Warning / preview honesty. |

Radii move to Geist-like values:

- `--r-sm`: `6px`
- `--r-md`: `12px`
- `--r-lg`: `16px`
- `--r-full`: `9999px`

Spacing stays 4px-based but follows a clearer rhythm: 8px inside groups, 16px between groups, 32-40px between sections.

Elevation becomes subtle and theme-aware:

- Dark raised: `0 1px 2px rgba(0, 0, 0, 0.16)`
- Light raised: `0 2px 2px rgba(0, 0, 0, 0.04)`

---

## 3. Typography

- UI/prose: **Geist Sans**.
- Numerics/code: **Geist Mono**.
- CJK fallback: keep Noto Sans SC/JP.
- Delivery: self-host with `@fontsource/geist-sans` and `@fontsource/geist-mono` through Vite.
- Map existing `--t-*` variables onto Geist-style sizes so current markup continues to work.

---

## 4. Deliberate Trade-Offs

1. **Corners get softer:** adopt Geist radii.
2. **More whitespace:** cards and panels breathe; tables, ticker strip, and dense KPI rows remain compact.
3. **Calmer motion:** keep live-data number motion, remove decorative shimmer/bounce, retune to 150/200/300ms patterns.
4. **Casing:** Title Case for labels, buttons, titles, and tabs; sentence case for body.
5. **Mint stays a fill in light theme:** use darker `--accent-ink` for light-theme links/text.

---

## 5. Files To Touch

| File | Change |
|---|---|
| `frontend/package.json` | Add Geist Fontsource packages. |
| `frontend/index.html` | No-flash theme init script; dynamic `color-scheme`; keep Noto fallback. |
| `frontend/src/styles/tokens.css` | Core light/dark Geist-inspired token layer. |
| `frontend/src/styles/typography.css` | Geist type ladder and font wiring. |
| `frontend/src/components/shell.tsx` | Theme toggle in topbar, persisted and OS-aware. |
| `frontend/src/components/three/ImmuneCore.tsx` | Make Three.js colors theme-aware where practical. |
| `frontend/src/styles/*.css` | Radius, padding, shadow, focus, casing, and motion sweep. |
| `CLAUDE.md`, `DESIGN.md`, `AGENTS.md` | Update visual contract after implementation checkpoint. |

---

## 6. Phased Execution

- [x] **Phase 0 - Prep & fonts:** add Geist fonts, theme bootstrap, and toggle scaffolding.
- [x] **Phase 1 - Token foundation:** rewrite token values for light/dark Geist structure plus mint/green/red brand layer.
- [x] **Phase 2 - Typography:** wire Geist ladder and verify CJK/tabular numerics.
- [x] **Phase 3 - Shell + toggle:** restyle shell/topbar/ticker and verify Command Center in both themes.
- [ ] **Phase 4 - Components:** buttons, inputs, panels, badges, tables, focus rings, charts, and motion.
- [ ] **Phase 5 - Screen sweep:** all screens and per-screen CSS, plus `ImmuneCore` theme awareness.
- [ ] **Phase 6 - Content voice:** Title Case labels/actions; consistent error, empty, and progress patterns.
- [x] **Phase 7 - Docs:** update visual contract docs.
- [ ] **Phase 8 - Verify:** typecheck, build, screenshots in both themes, contrast spot-check, reduced-motion check.

---

## 7. Working Decisions

- Dark field: use near-black `#0a0a0a`, not pure `#000000`, unless the final visual pass says otherwise.
- First-load theme: follow OS preference, fallback to dark.
- Checkpoint: complete Phase 3 on Command Center before sweeping all screens.

---

## 8. Execution Log

- 2026-06-19: Plan saved from pasted brief.
- 2026-06-19: Installed `@fontsource/geist-sans` and `@fontsource/geist-mono`, imported latin weights in `frontend/src/main.tsx`, removed Google font loading from `frontend/index.html`, and kept the no-flash theme bootstrap.
- 2026-06-19: Removed the `App.tsx` hardcoded dark-theme override so the persisted light/dark toggle can work.
- 2026-06-19: Adjusted initial Geist token foundation: near-black dark field, softer radii, raised surfaces, `Geist Sans` font-family wiring, and no negative heading tracking.
- 2026-06-19: Verified `npm.cmd run typecheck`, `npm.cmd run build`, `npm.cmd run build:django`, and `http://127.0.0.1:8000/dashboard/live/?v=geist-phase0` returning `200`.
- 2026-06-19: Captured Command Center checkpoints in both themes: `screenshots/geist-command-dark.png` and `screenshots/geist-command-light.png`.
- 2026-06-19: Started the shared component sweep: removed old uppercase defaults from common labels/tables, flattened glass-style motion surfaces, and kept controls on tokenized Geist surfaces.
- 2026-06-19: Continued the screen sweep by removing forced uppercase/tracking from Live, Investigation, Memory, Models, Audit, and shared screen component labels.
- 2026-06-19: Updated visual contract docs (`AGENTS.md`, `DESIGN.md`, `CLAUDE.md`) so the repo points future work at the Geist-based pro terminal system instead of the old Montserrat/Outfit terminal notes.
