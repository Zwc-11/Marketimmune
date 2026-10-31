# eval

Benchmarks, each in its own folder with the script that produced it and the
committed result. A number quoted anywhere in the repo links to a file here.

| Folder | What | Rerun |
|---|---|---|
| `markout_sol_10s/` | SOL maker-fill markout model (the deployed v2 model): purged k-fold CV on May 27 to 31, 2026, forward holdout June 1 | Purged k-fold was removed from the trainer (v3 validates with the rolling daily walk-forward only); at commit `8f731c0`, with the local Gold partitions: `python -m marketimmune.cli.train --coin SOL --dates 20260527..20260531 --holdout-date 20260601 --horizon 10s --iterations 150 --n-splits 5 --cv-scheme purged_kfold` |
| `sol_dec_registered/` | The pre-registered SOL December 2025 ladder (`docs/preregistration/sol-dec-2025-ladder.md`) as first run: classifier and quantile reports, rung comparisons, MCS, policies, decomposition, forecaster evaluation. OOF parquet files are gitignored | Code `8f731c0`, Dec 12 excluded; see the pre-registration |
| `sol_dec_corrected/` | The same ladder on the month rebuilt after the 2026-10-31 data fixes (pre-registration, Deviations) | The registered commands, rerun after `run_albers_month` rebuilds the month |
| `ladder_verdicts.json` | H1-H5 verdicts for both SOL runs under the pre-registered rules (`docs/research/sol-dec-2025-ladder-results.md`) | `python -m marketimmune.cli.score_ladder --runs eval/sol_dec_registered,eval/sol_dec_corrected` |
| `pipeline_speed/` | Stage timings on a synthetic panel shaped like the SOL run | `python eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json` |

The Rust replay benchmark is `cargo bench -p hl-replay --bench replay`
(`crates/hl-replay/benches/replay.rs`); its numbers are in `docs/performance.md`.
