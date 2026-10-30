# eval

Benchmarks, each in its own folder with the script that produced it and the
committed result. A number quoted anywhere in the repo links to a file here.

| Folder | What | Rerun |
|---|---|---|
| `markout_sol_10s/` | SOL maker-fill markout model: purged k-fold CV on May 27 to 31, 2026, forward holdout June 1 | `python -m marketimmune.cli.train --coin SOL --dates 20260527..20260531 --holdout-date 20260601 --horizon 10s --iterations 150 --n-splits 5 --cv-scheme purged_kfold` (needs the local Gold partitions) |
| `pipeline_speed/` | Stage timings on a synthetic panel shaped like the SOL run | `python eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json` |

The Rust replay benchmark is `cargo bench -p hl-replay --bench replay`
(`crates/hl-replay/benches/replay.rs`); its numbers are in `docs/performance.md`.
