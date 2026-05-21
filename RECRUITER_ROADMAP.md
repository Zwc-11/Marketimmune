# MarketImmune — Recruiter-ready Roadmap

This document is the strategic plan for turning **MarketImmune** into a
portfolio project that lands AI / ML / data-science internships at
top-tier firms (HRT, Two Sigma, Citadel, Stripe, Anthropic, Meta, etc.).

It assumes the codebase you are looking at right now: a Django dashboard
+ Django REST API + a `marketimmune.simulator` engine + a parquet lake
of real Binance USD-M data. Items are ranked by **impact per hour of
effort**, not by difficulty.

---

## 0. What recruiters actually look for

A great fintech / quant / ML portfolio project demonstrates **five
things**:

| Signal | What it looks like here |
|---|---|
| **Real data** | Binance kline + bookDepth parquet, not toy CSVs. ✅ |
| **A non-trivial ML problem with metrics** | "Detect manipulative agent behaviour" with PR-AUC / lead-time / latency. ⚠️ partly. |
| **Clean code architecture** | Strategy / Repository / Service layers, type hints, tests. ✅ baseline now. |
| **Reproducibility** | One-command setup, deterministic replay, seeded data. ✅ via `prepare_simulator`. |
| **A demo a recruiter can open in 30 seconds** | `/simulator/` cockpit with visible "what's real vs simulated" provenance. ✅ |

If you nail items 1–5, you're already ahead of 80% of CS undergrads.
The rest of this doc is what closes the remaining 20%.

---

## 1. Architecture you now have (and how it's organised)

```
marketimmune/                       # Pure-Python ML/quant core (no Django).
  simulator/
    __init__.py                     # Public API surface.
    config.py                       # Frozen value objects (ReplayConfig).
    data_loader.py                  # Repository pattern (parquet I/O + cache).
    pricing.py                      # Pure helpers (derived spread, mid).
    scenarios.py                    # Strategy + Factory (agent behaviours).
    replay_builder.py               # Service that orchestrates one replay.
  policy/rules.py                   # Existing RuleEngine baseline.
  models/, features/, lake/, ...    # Existing benchmark modules.

dashboard/                          # Django app (presentation + persistence).
  services/
    simulator_service.py            # Facade that views call; assembles DTOs.
  management/commands/
    start_replay.py                 # Thin CLI shell over ReplayBuilder.
    prepare_simulator.py            # Idempotent warm-up of a default session.
  views.py                          # HTTP endpoints (no logic).
  models.py                         # ORM only.
  templates/dashboard/              # Cockpit + sub-pages.
```

Design patterns currently in play:

- **Strategy** — `AgentScenario` ABC with one subclass per scenario.
- **Factory / Registry** — `ScenarioRegistry.register` lets you drop a
  new strategy in without touching the engine, the API, or the UI.
- **Repository** — `KlineRepository`, `DepthRepository` hide parquet.
- **Service** — `ReplayBuilder` (engine) and `SimulatorService` (app).
- **Value Object** — `ReplayConfig`, `ReplayPlan`, `ReplayTick`,
  `DerivedQuote`, `KlineRecord`, `DepthSnapshot` — frozen dataclasses
  with `slots=True`.
- **DTO** — `SimulatorService.snapshot()` returns the cockpit payload.

You can talk about all of these in an interview by name.

---

## 2. Top 10 upgrades, in priority order

### P0 — Within 1 day, dramatically raises perceived rigor

1. **Replace RuleEngine with a real ML model** as the primary risk head. ✅ **Done.**
   - `marketimmune/models/risk_head.py` — gradient-boosting `RiskScorer`
     with `train` / `predict` / `save` / `load`.
   - Persisted artifact at `data/models/risk_head.joblib`; loaded
     automatically by `ReplayBuilder.from_lake(..., model_path=...)`.
   - `ModelPrediction.model_name` now flips to
     `GradientBoostingRiskHead-v1` whenever the artifact exists; falls
     back to `RuleEngine` cleanly when it doesn't.
   - Each prediction also reports its top-3 contributing features
     inline in the cockpit's audit panel.

2. **Add a held-out benchmark report.** ✅ **Done.**
   - `scripts/train_risk_head.py` → writes
     `reports/risk_head_benchmark.json` with PR-AUC, ROC-AUC, F1,
     accuracy, precision@50, train/test sizes, feature importances,
     and live latency (p50/p95/p99).
   - The Risk page reads the JSON and renders headline KPI cards plus
     a feature-importance bar chart.

3. **Inference latency display.** ✅ **Done.**
   - `GET /api/risk-head/health/?samples=500` measures p50/p95/p99
     against the live artifact and returns JSON.
   - `dashboard/templates/dashboard/simulator_risk.html` fetches it
     on page load and replaces the previously hard-coded number.

### P1 — Within 1 week, opens senior-grade conversations

