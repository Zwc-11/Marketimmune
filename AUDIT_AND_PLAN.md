# MarketImmune — State-of-the-Repo Audit & Remediation Plan

*A file-by-file audit of what the code actually does today, where it diverges from
the résumé and the v2 vision, and a phased plan to (1) make the project honest now,
(2) simplify the architecture, and (3) build toward the résumé claims so every line
is backed by real code.*

Status date: 2026-06-15 · Scope scanned: ~17.3k lines Python, ~6.3k lines TS/TSX,
Django app, benchmark suite, configs, docs.

---

## 0. TL;DR — the one thing to internalize

This repo currently ships **three different products that disagree with each other**:

| Layer | What it claims | What it is |
|---|---|---|
| **Résumé / `CLAUDE.md` / retired v2 plan** | Hyperliquid perps, CatBoost, markout +15 bps, purged walk-forward CV | The *aspiration*. None of it is implemented. |
| **Frontend (`frontend/src`)** | "CatBoost markout classifier", "Hyperliquid S3 archive", `realized_markout_bps` | **Theater.** Hard-coded strings + a `Math.sin` stream. No backend produces any of it. |
| **Python backend (`marketimmune/`)** | — | The *real* v1: synthetic scenario data → scikit-learn `GradientBoostingClassifier` → random train/test split → binary "hostile/benign" label. |
| **`README.md`** | "real Binance data", "Gradient-Boosting", "PR-AUC 0.989" (×3) | The *old* v1 story, which your own v2 plan calls a "label-leakage artifact." |

**The gap is not a bug — it is the whole problem.** The résumé describes a system
that the code does not contain, and the demo a recruiter opens (`frontend`) advertises
that same non-existent system in hard-coded text. A recruiter who runs `grep -ri
catboost marketimmune/` finds nothing. That single check turns an impressive project
into a credibility problem.

The good news: the **bones are genuinely strong** (clean agent framework, structured
audit traces, broad tests, strict tooling). The plan below keeps the bones, deletes
the theater, and builds the real thing in honest phases.

---

## 1. Résumé claim-by-claim audit

Your résumé bullets, checked against the code line by line.

### Bullet 1 — "Built a toxic-flow detection platform on **real Hyperliquid perpetual-swap data**"

| Sub-claim | Reality | Verdict |
|---|---|---|
| Hyperliquid | `marketimmune/adapters/factory.py:37` raises `ValueError("Hyperliquid arrives in Phase 1")`. The only adapter is Binance (`adapters/binance.py`), which just re-exports the simulator's parquet repos. `ingest/` is 100% `binance_*`. | ❌ Not implemented |
| perpetual-swap | The data model is Binance USD-M klines + aggregated %-from-mid depth bands (spot-like). No perp microstructure (funding, OI, basis, liquidations) is ingested. | ❌ |
| real data | No `data/` dir, no `.parquet`, no model artifact, no `reports/` exist in the repo. The trained model is built from **synthetic** scenario templates (`models/dataset.py`). | ❌ The model never sees real data |
| "toxic-flow detection" | The label is `hostile vs benign` from a scenario registry, not adverse selection. | ⚠️ Renamed, not rebuilt |

### Bullet 2 — "Generate → Detect → Investigate → Decide → Remember loop across **5 agents**, storing traces and policy decisions in a **Django ORM audit log**"

| Sub-claim | Reality | Verdict |
|---|---|---|
| The 5-stage loop | Real and clean. `agentic/loop.py` wires it explicitly. | ✅ |
| "5 agents" | The loop actually wires **8** agents (RedTeam, Simulator, Sentinel, Investigator, Policy, Memory, **Trainer, Judge**). `loop.py` docstring says "five Day-1 agents" then "seven agents"; README says "six" and "Eight." The count is inconsistent in every doc. | ⚠️ Defensible (5 = the 5 *stages*) but fix the inconsistency |
| Django ORM audit log | Real. `dashboard/models.py` + migration `0005_agentic_loop_models` persist `ImmuneLoopRun`, `AgentRunRecord`, `PolicyDecisionRecord`, etc. | ✅ **Your strongest, most defensible claim** |

This bullet is the keeper. The agent framework (`agentic/base.py`) is well-designed:
an `Agent` ABC that wraps `_execute()` with timing/error capture and emits immutable
`AgentRun`/`ToolCall`/`DecisionTrace` records, deterministic by default with an
optional LLM. Lead with this in interviews.

### Bullet 3 — "Engineered **point-in-time order-flow features** and trained a **CatBoost** model under **purged walk-forward CV**, lifting **out-of-sample markout by 15 bps** vs. baseline"

| Sub-claim | Reality | Verdict |
|---|---|---|
| CatBoost | The model is `sklearn.ensemble.GradientBoostingClassifier` (`models/risk_head.py:31,215`). `MODEL_NAME = "GradientBoostingRiskHead-v1"`. CatBoost is not a dependency and not imported anywhere. | ❌ Wrong model |
| purged walk-forward CV | CV is `sklearn.train_test_split` (random row split, `risk_head.py:211`) or a scenario-family hold-out. No temporal split, no purge, no embargo. `grep -ri "purg\|embargo\|walk" marketimmune/` is empty. | ❌ Not implemented |
| out-of-sample markout +15 bps | There is **no markout label and no bps metric anywhere in Python.** The benchmark reports PR-AUC/ROC-AUC/F1/precision@50/accuracy. The only "markout bps" in the repo is `frontend/src/data/simEngine.ts:131`: `markoutBps = (0.5 - toxicity) * 9.5` — a cosmetic transform of a sine wave. | ❌ The number does not exist |
| point-in-time features | `features/order_features.py` is a plain aggregation over an event list — no as-of join, no `max(feature_ts) ≤ fill_ts` invariant. | ❌ Aggregated, not point-in-time |
| "calibrated" | `risk_head.py` docstrings say "calibrated" but there is no `CalibratedClassifierCV`, isotonic, or Platt step. Raw `predict_proba`. | ❌ Claimed, not done |

**Bullet 3 is currently ~0% backed by code.** It describes the v2 target in
`CLAUDE.md`. This is the bullet that does the most damage if a reviewer reads the repo,
and the one Phase 2 below is designed to make true.

---

## 2. The central architecture problem — duplication & disconnection

You said the architecture and folder structure are bad. Concretely, the problem is
**parallel subsystems that do the same job and never share a contract.** This is why it
feels both over-built and fragile.

### 2.1 Two scenario subsystems (corrected finding)

> **Correction (consumer-mapped in code):** an earlier draft listed "four scenario
> systems." That overstated it — two of those are not separate systems:
> `agentic/redteam.py` is a *consumer* of Layer A's registry, and `agents/` is the
> *building block* of Layer B. There are really **two load-bearing layers**, each with
> its own consumers and tests, so **there is no dead system to delete:**

**Layer A — live-product scenarios** (`simulator/scenarios.py`: `ScenarioRegistry` +
`AgentScenario`): 6 scenarios that emit per-tick *feature-template dicts*. Consumed by
the simulator (`replay_builder`, dashboard `simulator` view + service), the agentic loop
(`redteam`, `market_simulator`), and the **risk-head dataset** (`models/dataset.py`).

**Layer B — benchmark scenarios** (`scenarios/generator.py` + `config.py` + `labels.py`,
built on `agents/benign.py` + `unsafe.py`): agent classes that emit *event streams*
(`AgentOrderEvent`) with per-event labels. Consumed by AegisBench, the
`run_*`/`generate_scenarios` scripts, and the replay + `features` tests.

The duplication is **conceptual**: the same adversary concepts (spoofing, momentum
ignition, TWAP, inventory rebalancer, passive MM) are modeled twice — once as feature
templates (A), once as event-stream agents (B). The correct v2 design makes **B
canonical** and *derives* A's features by running B's streams through `feature_store` —
which is the **same change as the feature-pipeline unification (§2.3)**. So this is not
a quick delete-one-keep-one; it is a Phase-2-scale merge that touches the benchmark, the
simulator, and the risk head, and must be done against the test suite. Interim guard
shipped: `tests/simulator/test_feature_contract.py` locks Layer A's feature keys to
`FEATURE_ORDER` so the two layers cannot silently drift further apart.

### 2.2 Two replay engines

