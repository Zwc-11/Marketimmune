# MarketImmune architecture

MarketImmune predicts which SOL perp fills a market maker will regret 10 seconds
later. There are two paths: an **offline research path** that turns Hyperliquid
archives into a validated CatBoost model, and a **live path** that labels (and,
with an exported model, scores) every SOL-PERP fill as it prints.

```mermaid
flowchart LR
    subgraph offline["Offline research path (Python)"]
        S3["Hyperliquid S3 archive<br/>(requester pays)<br/>node fills, l2Book, asset ctxs"]
        BR["Bronze / Silver parquet<br/>marketimmune/ingest/*"]
        GOLD["Gold labels<br/>maker markout at t+10s<br/>regret = markout < -1 bps"]
        FEAT["Point-in-time features<br/>OFI 1s/5s/10s, microprice, spread,<br/>imbalance, basis, funding, OI"]
        CV["Temporal CV<br/>walk_forward (default) or purged_kfold<br/>60s purge + embargo"]
        CB["CatBoost + fold-local isotonic<br/>threshold chosen on OOF only"]
        HO["Forward holdout day<br/>vs 10s event-OFI baseline"]
        REP["docs/benchmarks/*.json<br/>committed report"]
        EXP["export_markout_web_model<br/>compact oblivious-tree JSON"]
        S3 --> BR --> GOLD --> FEAT --> CV --> CB --> HO --> REP
        CB --> EXP
    end

    subgraph live["Live path (browser, no backend needed)"]
        WS["Hyperliquid WebSocket<br/>l2Book, trades, activeAssetCtx, candle"]
        FEED["MarketFeed<br/>one snapshot per animation frame"]
        OFI["Streaming OFI<br/>bounded 10s window"]
        SCORE["Oblivious-tree evaluator<br/>+ isotonic, as-of book"]
        CLOCK["Regret clock<br/>resolve at first mid ≥ t+10s"]
        UI["Terminal UI<br/>book, tape, regret matrix, quote guard"]
        WS --> FEED --> OFI --> SCORE --> UI
        FEED --> CLOCK --> UI
    end

    subgraph api["Optional Django API"]
        DJ["/api/markout-model/*<br/>/api/agentic/*<br/>/api/hyperliquid/backfill-jobs/"]
        LOOP["Immune loop agents<br/>red team, sentinel, investigator,<br/>policy, memory, trainer, judge"]
        AUD["Append-only audit trail<br/>AgentRun, ToolCall, DecisionTrace"]
        LOOP --> AUD --> DJ
    end

    EXP -. "frontend/public/model/markout.json" .-> SCORE
    REP -. "bundled at build time" .-> UI
    DJ -. "loop state, model health,<br/>scored Gold fills" .-> UI
```

## Label

For a maker fill at time `t`, price `p`, maker side `s` (+1 the maker bought,
-1 it sold):

```
markout_bps = s * (mid_{t+10s} - p) / p * 10_000      # first mid at or after t+10s
regretted   = markout_bps < -1.0                        # 1 bps fee hurdle
```

`marketimmune/labels/markout.py` is the definition; `marketimmune/ingest/hyperliquid_gold.py`
applies it to a day of fills with one `searchsorted` per horizon, and
`frontend/src/lib/regret.ts` applies the same rule to live fills.

## Validation

`marketimmune/models/walk_forward.py` implements both schemes on index arrays:

- `walk_forward` (default for new runs): `n_splits + 1` time blocks, fold `k` tests
  block `k + 1` and trains only on rows before `test_start - purge`.
- `purged_kfold`: `n_splits` blocks, train on everything outside
  `[test_start - purge, test_end + embargo]`. The committed SOL report was produced
  this way; four of its five folds train on later days. Its headline number is the
  forward holdout (train May 27 to 31, score June 1), which is out of time.

The skip threshold is selected per fold from that fold's training-side out-of-fold
predictions, and the deployment threshold from all training out-of-fold rows; the
holdout day never influences either.

## Components

| Path | Role |
|---|---|
| `marketimmune/ingest/` | Hyperliquid archive parsers, lake writers, Gold labels |
| `marketimmune/features/hyperliquid_features.py` | Vectorized OFI windows and the as-of feature join |
| `marketimmune/models/` | Temporal splits, evaluation, calibration, scorer, oblivious-tree evaluator |
| `marketimmune/agentic/` | Immune-loop agents with structured traces |
| `scripts/train_hyperliquid_markout.py` | Trainer CLI; writes the report, model, calibrator |
| `scripts/export_markout_web_model.py` | Compact model JSON for the browser and CatBoost-free serving |
| `scripts/bench_pipeline.py` | Stage timings on a panel shaped like the SOL run |
| `dashboard/` | Django API, persistence, audit trail, serves the built SPA |
| `frontend/` | React + TypeScript + Vite terminal |

Python core code has no Django dependency. Django owns persistence and HTTP.

## Guardrails

MarketImmune sends no orders, holds no keys, and does not identify private
actors. Threat scope and non-goals are in [docs/threat_model.md](docs/threat_model.md).
Any new benchmark number must link to a committed artifact.