4. **Real-time event-time feature extractor.**
   - Right now, scenario features are constants per scenario. Build a
     real `OnlineFeatureExtractor` that consumes a stream of
     `(order, trade, cancel)` events and produces 1s / 5s / 60s
     rolling window features. Reuse it for both training and
     `/simulator/`.
   - This is the difference between "I built a demo" and "I built the
     ML feature pipeline."

5. **Marked Temporal Point Process (MTPP) risk head.**
   - Implement a small GRU- or transformer-based MTPP that predicts
     P(next 10s contains a manipulative event). This is what the
     dashboard already claims you have under "GRU-MTPP" /
     "Order-S2P2"; ship at least one of them for real.
   - Compare against the gradient-boosting baseline in your benchmark
     report.

6. **Explainability tab using SHAP.**
   - For each prediction in the cockpit, surface the top-3 SHAP
     contributions in the audit panel. Use `shap.TreeExplainer` for the
     boosting model. This is a hugely impressive signal at intern
     level.

### P2 — When you have a weekend free

7. **WebSocket live replay** (replace polling with a Django Channels
   WebSocket that streams ticks at the chosen speed). Same DTO, but
   feels like a real terminal.

8. **Multi-symbol support.** Right now everything is BTCUSDT. Add
   ETHUSDT in the lake, surface a symbol picker in the cockpit, and
   prove that the entire pipeline is symbol-agnostic.

9. **Out-of-distribution detection.** A simple Mahalanobis-distance
   detector on the feature embedding. The benchmark already has an
   `ood_detection` task; ship a measurable number.

10. **Adversarial robustness experiments.** Inject perturbed scenarios
    and measure how much risk-score drops. Write a one-page report.

---

## 3. Things to delete or fix before showing the project

- `dashboard/test_simulator.py` references `/simulator/api/state/` (the
  real URL is `/api/simulator/state/`) and passes a `str` to a
  `JSONField`. Either delete or fix; broken tests in the repo are a
  red flag for reviewers.
- `dashboard/views.py` still has many `DemoXxxView` classes that
  predate the simulator. If you keep them, demote them to a
  `legacy/` subpackage; if not, delete them.
- `DASHBOARD_SUMMARY.md` and `DASHBOARD_QUICK_START.md` predate this
  refactor and may overclaim capabilities. Audit them.
- `LICENSE` is missing — add MIT or Apache-2.0. Recruiters check.

---

## 4. README rewrite (the single highest-ROI change you can make)

Your `README.md` is the first thing a recruiter sees. It must answer:

1. **What is it?** (one sentence, no jargon)
2. **Why is it interesting?** (real data + non-trivial ML problem)
3. **What does it look like?** (animated screenshot of `/simulator/`)
4. **What did *you* build vs reuse?** (be explicit; this matters
   enormously when your repo uses public datasets)
5. **What are the headline numbers?** (PR-AUC, latency, lead time)
6. **How do I run it?** (one paragraph max)
7. **What's the architecture?** (link to this doc)

Drop a `docs/architecture.svg` produced from the diagram in section 1
of this file. Recruiters love a system diagram.

---

## 5. Interview talking points (memorise three)

You can credibly say all of these today:

> *"I built a deterministic replay of a real Binance order book on top
> of the published USD-M parquet lake, layered six configurable agent
> scenarios on top using a Strategy / Registry pattern, and ran a rule
> engine that emits PR-AUC-measurable risk scores per minute. The whole
> data path is honest about which numbers come from the parquet (klines
> + aggregated depth) and which are simulated overlays."*

> *"The most interesting code is the separation between
> `marketimmune.simulator` — pure Python with no Django dependency, so
> the same engine can run in a notebook or a backtest — and the
> `dashboard.services` layer that maps `ReplayPlan` value objects onto
> the Django ORM in one transaction."*

> *"My next step is to replace the rule engine with a gradient boosting
> head trained on the same features, ship a held-out benchmark with
> PR-AUC and average lead-time numbers, and add SHAP-based
> explainability per prediction."*

That is enough to handle 30 minutes of conversation.

---

## 6. What this project still **shouldn't** claim

To stay honest (recruiters read code):

- We do **not** have a real L1 order book; only aggregated %-from-mid
  depth bands. The cockpit labels this as "±1% band spread" — do **not**
  call it "Level 1 spread" anywhere.
- We do **not** have per-trade aggressor side data, so the CVD panel is
  labelled "signed-volume CVD proxy", not "CVD".
- The GRU-MTPP / S2P2 numbers on the Benchmark page are currently
  populated from `demo_data.py` seeds, not from real training. Either
  train and replace, or relabel as "target metrics".

The reason you maintain this discipline is simple: a recruiter who
finds *one* lie in your project will mistrust every other claim. A
recruiter who finds your code being scrupulously honest about
provenance will trust everything.

---

*Last updated: refactor introducing `marketimmune/simulator/`,
`dashboard/services/`, and the `prepare_simulator` command.*