- `marketimmune/replay/` — a full matching engine (`matching_engine.py`, `order_book.py`, `shadow_book.py`, `clock.py`, `cursor.py`) — heavy, used by the benchmark/MTPP path.
- `marketimmune/simulator/replay_builder.py` — a simpler builder — the one the dashboard actually uses.

### 2.3 Train/serve transform skew (corrected finding)

> **Correction (verified in code):** an earlier draft called this "three feature
> vocabularies." That overstated it. Backend training and serving actually **share the
> same feature names** — the `w{ms}_{domain}_{feature}` convention (e.g.
> `w1000_agentic_burst_rate_per_second`). The real problem is that two different code
> paths *produce* those identically-named features:

| Path | How the features are produced | Where |
|---|---|---|
| **Training** | Hard-coded constant values per scenario, then noised | `simulator/scenarios.py` `step()` → `models/dataset.py` |
| **Serving** | Computed from the event stream via rolling windows | `features/feature_store.py` (`order/market/agentic` × 1s/5s/60s) |
| **Display** | A separate, smaller set of human-readable names (a *view*, fine to differ) | `frontend/src/data/simEngine.ts` (`order_flow_imbalance`, …) |

So the model trains on hand-written template numbers but, at inference, sees numbers
computed by `feature_store` — **same names, different transform** → silent train/serve
skew (the Phase 1 failure mode described here). Worse for extensibility: the 10
feature keys are **duplicated by hand across all 6 scenario classes**, so adding a
feature means editing `FEATURE_ORDER` *and* every scenario. The fix (Phase 1→2): route
training data through the *same* `feature_store` transform, over generated event
streams, instead of hand-written templates.

### 2.4 Multiple fixture/data layers

`dashboard/demo_data.py`, `frontend/src/data/seed.ts`, `frontend/src/data/simEngine.ts`,
plus legacy demo ORM tables — four places that fabricate "what the system looks like."

### 2.5 Dead v2 scaffolding

`marketimmune/ports/` + `adapters/` is the hexagonal seam from the v2 plan, but it is
**empty scaffolding**: `factory.py` knows only `binance` and raises on anything else.
The seam adds indirection today without enabling anything — it is a promise, not a port.

### 2.6 The disconnect, in one sentence

> The Python backend is **v1** (Binance + GBM + synthetic), the frontend is **v2 cosplay**
> (hard-coded CatBoost/Hyperliquid/markout strings over a `Math.sin` generator), and they
> share **no data contract** — the frontend never needs the backend to be true.

---

## 3. File-by-file findings

Organized by directory. ✅ = keep, ⚠️ = fix, ❌ = delete/replace, ➕ = missing.

### `marketimmune/agentic/` — the immune loop (the crown jewel)
- ✅ `base.py` — clean `Agent` ABC, immutable trace value objects. **Keep as the template.**
- ✅ `loop.py` — explicit, data-only orchestration. ⚠️ Fix the "five/seven/eight agents" docstring contradiction; pick one number and state it once.
- ✅ `sentinel.py`, `investigator.py`, `policy.py`, `memory.py`, `judge.py` — coherent, well-traced.
- ⚠️ `trainer.py` — shells out to `scripts/train_risk_head.py` via `subprocess` and labels the run `dataset_version = "synthetic-{timestamp}"`. The self-improvement loop is real *mechanism* over a *meaningless signal* (it retrains on regenerated synthetic data). Honest, but advertise it as "retraining harness," not "the model learns."
- ⚠️ `market_simulator.py` — uses the `simulator/` replay; fine, but it's the bridge that papers over the train/serve transform gap (§2.3).
- ✅ `llm.py`, `redteam.py` — deterministic-by-default with optional DeepSeek (V4, OpenAI-compatible over `httpx`; `AnthropicLLMClient` removed per "no more Claude API"). Good discipline.

### `marketimmune/models/` — the ML head
- ⚠️ `risk_head.py` — works, but: it's GBM (not CatBoost), docstring says "calibrated" without calibration, `_top_contributions` is `value × global importance` (a SHAP stand-in it admits is "not as principled"). Rename claims to match, or implement the real thing (Phase 2).
- ❌ `dataset.py` — **the root of the credibility problem.** Builds the training set from scenario templates × lognormal noise + "contamination." The 0.989 measures this generator. Must be replaced by a real label pipeline (Phase 2), not patched.
- ✅ `mtpp/order_s2p2.py`, `mtpp/gru_mtpp.py` — genuine implementations (CT-LSTM / Neural Hawkes, Mei & Eisner 2017). ⚠️ But their dashboard metrics are **seeded from `demo_data.py`**, not real training runs. Either train-and-report for real or relabel as "target metrics." Note these models are *not* the served risk head — decide if they earn their keep or move to `research/`.

### `marketimmune/features/` — feature engineering
- ⚠️ `order_features.py`, `market_features.py`, `agentic_features.py`, `windows.py` — real windowing, but plain aggregation with **no point-in-time / as-of correctness** and no leakage invariant. This is where the "point-in-time" résumé claim must be earned.
- ✅ `feature_store.py` — **dependency direction fixed (Phase 1 done):** `p95` moved to the neutral `marketimmune/stats.py`, so `features/` no longer imports from `replay/` (re-exported from `replay_runner` for back-compat). ⚠️ Still TODO: training builds its rows from `scenarios.py` templates, not this transform (§2.3) — route training through `feature_store` so train == serve.

### `marketimmune/ports/` + `adapters/`
- ⚠️ Empty seam (see §2.5). Keep the *idea*, but only once a second adapter (Hyperliquid) actually exists, or it's just indirection.

### `marketimmune/replay/` vs `marketimmune/simulator/`
- ⚠️ Two engines (§2.2). Pick one as canonical; demote the other to clearly-scoped use or delete.

### `marketimmune/scenarios/` + `marketimmune/agents/`
- ⚠️/❌ Overlaps `simulator/scenarios.py` and `agentic/redteam.py` (§2.1). Consolidate to one scenario source feeding both training and the loop.

### `marketimmune/ingest/` + `lake/`
- ✅ Real Binance downloader/parsers/coverage + parquet I/O with manifest. ➕ Needs a Hyperliquid sibling for Bullet 1 to be true. `duckdb`/`polars` are dependencies but the "Medallion lakehouse" from the plan is not built.

### `marketimmune/schemas/`
- ✅ `events.py`, `labels.py`, `manifests.py` — Pydantic contracts. Good. ➕ Add a `markout`/toxicity label schema in Phase 2.

### `dashboard/` (Django)
- ⚠️ `models.py` (587 lines) — **two eras coexist**: legacy demo tables (`BenchmarkMetrics`, `TaskMetric`, `ModelMetric` whose choices are `gru_mtpp`/`s2p2_nhp` — not the GBM head actually served, `ProjectStats`, `DemoMarketEvent`, `DemoAgentEvent`) and the new agentic audit tables. Split into `models/legacy.py` + `models/audit.py` or delete the demo tables.
- ⚠️ `views/legacy_dashboard.py` + `api_demo.py` coexist with the new `views/agentic.py` (417 lines) and `views/simulator.py`. Legacy demo views should go to a `legacy/` package or be deleted.
- ✅ `services/agentic_service.py`, `services/simulator_service.py` — the Facade layer is a good pattern; keep.

### `frontend/src/`
- ❌ `data/simEngine.ts` — hard-codes `model_name: 'CatBoost markout classifier'` (L161), `source: 'Hyperliquid S3 archive'` (L58,151), fake `realized_markout_bps` (L131), and comments claiming "real episodes, not fabricated" over pure synthetic generators. **61 references to v2 vocabulary the backend doesn't have.** This is the single most dangerous file in the repo for credibility.
- ⚠️ `data/seed.ts`, `data/provider.tsx` — static-first design is legitimate *if labeled as a demo*. Today it's labeled as the product.
- ✅ Component/screen structure, motion system, Three.js hero — genuinely good front-end craft. The problem is the *copy*, not the code.

### `aegisbench/`
- ✅ Small (373 lines), real benchmark harness with 6 task types + leaderboard CSV. Modest but honest. Decide if it's still part of the story or legacy from the Binance era.

