# MarketImmune — Product Context

> Impeccable context file. Keep this aligned with `README.md`, `AUDIT_AND_PLAN.md`, and
> the hybrid data layer in `frontend/src/data/`.

## Register

**product** — design serves a research dashboard and agentic operations tool, not a
marketing site.

## Scene sentence

A quant researcher or ML engineer monitors adverse-selection risk on Hyperliquid BTC-PERP
from a desk in normal office lighting: they need dense, honest telemetry, fast scan of
toxicity state, and traceable agent decisions without mistaking preview data for live
production metrics.

## What it is

MarketImmune is an AI market-safety research platform. A multi-agent **immune loop**
(Generate → Detect → Investigate → Decide → Remember) runs over trading scenarios,
scores toxic order flow, writes investigation narratives, decides control actions, and
persists every step to an append-only audit log. The React dashboard visualizes loop
state, live microstructure preview, model benchmarks, memory, and audit traces.

**Honest status:** research prototype, not a live trading system. The SPA boots from
bundled fixtures and a deterministic simulator; Django hydrates persisted slices when
reachable. A persistent **"Preview · simulated data"** badge must remain until real
Hyperliquid backfill and trained markout models are wired end-to-end.

## Audience

| Persona | Job to be done |
|---|---|
| Research engineer | Inspect loop traces, model metrics, promotion evidence |
| Interviewer / reviewer | Verify claims match code; see auditability and ML discipline |
| Operator (future) | Watch live toxicity, trigger loop runs, read case files |

## Surfaces (hash routes)

| Route | Screen | Primary intent |
|---|---|---|
| `#/command` | Command Center | Loop posture, hero toxicity, run loop, 3D ImmuneCore |
| `#/live` | Live Simulation Cockpit | Scenario replay, charts, live toxicity stream |
| `#/agentic` | Immune Loop | Agent orchestration, tool traces, stage progress |
| `#/risk` | Toxicity Sentinel | Adverse-selection scoring, explainable signals |
| `#/investigations` | Investigation Case File | Evidence, rules, recommended controls |
| `#/models` | Model and Benchmark Center | Champion/challenger, walk-forward, markout lift |
| `#/memory` | Immune Memory Library | Learned adverse-selection episodes |
| `#/audit` | Decision Audit Trail | Full traceability of decisions and agent actions |

Nav groups: **Overview · Market · Operations · Intelligence** (see `frontend/src/routes.ts`).

## Domain vocabulary (v2 — use in all UI copy)

| Use | Avoid |
|---|---|
| Hyperliquid, `BTC-PERP` | Binance, `BTCUSDT`, generic CEX |
| Toxicity / adverse selection | Generic "risk", spoofing theater |
| Realized **markout** (10s, bps) | Unlabeled PR-AUC as headline |
| OFI, microprice vs mid, perp-oracle basis, funding ROC, OI delta, liquidation intensity | Fabricated adversary names without historical basis |
| Purged/embargoed walk-forward CV, isotonic calibration | Random split, "calibrated" without method |
| CatBoost markout classifiers (champion/challenger) | sklearn risk head labels in UI when backend differs |
| Historical toxic episodes (Oct-2025 cascade, JELLY playbook) | Made-up scenario lore |

Metrics must stay **honest**: headline is realized markout lift (bps) under a quoting
policy; PR-AUC in ~0.76–0.84 when shown, with methodology visible.

## Architecture constraints (UI-relevant)

- **Static-first hybrid SPA:** React + TS + Vite + Three.js; `npm run build` → `frontend/dist/`.
- **Data order:** `seed.ts` + `simEngine.ts` first; `provider.tsx` hydrates from Django API when up.
- **Live slice:** simulator + `useLiveRisk()` always local; engine tick 1.5s (4s reduced motion).
- **Routing:** hash-based; no backend required for deploy.
- **Design source of truth:** `CLAUDE.md` / `AGENTS.md` + `frontend/src/styles/*` (glass system committed).

## Non-goals (UI)

- No dark-mode-first retheme without explicit request (light glass is committed).
- No removing preview honesty badge while data is simulated.
- No résumé-inflated metrics in copy or fixtures without backend proof.
- No numbered nav sections (`01 / 08`) or scanline aesthetics.

## Key files

| Area | Path |
|---|---|
| Routes + product shape | `frontend/src/routes.ts` |
| Fixtures | `frontend/src/data/seed.ts` |
| Live stream | `frontend/src/data/simEngine.ts` |
| Data provider | `frontend/src/data/provider.tsx` |
| Shell | `frontend/src/components/shell.tsx` |
| Screens | `frontend/src/screens/*.tsx` |
| Primitives | `frontend/src/components/ui.tsx` |
| Motion | `frontend/src/components/motion/*`, `frontend/src/styles/motion.css` |
| 3D hero | `frontend/src/components/three/ImmuneCore.tsx` |
| API hydration | `frontend/src/api.ts` |
| Backend audit | `dashboard/models.py`, `marketimmune/agentic/` |

## Open product gaps (inform copy, not hide)

- Hyperliquid ingest, markout labels, and CatBoost training exist in Python modules but
  are not fully productized in the dashboard data path yet.
- UI shows v2 vocabulary on preview/sim data; keep labels and provenance panels explicit.
- Agent count docs vary (5 stages vs 8 roles); UI should refer to **stages** or name roles, not ambiguous counts.

## Impeccable commands — suggested starting points

1. **`/impeccable critique command`** — first UX pass on the highest-traffic surface (Command Center + shell).
2. **`/impeccable audit frontend/src`** — contrast, motion reduced-mode, responsive headings on changed screens.
3. **`/impeccable polish frontend/src/screens/ModelBenchmark.tsx`** — provenance/honesty panel is critical for credibility.
4. **`/impeccable clarify frontend/src/data/seed.ts`** — align fixture copy with what Python actually implements.
