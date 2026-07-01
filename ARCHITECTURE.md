# MarketImmune Architecture

MarketImmune is a static-first React/Django research system for adverse-selection
monitoring. The backend code is ordinary Python until persistence or HTTP is
needed; Django owns API hydration, database records, and serving the optional
bundled React build.

```text
Hyperliquid/API ingest
        |
        v
Bronze/Silver parquet lake
        |
        v
Point-in-time feature join
        |
        v
Markout labels
        |
        v
CatBoost markout model
        |
        v
Policy / immune loop
        |
        v
Append-only audit trail
```

## Flow

`[live data]` Free Hyperliquid Info API paths provide current/recent market
context for the dashboard when Django is reachable. Requester-pays archive paths
can backfill local parquet partitions for fills, L2 book snapshots, asset
contexts, Gold markout labels, and model-ready training rows.

`[real-model]` The CatBoost markout training path consumes local Gold training
parquet, applies purged/embargoed walk-forward splits, fold-local isotonic
calibration, event-OFI baseline comparison, and optional held-out evaluation.
The current README metric block is tied to a committed JSON report under
`docs/benchmarks/`.

`[bundled demo data]` The React app can boot without Django from bundled fixtures
and a deterministic simulator. Those paths keep the UI inspectable offline, but
they are preview data and should not be presented as live market evidence.

## Components

`marketimmune/` contains the core agents, policy rules, ingestion, labels, model
evaluation, replay, and resilience code. It does not require Django.

`hindsight/` contains the research backtesting/evaluation layer and canonical
market-data adapters.

`dashboard/` is the Django API, ORM persistence layer, management commands, and
static SPA host. The React bundle is copied into `dashboard/static/agentic/` by
`scripts/sync-django-bundle.mjs` after a Vite build.

`frontend/` is the React + TypeScript + Vite UI. It reads bundled data first,
then hydrates live and persisted slices from Django endpoints when available.

`aegisbench/` is experimental benchmark scaffolding. It remains in the repository
for research tasks but is not the core product narrative.

## Guardrails

MarketImmune does not send orders, hold keys, or identify real private actors.
Threat scope and non-goals are documented in [docs/threat_model.md](docs/threat_model.md)
and [docs/limitations.md](docs/limitations.md). Any new benchmark number should
link to a committed artifact or be marked pending rerun with the exact blocker.