### Tests & tooling
- ✅ 32 test files across agentic/agents/features/ingest/lake/models/policy/replay/schemas/simulator. `mypy --strict`, `ruff` (E,F,I,UP,B,SIM), `pytest`, coverage `fail_under = 100`, GitHub Actions CI. **This discipline is a real strength — protect it.**

---

## 4. Folder & repo-hygiene issues

- ✅ `.coverage` (167 KB binary) is present in the working tree but is **gitignored and untracked** (`.gitignore` line 16; not in the git index), so it won't be committed. No action needed — noted only as a stray local artifact you can delete.
- ⚠️ Root `package.json` (`"name": "marketimmune-dashboard"`) + `tsconfig.json` build a **second, legacy Django-template dashboard** (`dashboard/static/ts` → `dashboard/static/js/dashboard.js`, still loaded by `dashboard/templates/dashboard/index.html`). It coexists with the real Vite/React app in `frontend/` — **two separate front-ends and TS toolchains.** Don't delete blindly: decide in **Phase 1** whether the legacy Django-template dashboard is retired (then remove the root pair) or kept.
- ⚠️ **Four ways to run the project**: `Makefile`, `make.ps1`, `setup_dashboard.sh`, `setup_dashboard.bat`. Consolidate to one documented entrypoint per OS.
- ✅ **Planning docs collapsed:** `AUDIT_AND_PLAN.md` is now the canonical roadmap; obsolete aspirational roadmap files have been removed. Keep `README.md` short and honest, and update this file when the plan changes.
- ⚠️ Large uncommitted working tree (~30 modified files including `CLAUDE.md`, `README.md`, CI config). Commit or revert intentionally before showing the repo; a messy `git status` reads as unfinished.
- ⚠️ Generic Django naming (`dashboard_project/`) is fine but `dashboard/` is doing too much (demo + agentic + simulator). Consider `audit/` (agentic) split from `demo/`.

---

## 5. The phased plan

Per your choice: **honest now → simplify → build to résumé.** Each phase is
independently shippable and leaves the repo in a better, truthful state.

### Phase 0 — Honesty & alignment (½–1 day) — *do this before anyone sees the repo*

Goal: every claim in the repo is either true or labeled as a target. Zero new ML.

1. **Frontend de-theater.** In `simEngine.ts` + `seed.ts`, replace hard-coded
   `'CatBoost markout classifier'` and `'Hyperliquid S3 archive'` with what's real, OR
   add an unmistakable `DEMO DATA — illustrative, not live` banner in the UI and a
   `source: 'simulated'` field on every record. Remove the "real episodes, not
   fabricated" comments.
2. **README rewrite.** Delete the 0.989 / Binance / "Gradient-Boosting PR-AUC 0.989"
   headline. State plainly: what's built (agent loop + audit trail + GBM baseline on
   synthetic scenarios + working dashboard), what's simulated, what's planned (v2).
   Fold the three docs into one `README` + one `ROADMAP`.
3. **Fix the agent count** everywhere to one consistent number with a definition
   ("5 loop stages, 8 agent roles").
4. **Relabel `risk_head.py`** — drop "calibrated" until it is, rename `_top_contributions`
   to reflect it's an importance-weighted proxy, not SHAP.
5. **Repo hygiene** — pick one run script (consolidate `Makefile` / `make.ps1` /
   `setup_dashboard.{sh,bat}`), and commit the working tree intentionally. (The root
   `package.json`/`tsconfig.json` belong to the *legacy* Django-template dashboard —
   defer their removal to the Phase 1 front-end consolidation, not here.)
6. **Résumé interim rewrite** (see §7) so it matches the honest repo *today*.

Exit criteria: `grep -ri "catboost\|hyperliquid\|markout" .` returns only items that
are clearly labeled as roadmap/target, and `README` makes no claim the code can't back.

### Phase 1 — Architecture simplification (2–4 days) — *simple, but leaves space*

Goal: collapse the parallel subsystems into single contracts with clean seams.

1. **One feature pipeline.** Make `features/feature_store.py` the *single* transform
   used by training, serving, and the dashboard. Delete `models/dataset.py`'s bespoke
   feature synthesis; training consumes the same `feature_snapshot()` output. This kills
   the train/serve transform skew (§2.3) — the highest-leverage refactor in the repo.
2. **One scenario source.** Pick `ScenarioRegistry` as canonical; have `redteam`,
   the dataset, and the benchmark all draw from it. Move the others to `legacy/` or delete.
3. **One replay engine.** Choose `replay/` (full) or `simulator/replay_builder.py`
   (simple) as canonical for the loop; scope or delete the other.
4. **Split `dashboard/models.py`** into `audit/` (agentic tables) and `demo/` (or delete
   demo tables). Same for views.
5. **Define the data contract** between frontend and backend (a typed DTO the Django
   API returns and the React provider consumes) so the frontend can no longer drift
   from the backend.
6. **Fix dependency directions** (e.g., `feature_store` importing from `replay`).

The "leave space" principle: keep the **ports, the registry, and the `Agent` ABC** —
those are the cheap seams that let you add a venue, a scenario, or an agent without a
rewrite. Delete the *duplicate implementations*, not the *extension points*. Don't add a
port until it has two real implementations.

Target structure:

```
marketimmune/
  core/         # domain: Agent ABC, loop, value objects (no I/O)
  features/     # ONE shared transform lib (train == serve)
  data/         # adapters (binance/, hyperliquid/) behind one port
  models/       # risk head + (research/ for MTPP if kept)
  scenarios/    # ONE registry
  audit/        # event/decision records (or keep in Django)
dashboard/      # thin Django: API + ORM persistence only
frontend/       # React; consumes the typed contract, no fabricated copy
```

### Phase 2 — Build toward the résumé (the real work, 1–3 weeks)

Make Bullet 1 and Bullet 3 true, in dependency order. Each step is a defensible
interview talking point on its own.

1. **Hyperliquid ingestion** → `data/hyperliquid/` adapter reading the public S3
   archive (fills, L2 book, funding, OI, liquidations) into the parquet lake. Register
   `hyperliquid` in `adapters/factory.py`. *Now the port earns its existence.*
2. **Markout label** → implement `markout(h) = sign(side)·(mid_{t+h} − p)/p` for
   h ∈ {1s,10s,60s}; `toxic = markout < −fee`. Add the label schema. *This replaces
   the synthetic binary label — the credibility core.*
3. **Point-in-time features** → as-of joins in `features/`, with the hard test
   invariant `max(feature_ts) ≤ fill_ts`. Add OFI, microprice−mid, basis, funding RoC,
   OI delta, liquidation intensity (the `CLAUDE.md` taxonomy).
4. **CatBoost head** → add `catboost` dep; train `CatBoostClassifier` on the real
   features/labels. Keep the GBM/rule baselines for lift comparison.
5. **Purged & embargoed walk-forward CV** → implement the López de Prado protocol
   (temporal folds, purge overlapping-label windows, embargo buffer). *This is the
   single technique that fixes the 0.99 illusion.*
6. **Calibration + honest metrics** → isotonic calibration; report Brier + reliability,
   PR-AUC in the honest 0.76–0.84 range, and **realized markout lift in bps** under a
   quoting policy vs. an OFI-only baseline. *This is where the "+15 bps" becomes a real,
   measured number — or you report whatever the honest number turns out to be.*

Exit criteria: `scripts/train_risk_head.py` (renamed) trains CatBoost on real
Hyperliquid markout labels under purged walk-forward CV and writes a `reports/` JSON
with a measured bps lift. The frontend reads that JSON. Every résumé word is now code.

### Phase 3 — Harden (optional, ongoing)

Drift monitors (PSI/KS), champion/challenger registry, resilience (retry/circuit
breaker) on the Hyperliquid/DeepSeek calls, and CI gates that run the leakage invariants
as tests. Only after Phases 0–2 land.

---

## 6. Priority-ranked action list (impact ÷ effort)

