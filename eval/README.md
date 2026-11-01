# eval

Benchmarks, each in its own folder with the script that produced it and the
committed result. A number quoted anywhere in the repo links to a file here.

| Folder | What | Rerun |
|---|---|---|
| `markout_sol_10s/` | SOL maker-fill markout model (the deployed v2 model): purged k-fold CV on May 27 to 31, 2026, forward holdout June 1 | Purged k-fold was removed from the trainer (v3 validates with the rolling daily walk-forward only); at commit `8f731c0`, with the local Gold partitions: `python -m marketimmune.cli.train --coin SOL --dates 20260527..20260531 --holdout-date 20260601 --horizon 10s --iterations 150 --n-splits 5 --cv-scheme purged_kfold` |
| `sol_dec_registered/` | The pre-registered SOL December 2025 ladder (`docs/preregistration/sol-dec-2025-ladder.md`) as first run: classifier and quantile reports, rung comparisons, MCS, policies, decomposition, forecaster evaluation. OOF parquet files are gitignored | Code `8f731c0`, Dec 12 excluded; see the pre-registration |
| `sol_dec_corrected/` | The same ladder on the month rebuilt after the 2026-10-31 data fixes (pre-registration, Deviations) | `powershell -ExecutionPolicy Bypass -File .\scripts\run_ladder.ps1 -Coin SOL -Name sol_dec -Out eval\sol_dec_corrected` |
| `ladder_verdicts.json` | H1-H5 verdicts for both SOL runs under the pre-registered rules (`docs/research/sol-dec-2025-ladder-results.md`) | `python -m marketimmune.cli.score_ladder --runs eval/sol_dec_registered,eval/sol_dec_corrected` |
| `eth_dec/` | The confirmatory ETH December 2025 ladder (`docs/preregistration/eth-dec-2025-ladder.md`): the same reports plus `ladder_verdicts.json`; results in `docs/research/eth-dec-2025-ladder-results.md` | `powershell -ExecutionPolicy Bypass -File .\scripts\run_ladder.ps1 -Coin ETH -Name eth_dec` |
| `sim_sol.json` | Block-accurate maker PnL on SOL December: S1, the stale-quote rule and (with `--signals-dir`) S2/S3 injected into the rebuilt book, both queue models, PnL split by component (`docs/research/block-simulator.md`) | `python -m marketimmune.cli.build_albers_silver --coin SOL --dates 20251201..20251231 --mbo`, then `python -m marketimmune.cli.simulate_quotes --coin SOL --signals-dir data/gold/hyperliquid/quote_signals --out eval/sim_sol.json` |
| `sim_hft_sol.json` | S1 in hftbacktest (risk-averse, power-probability queues) against the engine, with and without the L2 crossing rule | `.venv-sim` (extra `sim`): `python -m marketimmune.cli.hft_baseline --coin SOL --out eval/sim_hft_sol.json` |
| `node_fills_reconciliation.json` | Node fills (`pull_node_fills`) against the Albers Silver fills, trade by trade, SOL and ETH December: matches, field differences, one-sided trades and the archive's missing windows (`docs/research/node-fills-reconciliation.md`) | `python -m marketimmune.cli.reconcile_node_fills --coins SOL,ETH --dates 20251201..20251231` |
| `quote_signals_sol.json` | Quote-time S2/S3 models for the simulator: per-model pinball skill on the Gold fills they did not train on, the dropped fill-time columns, and per day the train/serve check, unscored share and pull share at 2 bps (`docs/research/block-simulator.md`) | `python -m marketimmune.cli.quote_signals --coin SOL --dates 20251201..20251231 --report eval/quote_signals_sol.json` |
| `pipeline_speed/` | Stage timings on a synthetic panel shaped like the SOL run | `python eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json` |

The Rust replay benchmark is `cargo bench -p hl-replay --bench replay`
(`crates/hl-replay/benches/replay.rs`); its numbers are in `docs/performance.md`.
