# MarketImmune Core V1

MarketImmune is a working AI market-safety benchmark and demo platform for identifying harmful
or unsafe autonomous trading-agent behavior in crypto exchange microstructure.

The project combines:

- Real Binance USD-M Futures public market background data.
- Synthetic, labeled agent order-lifecycle events for controlled evaluation.
- Deterministic replay and scenario generation.
- Feature extraction and rule-based safety baselines.
- A benchmark suite and temporal-model baselines for early-warning and harm estimation tasks.

It does not perform live trading, identify private users/accounts, or claim alpha/prediction
edge for deployment.

## What We Accomplished

This repository now contains implemented and validated work through phases 1-9.

- Phase 1-3 foundation: package quality gates, schemas, event IDs, Parquet/lake/manifests, and CI.
- Phase 4 replay engine: deterministic, invariant-checked replay with generated replay reports.
- Phase 5 scenario and labeling system: benign and risky agent families, deterministic synthetic scenarios,
  and label/manifests.
- Phase 6 feature and policy baseline: multi-window feature store and RuleEngine baseline reports.
- Phase 7 AegisBench v0: train/validation/test splits, task metrics, JSON/Markdown reports, and leaderboard CSV.
- Phase 8 Order-MTPP baseline: variable-length temporal model pipeline with benchmarked latency and quality.
- Phase 9 Order-S2P2 baseline: neural Hawkes (CT-LSTM style) implementation with OOD metrics and comparison artifacts.

## Current Evidence And Reports

Project proof and metrics are included in the repository:

- `reports/phase_1_3_proof.md`
- `reports/phase4_6_proof.md`
- `reports/phase7_9_proof.md`
- `reports/phase4_6_metrics.json`
- `reports/phase7_9_metrics.json`
- Phase outputs under `reports/phase4` through `reports/phase9`

## Quickstart

```powershell
python -m pip install -e ".[dev]"
.\make.ps1 ci
```

On systems with GNU Make:

```bash
make install
make ci
```

Additional phase runners:

```powershell
.\make.ps1 phase46
.\make.ps1 phase79
```

## Demo Website

Run the demo-first dashboard:

```bash
python manage.py migrate
python manage.py load_metrics
python manage.py runserver
```

Open:

- `http://127.0.0.1:8000/demo/` for the plain-English project homepage.
- `http://127.0.0.1:8000/dashboard/live/` for simulated trades, live ML risk predictions, alerts, and reasoning traces.
- `http://127.0.0.1:8000/dashboard/data/` for stored market events, synthetic agent events, features, predictions, and alerts.
- `http://127.0.0.1:8000/dashboard/model/` for the active model, latest prediction, feature importance, and artifact path.
- `http://127.0.0.1:8000/dashboard/alerts/` for stored risk alerts and linked predictions.
- `http://127.0.0.1:8000/dashboard/training/` for model training history and artifact paths.
- `http://127.0.0.1:8000/dashboard/agents/` for structured agent reasoning traces.
- `http://127.0.0.1:8000/dashboard/benchmark/` for phase 7-9 benchmark metrics and leaderboard.

Optional background simulator:

```bash
python manage.py run_live_demo
```

The live page also writes one fresh simulated row set every second while it is open.

## Demo Tour

Screenshot placeholders to capture before sharing:

1. Homepage: `/demo/`
   - Placeholder: `docs/screenshots/homepage.png`
   - Shows the product headline, provenance labels, Simulate/Detect/Explain cards, and product diagram.
2. Live cockpit: `/dashboard/live/`
   - Placeholder: `docs/screenshots/live-cockpit.png`
   - Shows simulated live stream, scenario name, market regime, event ID, prediction ID, risk gauge, trade feed, alert stream, and decision audit trail.
3. Data storage page: `/dashboard/data/`
   - Placeholder: `docs/screenshots/data-storage.png`
   - Shows local SQLite row counts, latest inserted timestamp, and tabbed stored rows.
4. Training/model page: `/dashboard/training/` and `/dashboard/model/`
   - Placeholder: `docs/screenshots/training-model.png`
   - Shows model metrics, training command, dataset source, split method, metric source, artifact timestamp, and report path.
5. Decision audit trail and alerts: `/dashboard/agents/` and `/dashboard/alerts/`
   - Placeholder: `docs/screenshots/audit-alerts.png`
   - Shows observation, feature evidence, model interpretation, policy decision, recommended control, confidence, linked event ID, linked prediction ID, and alert severity.

## Scope Rules

- No API keys are required.
- No real orders are sent.
- Tests use local fixtures and do not require internet.
- Synthetic agent behavior is labeled as synthetic.
- Benchmark and model metrics must be generated from actual outputs, not entered manually.