| # | Action | Phase | Effort | Why it matters |
|---|---|---|---|---|
| 1 | De-theater the frontend (kill hard-coded CatBoost/Hyperliquid/markout) | 0 | S | Removes the most findable lie |
| 2 | Rewrite README honestly; merge 3 docs → 2 | 0 | S | First thing a reviewer reads |
| 3 | Rewrite résumé to match reality (interim) | 0 | S | Stops a claim you can't defend |
| 4 | Unify to ONE feature pipeline (train==serve) | 1 | M | Kills train/serve skew; biggest code win |
| 5 | Consolidate scenarios/replay/fixtures | 1 | M | Removes the "over-built" feel |
| 6 | Hyperliquid adapter + markout label | 2 | L | Makes Bullet 1 + the label real |
| 7 | Purged walk-forward CV + CatBoost + bps lift | 2 | L | Makes Bullet 3 real |
| 8 | Repo hygiene (.coverage, dup configs, run scripts) | 0 | S | Cheap polish |

---

## 7. Résumé rewrite

**Interim (true *today*, after Phase 0)** — defensible against a full code read:

> - Built an **AI market-safety platform** that detects risky autonomous-trading
>   behavior and produces auditable risk decisions, with a React/TypeScript dashboard
>   over a Django REST API.
> - Designed a **Generate → Detect → Investigate → Decide → Remember** loop across
>   modular agents, persisting every tool call, decision trace, and policy action to a
>   **Django ORM audit log** (append-only, fully reproducible).
> - Engineered a multi-window order-flow feature store and a **gradient-boosting risk
>   head** with a held-out benchmark (PR-AUC / latency), behind a leakage-aware
>   evaluation **redesign** (purged walk-forward CV) currently being migrated to real
>   Hyperliquid perp data.

**Target (true after Phase 2)** — your current bullets, now backed:

> - Built a toxic-flow detection platform on **real Hyperliquid perpetual-swap data**…
> - …**CatBoost** model under **purged walk-forward CV**, lifting out-of-sample
>   **markout by N bps** vs. an OFI baseline. *(Report the measured N — honesty is the
>   selling point.)*

Pick the interim version now; let Phase 2 earn the target version. **Never ship a
bullet the repo can't survive a `grep` of.**

---

## 8. What to protect

Don't "simplify" these away — they're the parts that already work and signal quality:
the `Agent` ABC + structured traces (`agentic/base.py`), the Django ORM audit trail,
the strict tooling (mypy/ruff/100% coverage/CI), the real MTPP implementations, and the
front-end craft. The plan removes *duplication and dishonesty*, not *capability*.

---

## 9. Execution log (what has actually been applied to the repo)

### Phase 0 — Honesty & alignment ✅ DONE
- **Frontend de-theater:** persistent "Preview · simulated data" badge (`frontend/src/components/shell.tsx`); fake provenance `'Hyperliquid S3 archive'` → `'Simulated (preview)'` and the false "real episodes, not fabricated" comment removed (`simEngine.ts`); honest "synthetic preview" headers added (`simEngine.ts`, `seed.ts`).
- **`README.md` rewritten:** *What's real today / What's simulated / What's planned*; removed the `0.989` PR-AUC + "real Binance data" headline.
- **Agent count** made consistent in `marketimmune/agentic/loop.py` (5 stages / 8 roles).
- **`risk_head.py`:** removed unsupported "calibrated" wording (now states calibration is planned, not applied).
- **`RESUME_BULLETS.md`** added (interim bullets true today + target bullets for after Phase 2).
- **`.coverage`** confirmed gitignored *and* untracked — no action needed.

### Phase 1 — Architecture simplification 🚧 STARTED
- ✅ **Old plan docs removed:** deleted the retired v2 refactor plan and the older recruiter roadmap; `README.md`, code comments, and tests now point to `AUDIT_AND_PLAN.md` as the single source of truth.
- ✅ **Dependency direction fixed:** `p95` moved to a neutral `marketimmune/stats.py`; `features/` no longer imports from `replay/`. Re-exported from `replay_runner` so `tests/replay/test_replay.py` keeps working.
- ✅ **§2.3 corrected** ("three vocabularies" → the accurate train/serve transform skew).
- ✅ **`dashboard/models.py` split by concern** → `models_audit.py` (9 models), `models_simulator.py` (9), `models_demo.py` (11); `models.py` now re-exports all 29. Backward-compatible (every `from dashboard.models import X`, the admin, and migrations still resolve); **zero new migrations** because Django tracks models by `app_label`, not module path. Verify: `python manage.py makemigrations --check --dry-run` → "No changes detected".
- ✅ **Scenario systems mapped + §2.1 corrected:** consumer-tracing shows two *load-bearing* layers (live-product `ScenarioRegistry` vs benchmark `scenarios/`+`agents/`), not four redundant ones — **no dead code to delete.** Added `tests/simulator/test_feature_contract.py` locking Layer A's feature keys to `FEATURE_ORDER`. The real A/B merge is entangled with item 1 (feature pipeline) and is Phase-2-scale.
- ⏳ **Remaining (behavioral — apply locally with the test suite running):**
  1. Route training through `feature_store` over generated event streams (kills the §2.3 train/serve skew; stop hand-writing feature values in `scenarios.py`). *Best folded into Phase 2's real-data work — it changes the benchmark numbers.*
  2. Merge the two scenario layers (§2.1): make benchmark event-streams canonical and *derive* the feature-template scenarios via `feature_store`. Entangled with item 1; Phase-2-scale; needs the local test loop.
  3. Pick one replay engine (§2.2). *(Same — deletion + test updates.)*
  4. Define a typed frontend↔backend DTO (§2.6).

### Provider migration — DeepSeek (per "no more Claude API")
- ✅ `marketimmune/agentic/llm.py` rewritten: new `DeepSeekLLMClient` (OpenAI-compatible over `httpx`, default `deepseek-v4-pro`), provider-aware `build_default_llm` (default `deepseek`), `AnthropicLLMClient` removed. Dropped the `anthropic` dependency; swapped `ANTHROPIC_API_KEY`/`CLAUDE_*` → `DEEPSEEK_*` across `.env.example`, the LLM-status view, `manage.py`, `base.py`, `seed.ts`, README, and the plan docs.
- ✅ **Provider hygiene completed:** removed the stale `anthropic` dashboard requirement, updated the legacy Django template's visible LLM badges to DeepSeek, and verified no `Claude`/`Anthropic` provider references remain in dashboard/frontend/backend/README/env files.
- ✅ Fixed the `httpx` F401 (now used) and 6 pre-existing mypy `np.ndarray` generic errors in `risk_head.py` / `dataset.py`.
- ✅ **Live DeepSeek smoke + mock immune-loop run completed** from `.env`: `MARKETIMMUNE_USE_LLM=1` was set for the process only, `build_default_llm(load_env=False)` constructed the `deepseek` client, and a direct `client.complete(...)` call returned `DEEPSEEK_SMOKE_OK` over `https://api.deepseek.com/chat/completions` (`HTTP 200`). Then the free Hyperliquid Info API seeded 90 recent BTC 1m candles + live L2 depth into the local replay lake, and `AgenticService.run_once(difficulty="hard", tick_limit=60)` persisted `loop_7d9ae5c69428`: all 8 agents ran, 5 alerts, 5 cases, 1 new memory, 6 `llm.complete` tool calls, and 6 accepted LLM traces (`proposal_rationale_source=llm`, case narratives sourced from `llm`). No fake LLM response was counted.
- ✅ **DeepSeek reasoning-model budget fix:** `deepseek-v4-pro` can spend small `max_tokens` budgets entirely on hidden `reasoning_content`, yielding empty visible `content` with `finish_reason="length"`. RedTeam/Investigator prompts were made compliance-oriented and their per-call budgets raised (`1000` / `1200`) so the loop records visible LLM rationale/narratives while still never exposing reasoning text.

