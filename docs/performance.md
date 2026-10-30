# Performance

A pass over the markout pipeline's hot paths, from archive labels to the browser.
The rule was "same inputs, same report": every change is measured, and the
end-to-end training report is compared field by field against the original code.

## Pass 2 (2026-10-30): the v3 Albers path, the leakage check, the Rust book

Measured on real data (Albers et al. SOL, 2025-12-01) on a 2 vCPU, 3 GB Linux VM,
Python 3.12; "before" is commit `add8ab7` run on the same machine. Every output
was compared: same parquet tables, same validation JSON, same check verdicts.

| Stage | Before | After | Speedup |
|---|---:|---:|---:|
| Silver L2 + order events, 24 h of statuses (801,715 rows, 346,446 events) | 134.3 s | 57.7 to 74.1 s | 1.8 to 2.3x |
| Silver fills from the hourly trades members (169,024 matches) | 7.8 s | 5.4 s | 1.4x |
| No-look-ahead check, 200 fills against 160K labels and 802K book rows | 103.3 s | 1.5 s | 69x |
| Gold stage for the day (labels, training rows, check, CEX gap) | about 110 s | about 7 s | 16x |
| Rust match-mode engine, 1M synthetic actions | 44.5 ms (22.5 M/s) | 37.3 ms (26.8 M/s) | 1.19x |

For the whole SOL month that is about 2.2 hours down to about 40 minutes for the
three Albers stages.

**Book diffs.** Each hourly diff member holds every coin, 1.6 GB of JSON. Lines are
written with a fixed key order, so one regex over 16 MB inflated chunks reads the
oid and size of a coin's `new` diffs without `json.loads`; a chunk where a line of
that coin breaks the order falls back to JSON. python-isal (`pip install .[fast]`)
inflates 2.3x faster than zlib. A worker process parses the next hours' diffs while
the current hour replays (`--diff-workers`, DeepInfer's overlap of CPU scheduling
with execution).

**Replay.** NumPy classifies all 2.4M statuses of an hour first: rejections, opens
that never rested and statuses of orders the book never held are counted, not
looped over. Blocks with nothing left leave the book unchanged and are counted in
bulk. The remaining book updates are inlined, the top five levels are recomputed
only after a change that touched them, and Silver rows are built straight from the
levels.

**Leakage check.** It used to rebuild every sampled fill twice, once over the rest of
the day, so each of the 200 samples processed hundreds of thousands of book rows.
The uncut run is now one `build` call for all samples (the builder is row-wise, the
same property the as-of join already has); only the cut runs stay per sample. The
largest feature difference it reports is now 4e-13, the rounding of prefix-sum
windows that start earlier; the tolerance is 1e-9. It is also stricter: a feature
that reads further back than `lookback_ms` now shows up as a mismatch, where one
call per label cut both runs at the same point and let it pass.

**Rust book.** A batch is split into its three classes with three O(n) passes
instead of a sort, the duplicate check is a map lookup, and a taker drains each
crossed level in place instead of looking the level up again for every fill. The
2 x 1024 proptest streams against the naive reference still match exactly.

## Pass 1 results

Measured on the cloud container used for this work (2 vCPU, Python 3.13, NumPy
2.x), median of runs, no other load. Synthetic inputs are shaped like the SOL run
(724,150 fill rows over five days, 91-point threshold grid, a 400K-snapshot L2 day,
190K fills to label); the real Gold partitions are local-only.

| Stage | Before | After | Speedup |
|---|---:|---:|---:|
| Fold-local threshold selection, 724K rows x 91 thresholds x 5 folds | 39.63 s | 0.61 s | 65x |
| Deployment threshold sweep, 724K x 91 | 9.59 s | 0.15 s | 63x |
| Out-of-fold evaluation report (PR-AUC, Brier, ECE, lift per fold) | 2.12 s | 0.29 s | 7x |
| Purged k-fold splits, tuple API | 0.61 s | 0.31 s | 2x |
| OFI event + 1/5/10 s windows, 400K snapshots | 5.34 s | 0.91 s | 6x |
| As-of feature join, 190K fills | 8.75 s | 2.03 s | 4x |
| Gold markout labels, 190K fills | 2.30 s | 1.58 s | 1.5x |
| Score 2,000 fills one call at a time (CatBoost) | 0.35 s | 0.27 s | 1.3x |
| Score 2,000 fills in one batch (CatBoost) | | 0.012 s | 29x vs one at a time |
| One fill, CatBoost-free oblivious-tree evaluator | | 20 µs | |

End to end, the full trainer on a synthetic 724,150-row panel plus a 210,530-row
holdout day (150 CatBoost iterations, 5 folds, 6 fits), same flags as the committed
report:

| Trainer run | Before | After |
|---|---:|---:|
| Wall time, `--cv-scheme purged_kfold` | 200.3 s | 98.6 s |
| of which CatBoost fitting (`fit_elapsed_s`) | 94.9 s | 94.2 s |
| Everything else: loading, evaluation, thresholds, holdout | 105.4 s | 4.4 s |

CatBoost now dominates; the remaining 4 s is parquet decode and the six
`predict_proba` calls.

`python eval/pipeline_speed/bench.py --out eval/pipeline_speed/results.json` reruns
the after-column stages on any machine; the before column came from the same
harness pointed at commit `087b1fd`.

## What changed

**Threshold sweeps: sort once, prefix-sum, binary search.** The quoting policy
keeps a fill when `p < threshold`. For probabilities sorted ascending, the kept
set for any threshold is a prefix, so policy markout for all 91 thresholds is
`cumsum(markout[order])[searchsorted(p_sorted, grid)] / n`. That replaced a Python
loop over every row for every threshold (`O(n * g)` to `O(n log n + g log n)`).

**Splits as index arrays.** `temporal_fold_arrays` sorts timestamps once with a
stable `argsort`; each fold's train set is a prefix (walk-forward) or a prefix plus
a suffix (purged k-fold) found with two `searchsorted` calls. The trainer and the
evaluator consume `np.intp` arrays directly instead of 579K-element tuples.

**Vectorized metrics.** Brier, reliability bins, and ECE use `bincount`;
`ECE = sum_b |sum(y_b) - sum(p_b)| / n` needs no per-bin division.

**Feature joins.** OFI events are computed column-wise; each rolling window is a
prefix-sum difference located with `searchsorted` (the same arithmetic as before,
so values are bit-identical). The as-of join resolves every fill's latest prior L2
and asset row with one `searchsorted` per coin and checks point-in-time
correctness for all rows at once.

**Batched, batch-invariant scoring.** `HyperliquidMarkoutScorer.predict_batch`
makes one model call for many fills; isotonic calibration is a binary search
instead of a linear scan. Gold scoring sorts and slices the parquet table in Arrow
and only materializes the rows it scores.

**Training I/O.** Partitions load in a thread pool, the holdout day is read while
CatBoost fits, and the feature matrix is a contiguous float32 array (CatBoost
quantizes to float32 anyway, so the model is unchanged).

## Ideas taken from DeepInfer

DeepSeek's [DeepInfer](https://github.com/deepseek-ai/DeepInfer) is an LLM
inference engine; three of its ideas carry over to a tabular scorer.

| DeepInfer | Here |
|---|---|
| Asynchronous scheduling overlaps CPU batch scheduling with device execution | The holdout parquet loads while CatBoost trains; partitions decode in parallel |
| Decoder SWA bounded replay: recompute only a bounded suffix instead of the whole prompt | Browser OFI keeps only the last 10 s of book events (`frontend/src/lib/ofi.ts`) and still matches the full-day Python prefix sums to 1e-12 |
| Batch-invariant inference: identical results whatever the batch composition | `predict_batch` returns exactly the per-fill result; pinned by a test with a real CatBoost model, because an audited decision must not depend on what else was in the batch |
| Benchmark sweep script and methodology | `eval/pipeline_speed/bench.py` writes machine info and per-stage medians to JSON |
| Asynchronous scheduling, again | Albers book diffs parse in a worker process while the previous hour replays |

## The browser

The terminal applies the same discipline to rendering, because on a trading screen
a stalled frame is a stale price:

- WebSocket messages mutate private state; one `requestAnimationFrame` flush
  publishes a snapshot per frame however many messages arrived.
- Each slice (book, tape, candles, stats) keeps its identity until it changes, and
  components subscribe with `useSyncExternalStore` selectors, so a new trade does
  not re-render the book.
- The 10 s countdown on every pending fill is a CSS animation started with a
  negative delay; there are no per-row timers.
- Candles are set once; live ticks go through `series.update`.
- The oblivious-tree evaluator flattens 150 trees into typed arrays and scores a
  fill with no allocation. The Python twin packs trees into `(trees, depth)`
  arrays: about 20 µs for one fill, and both of its code paths add trees in the
  same order, so a fill scores bit-identically alone or inside a 100K batch.
- Bundle: the previous UI shipped Three.js for a WebGL hero, 1.11 MB of JavaScript
  (314 KB gzipped). The terminal ships 561 KB (188 KB gzipped), a third of it the
  TradingView chart library, and loads each page lazily.

## Equivalence

With `--cv-scheme purged_kfold`, the optimized trainer reproduces the original
report on the same 724K-row panel: every numeric field matches within `2e-13`
(floating-point summation order), every chosen threshold is identical, and no
field is missing. The only intentional differences are new fields (`cv_scheme`,
`n_evaluated`) and `latency_p95_ms`, which now times the float32 vector path the
deployed scorer uses instead of a one-row pandas frame.
