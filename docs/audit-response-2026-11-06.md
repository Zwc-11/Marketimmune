# Response to the codebase and paper-trading audit of 2026-11-06

The audit reviewed commit `921bbb9` ("Preserve OOF folds and join live asset context as of
fills", 2026-10-30 09:36), a checkout in `OneDrive\桌面\MarketImmune`. On GitHub that commit is
`cf1e17e` (the history was rewritten on 2026-10-30 to fix authorship). Two commits later the
same day changed most of what it reviewed:

- `a98ca90` "Remove the agent-safety stack; slim the Django API into server/" deleted the agent
  loop and judge, AegisBench, the legacy simulator and replay engine, drift monitoring, the
  canonical event schemas, the sequence models and the Django dashboard;
- `e65bc22` "Restructure by pipeline stage" moved the lake, features, labels, models and serving
  code to `marketimmune/{lake,features,labels,models,serving}` and the trainer to `cli/train.py`.

Since then the repository also gained a paper-trading system (`marketimmune/paper`,
`docs/research/paper-trading.md`). Each finding below was checked against the current code. The
ones that still applied are fixed, each with a test of the intended behaviour. Removed code was
not rebuilt. The audit's probe scripts import the old module paths and do not run against this
code.

## Status

| ID | Finding | Status | Where | Test |
|---|---|---|---|---|
| B01 | First row drops later columns from Parquet | Fixed: union of keys, nulls for missing; files published by rename | `lake/tables.py` `write_parquet_records` | `tests/lake/test_tables.py::test_parquet_keeps_columns_that_only_later_rows_have` |
| B02 | Untimestamped dynamic context spread over the day | Fixed: an asset row without `ts_ms` is an error; a fill before the first context gets none | `features/training_rows.py` | `tests/features/test_training_rows.py` (2 tests) |
| B03 | Browser context join compares local and exchange clocks | Fixed: receipt time moved onto the exchange clock with the smallest recent offset plus a 500 ms margin, so the join is late, never early | `frontend/src/market/feed.ts` `score` | `feed.test.ts` "B03" |
| B04 | Overlapping or backward forward holdouts | Fixed: holdout dates must be disjoint and later; holdout rows decided before the last training label could be known (its horizon plus the 30 s label lag) are dropped and counted | `cli/train.py` `check_forward_holdout`, `purge_holdout_gap` | `tests/cli/test_train.py` (2 tests) |
| B05 | Training ignores `feature_ts_ms`; safety asserted | Fixed: every row's `feature_ts_ms < ts_ms` is checked when Gold is read; a partition without the column is not leakage-safe; `--purge-ms` must cover the horizon plus the label lag (default `max(60 s, that)`). `leakage_safe` already came from the per-partition sidecars | `cli/_train_data.py`, `cli/train.py` | `tests/cli/test_train.py` (2 tests) |
| B06 | Candle seed reveals the close at the open | Removed with `ingest/hyperliquid_replay_seed.py` (`a98ca90`). Nothing replays candles; the paper engine replays raw messages | | |
| B07 | Nearest-depth lookup can pick a future book | Removed with `simulator/data_loader.py` (`a98ca90`). Current as-of joins are strictly backward (`training_rows._CoinIndex.latest_before`, `paper.signals.Series.at`) | | |
| B08 | A late trade labelled with the next mid | Fixed: the tracker keeps the mids it has seen and labels a late fill from the first mid at its horizon; with no such mid in hand it has no label | `frontend/src/lib/regret.ts` | `regret.test.ts`, `feed.test.ts` "B08" (2 tests) |
| B09 | Feed gaps: unbounded label lag, stale decisions, silent socket | Fixed offline: `MarkoutConfig.max_mid_lag_s` defaults to 30 s (was unbounded). Fixed live: a label's mid must come within 2 s of its horizon; a score needs a book at most 5 s and a context at most 60 s old; a stalled book stream (15 s) or a missing pong (10 s) closes and reconnects the socket | `labels/markout.py`, `feed.ts`, `regret.ts`, `config.ts` | `tests/lake/test_gold.py`, `feed.test.ts` "B09" (2 tests), `regret.test.ts` |
| B10 | Model for the wrong coin or horizon accepted | Fixed in both scorers. Browser: coin, horizon and feature names must match, and a threshold must exist. Python: calibrator and report must agree on model, coin, horizon and feature columns, must not be marked undeployable, and must give a threshold | `feed.ts` `checkCompatible`, `serving/scorer.py` `load` | `feed.test.ts` "B10", `tests/serving/test_scorer.py` (6 cases) |
| B11 | Invalid model data turns into a quote | Fixed: non-finite inputs or outputs raise in Python (no clamping of NaN to 0); the browser refuses unknown feature columns and leaves a fill with a non-finite feature unscored | `serving/scorer.py`, `frontend/src/lib/features.ts`, `feed.ts` | `tests/serving/test_scorer.py`, `feed.test.ts` "B11", `features.test.ts` |
| B12 | Maker and taker legs as two opportunities | Already one `MatchFill` per `(coin, ts_ms, tid)` (`pair_fill_legs`, with a hard error unless one taker and one maker leg). Added: repeated legs from overlapping sources are dropped and counted in the coin-day's coverage record | `sources/hyperliquid_node_fills.py`, `lake/backfill.py` | `tests/lake/test_tables.py::test_a_leg_seen_twice_is_one_maker_opportunity` |
| B13 | Judge approves NaN and unsafe candidates | Removed with `agentic/judge.py` (`a98ca90`). No promotion path remains; B10 and G05 cover what the server will load | | |
| B14 | Promotion installs the wrong artifact, hides failures | Removed with `dashboard/services/agentic_service.py` (`a98ca90`) | | |
| B15 | Matching engine without order lifecycles | Removed with `replay/` (`a98ca90`). The paper fill model (`paper/orders.py`) keeps orders live until cancelled, with latency on both, queue position from the book, partial fills and trade-through fills | | `tests/paper/test_paper_units.py` |
| B16 | Threshold selection breaks the quote-rate floor | Fixed: no threshold inside the budget means no policy (`None`). A fold quotes everything and says so; the deployment threshold is `None` and the model is not deployable | `models/evaluation.py`, `cli/train.py` | `tests/models/test_evaluation.py` (2 tests) |
| B17 | Block-threshold calibration never blocks | Removed with AegisBench (`a98ca90`) | | |
| B18 | Ties leak labels into PR-AUC | Removed with AegisBench (`a98ca90`). The markout evaluator uses scikit-learn's average precision | | |
| B19 | KS drift wrong with ties | Removed with `monitoring/drift.py` (`a98ca90`) | | |
| B20 | Missing replay date returns another date | Removed with `simulator/data_loader.py` (`a98ca90`). `cli/_train_data.resolve_training_partitions` raises on a missing partition | | |
| B21 | Replay speed floored at the target | Removed with `replay/replay_runner.py` (`a98ca90`) | | |
| B22 | Maker rebates rejected | Removed with `schemas/events.py` (`a98ca90`). `NodeFill.fee` is a signed float; the paper ledger books a negative maker fee as income | | `tests/paper/test_paper_funding.py::test_a_maker_rebate_is_income` |
| B23 | Unsorted input mixes AegisBench features | Removed with AegisBench (`a98ca90`) | | |
| B24 | Five-minute statistics freeze in an outage | Fixed: the window ages with the exchange clock estimated from this machine's, not with the last book | `feed.ts` `refreshStats` | `feed.test.ts` "B24" |
| S01 | Scored fills overwritten across model versions | Fixed: one record per fill and model (the model file's SHA-256 is part of the key), so a later model's score is a new row | `server/api/services/markout_decisions.py` | `tests/server/test_api.py::test_a_new_model_scoring_a_fill_adds_a_record_and_keeps_the_old` |
| S02 | GPU sequence models predict on CPU tensors | Removed with `models/mtpp/` (`a98ca90`) | | |
| S03 | README quickstart lacks Django | Already fixed: the quickstart installs `.[training,server,aws,dev]`; the `server` extra carries Django | `README.md`, `pyproject.toml` | |
| S04 | Development security defaults, anonymous writes | Fixed: hosts default to this machine (`MARKETIMMUNE_ALLOWED_HOSTS`); `DJANGO_DEBUG=0` requires `DJANGO_SECRET_KEY`; a scoring pass (a database write) runs only for requests from this machine or with `X-MarketImmune-Token` | `server/settings.py`, `server/api/views.py` | `tests/server/test_api.py` (2 tests) |
| S05 | Real alerts depend on a synthetic replay | Removed with the agent loop (`a98ca90`) | | |
| S06 | Partial-day reruns overwrite the day | Fixed: each coin-day records the hours it was built from; a run over other hours stops unless `--replace`; files are published by rename | `lake/backfill.py`, `cli/backfill_day.py`, `lake/tables.py` | `tests/lake/test_backfill.py::test_a_rerun_over_other_hours_does_not_silently_replace_the_day` |
| G01 | Decisions must precede fills | The paper engine (`marketimmune/paper`) decides quotes before fills: orders go live a latency after the decision on Hyperliquid's block clock, cancels take the same latency, fills come from later trades and the queue ahead. The terminal's live scores remain a classification of public fills; the UI now says so | `paper/engine.py`, `paper/orders.py`, `frontend/src/components/QuoteGuard.tsx`, `DESIGN.md` | `tests/paper/` |
| G02 | Gross lift needs a ledger | The paper ledger keeps cash, position, fees (signed), position caps and a per-strategy gross budget. Added: hourly funding on held positions (`paper_report --funding`). Not modelled: margin and liquidation (positions are capped well inside them), hedging | `paper/orders.py`, `paper/engine.py`, `paper/funding.py`, `cli/paper_report.py` | `tests/paper/test_paper_funding.py` |
| G03 | A browser session is not infrastructure | The paper runs record every raw message and the engine's ticks, write a decision journal and summaries every minute, carry state across segments and replay exactly | `paper/live.py`, `paper/journal.py` | `tests/paper/test_paper_journal.py` |
| G04 | Final calibrator and threshold never checked together | Fixed: the report's `deployment` block scores the final model, its calibrator and the threshold together on the holdout; the model is deployable only with a threshold, leakage-safe partitions, and a holdout whose quote rate is inside the budget (a model trained without a holdout is not deployable). Scorers refuse undeployable models (B10); the server's health endpoint reports why | `cli/train.py` | `tests/serving/test_scorer.py` |
| G05 | Promotion needs hard gates | No promotion path remains. The hard gates are the deployable flag (G04) and the loader's checks (B10, B11) | | |
| G06 | More independent days and adverse conditions | Addressed by pre-registered runs: the 24-hour confirmation and a 14-day run of the tuned strategies, with gaps excluded and made up (`docs/preregistration/paper-*.md`). The clock-skew finding of 2026-11-06 is one such adverse condition, now corrected live (`--clock coinbase`) | | |

## What changes for existing data

- **Gold labels:** a label whose mid is more than 30 s past its horizon (or whose anchor mid is
  more than 30 s old) is no longer written. `MarkoutConfig(max_mid_lag_s=None)` rebuilds the
  old labels.
- **Training:** a Gold partition without `feature_ts_ms`, or with a row whose features are not
  strictly before the fill, is refused or reported not leakage-safe. Node Gold
  (`cli.build_node_gold`) now writes the true feature time (the last earlier block, or the CEX
  price a latency earlier). Its partitions built before this change need a rebuild before
  retraining.
- **Model reports:** a new `deployment` block. A model without a deployable threshold is not
  loaded by the server or the browser.
- **Server:** requests from another machine read decisions but do not trigger scoring without
  the token.