### Phase 2 — Build toward the résumé 🚧 STARTED
- ✅ **Markout label shipped** (`marketimmune/labels/markout.py` + a 100%-coverage test): the real adverse-selection target — `markout_bps = side·(mid_{t+h} − p)/p·1e4`, a forward as-of mid lookup that returns `None` past the data end (no fabricated look-ahead), `is_toxic` on fee-adjusted markout, horizons {1s, 10s, 60s}. **First time "markout" exists as backend code instead of a frontend string.** Not yet wired into training — that needs real data (below).
- ✅ **Hyperliquid archive parser shipped** (`marketimmune/ingest/hyperliquid_archive.py` + 100%-coverage test): S3 key builders, `L2Level`/`BookSnapshot` value objects, an NDJSON `l2Book` parser (tolerant of the `{channel,data}` envelope), and top-of-book microstructure features (mid, spread bps, microprice, top imbalance). Built to the real documented schema. Network (boto3) + codec (lz4) are **injected callables** (Ports & Adapters), so the parsing is pure and fully tested; the boto3/lz4 wiring is the only `# pragma: no cover` boundary, installable via `pip install -e ".[hyperliquid]"`. **Still TODO (your machine):** run the requester-pays backfill and land Bronze→Gold so `feature_store` + `labels.markout` produce a real training set.
- ✅ **Requester-pays L2 archive schema smoke confirmed** against a real downloaded file (`s3://hyperliquid-archive/market_data/20230916/9/l2Book/SOL.lz4`, `ContentLength=200608`, `RequestCharged=requester`): the archive rows wrap the WebSocket l2Book payload under `raw`, so `parse_book_snapshot` now accepts plain, `{channel,data}`, and `{raw:{channel,data}}` shapes. The local decode parsed 5,568 SOL snapshots and produced top-of-book features.
- ✅ **Free Hyperliquid Info API sample path shipped** (`marketimmune/ingest/hyperliquid_api.py`, `scripts/fetch_hyperliquid_api_sample.py` + 100%-cov parser tests): fetches current/recent `allMids`, `l2Book`, `metaAndAssetCtxs`, and `candleSnapshot` data, parses them into the existing `BookSnapshot` / `AssetCtx` / `Candle` value objects, and writes Silver L2 / asset-context / candle parquet samples. This is useful for live smoke data and recent market context; it is **not** a replacement for historical fills from requester-pays S3.
- ✅ **Free Hyperliquid replay-lake bridge shipped** (`marketimmune/ingest/hyperliquid_replay_seed.py`, `scripts/seed_hyperliquid_replay_lake.py`, `tests/ingest/test_hyperliquid_replay_seed.py`): calls the free public Info API, writes the native Hyperliquid Silver samples, and also writes a small current/recent replay seed into the existing simulator lake shape (`data/lake/binance_usdm/...`) until a true Hyperliquid replay adapter exists. It clamps each seed to one UTC date so candle and depth files stay aligned. This is intentionally a bridge, not the final venue adapter.
- ✅ **Free Hyperliquid live dashboard path shipped** (`/api/hyperliquid/live/`, `/api/hyperliquid/candles/`, `dashboard/services/hyperliquid_service.py`, `frontend/src/api.ts`, `frontend/src/config.ts`, `frontend/src/components/shell.tsx`, `frontend/src/screens/LiveCockpit.tsx`): Django calls the free public Info API for the configured `MARKETIMMUNE_HYPERLIQUID_COIN`, computes top-of-book features from real L2/asset-context responses, fetches recent candles for the Live Market chart, and the React market strip/chart render only live/cache values. There is no simulator price fallback; if the live API is blocked or misses the configured budget, the live market panels say unavailable. The browser does not send a 100 ms budget by default anymore; Django's `.env` budget is the request-time source unless `VITE_MARKETIMMUNE_HYPERLIQUID_BUDGET_MS` is explicitly set.
- ✅ **Hyperliquid asset-contexts parser shipped** (`marketimmune/ingest/hyperliquid_asset_ctxs.py` + 100%-cov test): an `AssetCtx` value object, a **column-configurable** CSV parser (defaults = the documented API field names, since the exact archive header isn't published), and the pure derivatives-state signals — perp-oracle **basis (bps)**, **funding rate-of-change**, **OI delta** — plus injected-IO `load_asset_ctxs`.
- ✅ **Requester-pays asset-context schema smoke confirmed** against `s3://hyperliquid-archive/asset_ctxs/20230916.csv.lz4` (`ContentLength=2698358`, `RequestCharged=requester`): historical CSV headers are snake_case (`open_interest`, `oracle_px`, `mark_px`, `mid_px`) while the live API uses camelCase. `parse_asset_ctxs_csv` now auto-detects both. The local decode parsed 72,000 context rows and the SOL one-hour smoke backfill wrote Silver L2 + asset-context parquet.
- ✅ **Minute-level asset-context timestamps preserved:** historical `asset_ctxs` rows include a `time` column; `AssetCtx` now carries `ts_ms`, Silver asset-context parquet writes it, and the Gold training join uses the latest context at or before each fill instead of treating context as static daily data.
- ✅ **Hyperliquid fills parser shipped** (`marketimmune/ingest/hyperliquid_fills.py` + 100%-cov test): documented API fill fields (`coin`, `px`, `sz`, `side`, `time`, `crossed`, fee/order/trade ids), tolerant block/archive envelopes (`fill`, `fills`, `userFills`, `nodeFills`), maker-side conversion for markout labels (`crossed=True` flips user side), and injected-IO `HyperliquidNodeFills`. **Honest caveat:** the `node_fills_by_block` object-key partition and any archive-only fields still need confirmation against a real requester-pays listing/file.
- ✅ **Requester-pays node-fills schema smoke confirmed**: bounded listing shows the real partition is `node_fills_by_block/hourly/<YYYYMMDD>/<hour>.lz4` (for example `node_fills_by_block/hourly/20250727/8.lz4`, `ContentLength=1517603`, `RequestCharged=requester`; current-hour files on 2026-06-20 are ~14–35 MB each). The payload is NDJSON block rows with an `events` array; each event is `[user_address, fill_object]`. `iter_fill_mappings` now accepts that shape and keeps `user` in the raw fill record. The local decode parsed 17,516 fills from the one-hour file, including 474 SOL fills.
- ✅ **Pure Gold markout assembly shipped** (`marketimmune/ingest/hyperliquid_gold.py` + 100%-cov test): combines parsed fills with L2-book mids, emits horizon-keyed markout bps + toxicity flags, skips unavailable future horizons instead of fabricating labels, and stays I/O-free so persistence can evolve separately.
- ✅ **Hyperliquid Bronze/Silver/Gold parquet writers shipped** (`marketimmune/ingest/hyperliquid_lake.py` + 100%-cov test): defines a simple lake layout, writes Bronze parsed fills with raw JSON, Silver conformed fill rows, Silver L2 top-of-book rows, Silver asset-context rows, and flattened Gold markout rows with zstd Parquet. The writer is intentionally thin and testable: parsers own schema interpretation, Gold assembly owns labels, and this layer owns only paths + serialization.
- ✅ **Hyperliquid daily backfill coordinator shipped** (`marketimmune/ingest/hyperliquid_backfill.py` + 100%-cov test): coordinates explicit hourly L2 keys, daily asset contexts, explicit node-fill suffixes, non-empty parquet writes, and Gold markout assembly. It still does **not** infer the undocumented `node_fills_by_block` partition; the real S3 listing/schema confirmation remains a machine/network task.
- ✅ **Requester-pays backfill CLI wrapper shipped** (`scripts/backfill_hyperliquid_day.py` + tested CLI wrapper): accepts explicit `--hour` and confirmed `--fill-suffix` inputs, builds requester-pays fetchers for the archive and node-data buckets, wraps fetches in retry/circuit breaker by default, runs `HyperliquidDailyBackfill`, and prints a JSON write summary. Verified locally with monkeypatched fetchers plus `--help`; the real run still needs AWS requester-pays access.
- ✅ **Requester-pays CLI progress + fill-hour helper shipped:** `scripts/backfill_hyperliquid_day.py` now prints per-object progress to `stderr` (`[fetch] ...`, `[done] ... bytes`) so long downloads no longer look frozen, and `--fill-hour 8-23` auto-generates the confirmed `hourly/<YYYYMMDD>/<hour>.lz4` suffixes. `--fill-suffix` still works for explicit objects; `--quiet` suppresses progress.
- ✅ **Point-in-time Hyperliquid feature join shipped** (`marketimmune/features/hyperliquid_features.py` + 100%-cov test): joins Gold markout labels to the latest prior Silver L2 features, attaches snapshot-derived event OFI plus 1s/5s/10s rolling OFI windows, optionally attaches asset-context signals, writes model-ready Gold training rows from the daily coordinator, and calls `assert_as_of` so any future feature timestamp raises `LeakageError`.
- ✅ **Purged/embargoed walk-forward splitter shipped** (`marketimmune/models/walk_forward.py` + 100%-cov test): creates contiguous temporal test folds, preserves original row indices, excludes train rows in `[test_start - purge, test_end + embargo]`, and validates split/purge/embargo inputs. This is the evaluation scaffold CatBoost will use once real Gold training rows exist.
- ✅ **Calibration metrics + isotonic fitting shipped** (`marketimmune/models/calibration.py`, `scripts/train_hyperliquid_markout.py` + tests): Brier score, non-empty reliability bins, expected calibration error, fold-local isotonic fitting, uncalibrated-vs-calibrated report blocks, and a deployable JSON calibrator artifact next to the `.cbm` model.
- ✅ **Markout evaluation report shipped** (`marketimmune/models/markout_evaluation.py` + 100%-cov test): consumes out-of-fold toxicity probabilities, timestamps, labels, and realized markout; groups them with the purged/embargoed splitter; reports PR-AUC, Brier, ECE, quote rate, and quoting-policy markout lift; and emits the compact `ModelMetrics` shape consumed by the promotion policy.
- ✅ **Full-day requester-pays Bronze/Silver/Gold backfill confirmed on real SOL data:** `python scripts/backfill_hyperliquid_day.py --coin SOL --date 20260601 --hour 0-23 --fill-hour 0-23 --lake-root data/hyperliquid` downloaded 24 hourly L2 archives, the daily asset-context file, and 24 hourly node-fill files; loaded 11,959,780 raw fills; filtered 210,598 SOL fills; built 210,592 Gold markout rows and 210,548 Gold training rows; and wrote 6 parquet artifacts under `data/hyperliquid/`.
- ✅ **Backfill performance fix shipped:** `marketimmune/features/hyperliquid_features.py` now builds timestamp indexes and uses point-in-time `bisect_right` lookups for latest-prior L2/context joins instead of repeated full scans. The same full-day run now reaches the write stage instead of appearing stuck after downloads.
- ✅ **Real calibrated CatBoost markout trainer shipped and run:** `scripts/train_hyperliquid_markout.py` trains `CatBoostClassifier` on one or more local Gold Hyperliquid training partitions (`--date` / `--dates`, `--coin` / `--coins`), produces out-of-fold probabilities under the purged/embargoed splitter, applies fold-local isotonic calibration, selects fold-local quoting thresholds from a configurable threshold grid and quote-rate budget, optionally evaluates a true held-out panel (`--holdout-date` / `--holdout-dates`), writes a JSON report, saves a `.cbm` model, and writes a JSON isotonic calibrator. Date ranges are strict by default; missing local partitions now produce an actionable error, while `--allow-missing-partitions` explicitly trains on available files and records skipped dates in the report. Latest local held-out run: train SOL `20260527..20260531`, hold out `20260601`, horizon `10s`, 5 splits, 60s purge/embargo, 150 iterations. Train CV: `PR-AUC=0.553`, `Brier=0.222`, `markout_lift_bps=0.854`, `baseline_delta=+0.138 bps`; holdout: `PR-AUC=0.556`, `Brier=0.233`, `markout_lift_bps=0.860`, `baseline_delta=+0.109 bps`. Artifacts: `reports/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json`, `data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.cbm`, and `data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.isotonic.json`.
- ✅ **Agentic real-data training path shipped:** `ModelTrainerAgent` now has `training_mode="hyperliquid_markout"` with a typed `HyperliquidTrainingSpec` that supports either a single coin/date or a coin/date panel. It launches `scripts/train_hyperliquid_markout.py`, writes durable candidate report/model/calibrator artifacts under `reports/candidates/` and `data/models/candidates/`, returns a structured `TrainingJob` with artifact paths, and preserves the old synthetic risk-head path for existing demos/tests. `ImmuneLoop.with_hyperliquid_training(...)` builds a loop whose self-improvement stage uses the real Hyperliquid trainer.
- ✅ **Agentic real-data training path shipped:** `ModelTrainerAgent(training_mode="hyperliquid_markout", HyperliquidTrainingSpec(...))` launches the same real-data CatBoost trainer, supports coin/date panels plus holdout coin/date panels, returns durable candidate report/model/calibrator artifacts, and preserves the old synthetic risk-head path for demos/tests. `BenchmarkJudgeAgent` now checks both CV and holdout baseline deltas and rejects candidates that lose to event OFI. With the explicit event-OFI incumbent report, the latest SOL held-out candidate receives `promote` (`7/7` criteria passed).

### Phase 3 — Harden 🚧 STARTED
- ✅ **Resilience layer shipped and wired into DeepSeek** (`marketimmune/resilience.py`, `marketimmune/agentic/llm.py` + 100%-coverage tests): `with_retry` (exponential backoff + **full jitter**) and `CircuitBreaker` (trip → fast-fail → half-open probe). `sleep`, the clock, and the RNG are injected, so both are fully deterministic under test. `DeepSeekLLMClient` now wraps its HTTP request with retry + circuit breaking while preserving the empty-string deterministic fallback contract. Hyperliquid fetch callables can use the same wrapper once the real backfill adapter lands.
- ✅ **Drift monitors shipped and wired into Memory/Loop** (`marketimmune/monitoring/drift.py`, `marketimmune/agentic/memory.py`, `marketimmune/agentic/loop.py` + 100%-cov tests): `psi` (quantile-binned Population Stability Index), `ks_statistic` (two-sample Kolmogorov–Smirnov), and `drift_severity` thresholds. `ImmuneMemoryAgent` can now emit a `DriftReport` from reference/current score windows, and `ImmuneLoop` passes significant drift into the trainer as `retrain_pending`.
- ✅ **Promotion policy shipped and wired into Judge** (`marketimmune/models/promotion.py`, `marketimmune/agentic/judge.py` + 100%-cov tests): `PromotionPolicy.evaluate(champion, challenger)` scores markout-lift / PR-AUC / calibration / latency / no-leakage and returns promote / needs_more_data / reject — and **never promotes a model that isn't leakage-safe**. `BenchmarkJudge` now delegates to it when both incumbent and candidate expose v2 metrics, while preserving the legacy five-vote fallback for old reports.
- ✅ **Leakage invariant shipped and wired into the Hyperliquid feature join** (`marketimmune/labels/leakage.py`, `marketimmune/features/hyperliquid_features.py` + 100%-cov tests): `assert_as_of(feature_ts, fill_ts)` raises `LeakageError` when any feature postdates the fill (`max(feature_ts) ≤ fill_ts`). The join selects latest-prior L2/context features for training rows and fails loudly on future feature rows.
- ✅ **CI workflow expanded** (`.github/workflows/ci.yml`): CI now installs dashboard requirements, runs Django checks/migration dry-run, installs the frontend with `npm ci`, and runs frontend typecheck/build in addition to backend lint/type/test/coverage/metrics.

Phase 3 hardening is complete as standalone, tested components. Real requester-pays SOL backfills, a true held-out CatBoost report, and a Judge promotion over the event-OFI incumbent now exist locally. The promoted CatBoost artifact is exposed through the Django API and Models page as a real artifact-health/readout surface. Gold fill scores now flow through Sentinel, Investigator, Loop, and Policy as first-class evidence, and persisted scored-fill rows link back to the loop/case/policy action that consumed them. What remains is broader real-data scale-out and automation around refreshing new Gold partitions or a live fill stream.

### Gate status (latest local run)
- ✅ **pytest + coverage: 623 passed; 100% line and branch coverage** (`4649` statements, `930` branches, `0` missing, `0` partial).
- ✅ **mypy: clean** (`95` source files). ✅ **ruff: clean**.
- ✅ **Django checks clean:** `python manage.py check` → no issues; `python manage.py makemigrations --check --dry-run` → no changes detected.
- ✅ **Frontend checks clean:** `npm.cmd run typecheck` and `npm.cmd run build` pass (`npm.cmd` avoids the local PowerShell `npm.ps1` execution-policy block).
- ✅ **CI guard scripts clean:** `python scripts/check_line_limit.py` and `python scripts/phase_metrics.py` pass. The latest Vite build was synced into `dashboard/static/agentic/`.
- ✅ **Live Hyperliquid dashboard smoke:** Django `/api/hyperliquid/live/` returned real BTC-PERP mid/spread/depth (20 bids / 20 asks) and `/api/hyperliquid/candles/` returned 241 one-minute candles. The Django-served SPA at `http://127.0.0.1:8000/dashboard/live/#/live` hydrates with live data, no static-preview warning, no partial-load banner, and no simulator price fallback.
- ✅ **Free Hyperliquid replay seed + DeepSeek loop smoke:** `python scripts/seed_hyperliquid_replay_lake.py --coin BTC --symbol BTCUSDT --lookback-minutes 120 --rows 90 --timeout-s 10` called the public Info API and wrote 90 BTC candles, 40 L2 levels, and 230 asset contexts (`date=2026-06-20`; 31 cross-day candles dropped for alignment). Then `MARKETIMMUNE_USE_LLM=1 python manage.py run_immune_loop --difficulty hard --limit 12` persisted `loop_360eee9d14a7`: `posture=block_simulated_agent`, 5 alerts, 5 cases, `proposal_source=llm`, `case_source=llm`, and 20 stored tool calls.
- ✅ **Replay-seed regression slice:** `pytest tests/ingest/test_hyperliquid_replay_seed.py tests/ingest/test_hyperliquid_api.py tests/ingest/test_hyperliquid_lake.py tests/agentic/test_loop.py` → 32 passed; `python -m mypy marketimmune` clean; `ruff` clean on touched files; `python manage.py check` clean; `python scripts/check_line_limit.py` clean.
- ✅ **Requester-pays one-hour archive smoke:** `python scripts/backfill_hyperliquid_day.py --coin SOL --date 20230916 --hour 9 --lake-root data/hyperliquid` succeeded after schema confirmation: `book_snapshots=5568`, `asset_contexts=72000`, `fills=0`, `gold_rows=0`, `training_rows=0`, wrote `data/hyperliquid/silver/hyperliquid/l2_book/SOL/SOL-20230916.parquet` and `data/hyperliquid/silver/hyperliquid/asset_ctxs/asset-ctxs-20230916.parquet`. Fills remain zero until a real `node_fills_by_block` suffix is listed/confirmed.
- ✅ **Requester-pays Bronze→Gold one-hour smoke:** `python scripts/backfill_hyperliquid_day.py --coin SOL --date 20250727 --hour 8 --fill-suffix hourly/20250727/8.lz4 --lake-root data/hyperliquid` succeeded end-to-end: `book_snapshots=5675`, `asset_contexts=287430`, `fills=474`, `gold_rows=474`, `training_rows=474`, writing Bronze fills, Silver fills/L2/context, Gold markout, and Gold training parquet. First verified Gold row includes `markout_bps_1s=-3.48`, `markout_bps_10s=-5.88`, `markout_bps_60s=-6.69`, all toxic flags true, and point-in-time joined L2/context features.
- ✅ **Bronze→Gold rerun after timestamp fix:** same SOL hour rewrote Silver/Gold with timestamped asset contexts; verified sample asset row has `ts_ms=1753574400000`, first training row has `feature_ts_ms=1753606325317.0 <= fill ts_ms=1753606325380`, so the joined features remain as-of.
- ✅ **Backfill CLI progress smoke:** `python scripts/backfill_hyperliquid_day.py --coin SOL --date 20250727 --hour 8 --fill-hour 8 --lake-root data/hyperliquid --no-resilience` succeeded with visible object progress and the same Bronze→Gold counts (`fills=474`, `training_rows=474`).
- ✅ **Full-day SOL requester-pays backfill:** `python scripts/backfill_hyperliquid_day.py --coin SOL --date 20260601 --hour 0-23 --fill-hour 0-23 --lake-root data/hyperliquid` completed with `book_snapshots=155875`, `asset_contexts=331200`, `fills=210598`, `gold_rows=210592`, `training_rows=210548`, and 6 parquet writes. The model-ready Gold table is `data/hyperliquid/gold/hyperliquid/training/SOL/SOL-training-20260601.parquet`.
- ✅ **Additional SOL requester-pays backfills:** local Gold training partitions now exist for `20260527`, `20260528`, `20260529`, `20260530`, `20260531`, and `20260601`. The attached `20260527` run completed with `book_snapshots=156847`, `asset_contexts=331200`, `fills=191744`, `gold_rows=191740`, and `training_rows=191648`; the attached `20260531` run completed with `book_snapshots=157343`, `asset_contexts=331200`, `fills=100958`, `gold_rows=100958`, and `training_rows=100896`. `20260602` and `20260603` failed because `s3://hyperliquid-archive/market_data/<date>/0/l2Book/SOL.lz4` is absent; S3 listing returned `KeyCount=0` for those prefixes, so do not retry those exact objects.
- ✅ **Real calibrated CatBoost auto-policy panel run:** `python scripts/train_hyperliquid_markout.py --coin SOL --dates 20260528..20260601 --horizon 10s --iterations 150 --n-splits 5 --report reports/hyperliquid_markout_SOL_20260528_20260601_auto_policy.json --model-out data/models/hyperliquid_catboost_SOL_20260528_20260601_10s_auto_policy.cbm` completed on 743,046 usable rows with calibrated `PR-AUC=0.547`, `Brier=0.225`, `ECE=0.033`, `quote_rate=0.216`, `markout_lift_bps=0.822`, and `latency_p95_ms=0.828`. The equally tuned event-OFI baseline reached `markout_lift_bps=0.708`, so the candidate is now `+0.114 bps` versus baseline and `+0.087` PR-AUC. The deployment threshold selected from the grid was `0.330`; fold-local candidate thresholds were `0.32-0.33`.
- ✅ **True held-out CatBoost report:** `python scripts/train_hyperliquid_markout.py --coin SOL --dates 20260527..20260531 --holdout-date 20260601 --horizon 10s --iterations 150 --n-splits 5 --report reports/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json --model-out data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.cbm` trained on 724,150 rows and evaluated the frozen model on 210,530 unseen `20260601` rows. Train CV: `PR-AUC=0.553`, `Brier=0.222`, `markout_lift_bps=0.854`, `baseline_delta=+0.138 bps`. Holdout: `PR-AUC=0.556`, `Brier=0.233`, `ECE=0.027`, `quote_rate=0.246`, `markout_lift_bps=0.860`, `baseline_delta=+0.109 bps` versus event OFI. Artifacts: `reports/hyperliquid_markout_SOL_20260527_20260531_holdout_20260601.json`, `data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.cbm`, and `data/models/hyperliquid_catboost_SOL_20260527_20260531_holdout_20260601_10s.isotonic.json`.
- ✅ **Explicit event-OFI incumbent + Judge promotion:** wrote `reports/incumbents/event_ofi_SOL_20260527_20260531_holdout_20260601.json` from the report's event-OFI baseline block and ran `BenchmarkJudgeAgent` against it. Verdict: `promote`, `7/7` criteria passed: markout lift, PR-AUC, Brier calibration, latency, no leakage, CV baseline delta (`+0.138 bps`), and holdout baseline delta (`+0.109 bps`).
- ✅ **Promoted CatBoost artifact surfaced in the app:** added `marketimmune/models/hyperliquid_markout_scorer.py` to load the `.cbm`, apply the exported isotonic calibrator, preserve feature-order validation, and emit an explicit `quote` / `withhold_quote` decision. Django now exposes `/api/markout-model/health/` from settings-backed artifact paths, and the React Models page hydrates a real promoted-artifact panel with holdout PR-AUC, Brier, markout lift, baseline delta, decision threshold, artifact path, and smoke latency. Real smoke: `available=true`, holdout `PR-AUC=0.556`, holdout `markout_lift_bps=0.860`, smoke action `withhold_quote`, p95 smoke latency ~`0.9 ms` on the local artifact.
- ✅ **Promoted CatBoost Gold-fill evidence wired into the loop:** added a shared deploy-time Hyperliquid feature contract, `GoldFillScore` scoring helpers for local Gold training parquet rows, Sentinel support for promoted-model fill alerts, Investigator direct case construction when no replay tick exists, and `ImmuneLoop.run(..., gold_fill_scores=...)` so scored real fills can reach Policy without being dropped by replay-only lookup logic.
- ✅ **Promoted fill decisions persisted, exposed, linked, and historized:** added `ScoredFillDecision`, `ScoredFillDecisionLink`, and migrations `0006`-`0009`, a `/api/markout-model/decisions/` endpoint with auto/forced refresh, settings-backed Gold parquet path and refresh limits, and a Models-screen table for recent persisted promoted-model decisions. `AgenticService.run_once(...)` now refreshes recent promoted fill scores, passes them into the immune loop, persists loop-scoped cases/policy decisions without duplicate-ID collisions, links each consumed fill row back to the latest loop/case/policy action, and writes a durable history edge per fill/loop/case. Local smoke on `SOL-training-20260601.parquet` persisted 5 latest SOL Gold fills, ran `loop_99416c05bcef`, linked 5/5 current fill rows, and wrote 5 history links with `critical_alert` policy actions. The endpoint returned `200` with `loop_id`, `case_id`, `policy_decision_id`, and `recommended_action`.
- ✅ **Promoted-fill refresh status and Gold auto-discovery shipped:** added `ScoredFillRefreshRun` plus migration `0010`, latest-partition discovery under the configured Gold directory/root, source-change auto-refresh, and a `latest_refresh` payload surfaced in the Models page. Forced API smoke: `/api/markout-model/decisions/?limit=5&refresh=force` scored 5 fills from `data\hyperliquid\gold\hyperliquid\training\SOL\SOL-training-20260601.parquet`, wrote one `api` refresh run, returned `status=succeeded`, `refreshed_count=5`, and `duration_ms~2676`. Loop smoke then ran `loop_1b42b6ccfc07`, wrote one `loop` refresh run, linked 5/5 fills, and added 5 history links.
- ✅ **Requester-pays backfill job orchestration shipped:** added `HyperliquidBackfillJob` plus migration `0011`, a persisted `run_hyperliquid_backfill` management command, a read-only `/api/hyperliquid/backfill-jobs/` status endpoint, and a Models-screen backfill job table. The command supports explicit `--dry-run` planned jobs with no S3 fetches and real requester-pays runs that write Bronze/Silver/Gold, then optionally trigger promoted-fill refresh. Safe dry-run smoke: `python manage.py run_hyperliquid_backfill --coin SOL --date 20260601 --hour 0-1 --fill-hour 0-1 --dry-run --trigger scheduled` wrote `hl_backfill_e9a406c68cd6` with `status=planned`, generated fill suffixes `hourly/20260601/0.lz4` and `hourly/20260601/1.lz4`, and the API returned the planned job with `dry_run=true` and message `Dry run; no S3 objects fetched.`.
- ✅ **Earlier agentic trainer→Judge real-data smoke:** `ModelTrainerAgent(training_mode="hyperliquid_markout", HyperliquidTrainingSpec(SOL, dates=(20260528..20260601), 10s))` produced `reports/candidates/train_821a29a318-SOL-20260528-20260529-20260530-20260531-20260601-10s.json`, `data/models/candidates/train_821a29a318-SOL-10s.cbm`, and `data/models/candidates/train_821a29a318-SOL-10s.isotonic.json` with `markout_lift_bps=0.822`, `baseline_delta=+0.114 bps`. This is superseded by the held-out run above.
- ✅ **Trainer/OFI/calibration/panel/promoted-model regression slice:** holdout evaluator, holdout CLI wiring, agentic holdout command fields, Judge holdout-baseline gates, promoted artifact loader, dashboard health payload, Gold-fill agentic evidence path, fill-decision persistence/API/UI, latest-loop linkage, historical fill/loop link rows, refresh-run status, Gold partition auto-discovery, and persisted backfill job orchestration are tested. Full local gate passes: `python -m coverage run -m pytest` (`623 passed`), `python -m coverage report` (`100%`), `ruff check dashboard marketimmune tests`, `python -m mypy marketimmune`, `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `npm run typecheck`, and `npm run build`.
- ✅ **Hyperliquid parser/feature edge slice:** added coverage for timestamp-less L2 rows, asset-context custom headers and timestamp variants, replay-seed invalid inputs, empty replay artifacts, and non-fill node-data block metadata; focused slice passes (`48 passed`).

---

## 10. What's left (next steps)

**A. Real-data scale-up — needs your machine (network / storage / cost).** A stronger local SOL result now exists end-to-end: requester-pays Bronze/Silver/Gold, point-in-time training rows with event OFI, CatBoost, fold-local isotonic calibration, fold-local policy-threshold selection, purged/embargoed CV, a true held-out day, and Judge promotion over an explicit event-OFI incumbent. Latest held-out result: train `20260527..20260531`, hold out `20260601`, `PR-AUC=0.556`, `Brier=0.233`, `markout_lift_bps=0.860`, `+0.109 bps` versus event OFI on 210,530 unseen rows. This is a real local checkpoint; broaden to more dates/coins before making it a durable résumé claim. `20260602` and `20260603` are absent at the expected archive L2 prefix; choose other available dates instead of retrying those objects.

**B. Integration - real-data operations.** Real-data ingestion now produces model-ready Gold training rows with `assert_as_of`; the CatBoost trainer writes a real report/model artifact; `BenchmarkJudge` -> `PromotionPolicy`, markout evaluation, DeepSeek resilience, Memory/Loop drift triggering, CI gates, the promoted artifact health/readout endpoint, the promoted-model Sentinel/Policy path, persisted scored-fill API/UI, latest loop linkage, historical fill/loop/case links, source-change auto-refresh, operator-visible refresh status, and persisted requester-pays backfill jobs are wired. Remaining integration is a real live fill-stream adapter or an external scheduler invoking `run_hyperliquid_backfill` on chosen coin/date ranges, then multi-coin/multi-day scale-up.

**C. Deferred Phase 1 behavioral refactors (need the test loop).** Unify the feature pipeline (train via `feature_store`, §2.3), consolidate the two scenario layers (§2.1), collapse the two replay engines (§2.2).

**D. Honesty upkeep.** Keep `README.md` / `RESUME_BULLETS.md` in sync; switch to the *target* résumé bullets only once **A** lands.
- ⏳ **Hyperliquid ingestion (next — needs your machine: network + storage):**
  - **Archive (batch / Bronze):** `s3://hyperliquid-archive/market_data/<YYYYMMDD>/<hour>/l2Book/<COIN>.lz4` (L2 book snapshots) and `s3://hyperliquid-archive/asset_ctxs/<YYYYMMDD>.csv.lz4` (funding / open-interest / oracle / mark). `.lz4`-compressed, **requester-pays** (`--request-payer requester`). No candles/spot via S3.
  - **Fills (markout labels + liquidation intensity):** parser + parquet writers + explicit-suffix daily coordinator exist for documented fill records and tolerant block envelopes; confirm real object partition/fields in `s3://hl-mainnet-node-data/node_fills_by_block` (newer) or `node_fills` / `node_trades` (older).
  - **Adapter:** add the real requester-pays listing/runner that feeds confirmed object keys into `HyperliquidDailyBackfill`, then exposes the resulting repos to the rest of the app. Register `hyperliquid` in `adapters/factory.py` **only once the repos exist** (no empty seam).
  - **Feature → source map:** L2 book → mid, spread, microprice, imbalance, event OFI, and rolling OFI now; extend to depth/slope next. `asset_ctxs` → basis now; extend to funding RoC / OI delta once real timestamped rows are confirmed. Fills → markout labels now; liquidation intensity still needs real archive fields.
  - Then: scale the CatBoost run beyond the current SOL panel and report **measured markout lift in bps** vs. true event-level OFI.

### How to verify locally
```bash
ruff check .
mypy
python -m coverage run -m pytest
python -m coverage report -m                  # backend gate (100% coverage)
python scripts/fetch_hyperliquid_api_sample.py --coin BTC --interval 1m --lookback-minutes 60
python scripts/seed_hyperliquid_replay_lake.py --coin BTC --symbol BTCUSDT --lookback-minutes 120 --rows 90
cd frontend && npm run typecheck && npm run build
pip install -r dashboard/requirements.txt
python manage.py check                          # before/after any models change
python manage.py makemigrations --check --dry-run
```
For this Windows sandbox, pytest needed workspace-local temp paths (`TMP`/`TEMP` plus
`--basetemp`) because the default user temp folder was not writable.
