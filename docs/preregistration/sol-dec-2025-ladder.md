# Pre-registration: the SOL December 2025 feature ladder

Written 2026-10-30 19:30 ET, before any month-scale model result existed. Commit
this file before running `marketimmune.cli.train`, `train_quantile`,
`compare_rungs` or `mcs_rungs` on the month; the commit time is the registration
time. Any later change goes in **Deviations** with its date and reason.

**Seen before registration (disclosed):** smoke runs on 2025-12-01 hours 00-02
only (PR-AUC L0 0.748, L1 0.810, L2 0.814, L3a/L3b 0.811; CEX-gap correlation
0.49). No December day after 2025-12-01 has been modelled. Also seen, with no
ladder model involved: the S1 quote-everything PnL on 2025-12-01 to 12-11 (net
-0.27 / -0.36 / -0.51 bps per filled dollar at 1 / 10 / 60 s before fees), and
the forced-flow forecaster's own evaluation on 2025-12-03 to 12-11 (Brier and
lead time against its baselines). The forecaster's settings below were fixed
before that evaluation, except that a negative fitted impact is clipped to zero.

## Data

| Item | Value |
| --- | --- |
| Market | Hyperliquid SOL perpetual |
| Period | 2025-12-01 to 2025-12-31 (UTC) |
| Book | Albers L4 rebuild (`build_albers_silver`): one row per block whose top 5 levels changed; first 10 min of the run dropped as warm-up |
| Fills | Albers `trades_2025_12`: one row per match, both wallets |
| Reference | Binance USD-M SOLUSDT aggTrades, feed latency 300 ms |
| Positions | Rolled forward from every fill's start position (`build_positions`); state carries across dates from 2025-12-01 |
| Forecast | `forced_forecast`: 10 s grid; liquidation-distance prior, hazard scale (realised / forecast notional) and cascade impact fitted on earlier dates only; 2025-12-01 seeds the prior, 12-02 the scale, so forecast columns are missing on those two dates |
| Label | Maker markout in bps anchored at the last mid strictly before the fill; horizons 1 s (primary) and 10 s (secondary); `toxic = markout < -1 bp` |
| Data gaps | The Albers archives miss 2025-12-12 17:40:43 to 18:16:01 UTC. A jump of more than 30 s between blocks resets the rebuilt book and drops the next 10 min of book rows; a label whose pre-fill or horizon mid is more than 30 s stale is dropped |
| Exclusions | A date whose `.leakage.json` has `passed = false` is excluded from every rung and reported |

## Validation

Rolling daily walk-forward (`--cv-scheme rolling_daily`), 7-day training window,
60 s purge. Tested days: 2025-12-08 to 2025-12-31 (24 days). Every rung is
compared on the fills all compared runs evaluated.

## Rungs (feature sets)

`l0_book`, `l1_book` (+ CEX gap), `l2_book` (+ taker-wallet scores),
`l3a_book` (+ lost races), `l3b_book` (+ realised forced flow and the
position-book forecast: F and P per side at 5 / 15 / 60 s, heatmap mass),
`l3_book` (both), placebo `l3a_placebo_book` (L2 + opposite-side lost races
only). Secondary: `l3b_realised_book` (L2 + realised forced flow only), to show
what the forecast adds to it.

## Fixed settings (not tuned on December)

| Model | Settings |
| --- | --- |
| Classifier (`train`) | CatBoost, 150 iterations, depth 6, learning rate 0.08, seed 42, calibration fraction 0.2 |
| Quantile (`train_quantile`) | LightGBM quantile, tau 0.1/0.5/0.9, 300 trees, learning rate 0.05, 31 leaves, min child 200, seed 42 |
| Tests | Daily mean loss; Diebold-Mariano with Newey-West lag 2 and HLN factor, Student t (23 dof); stationary bootstrap, mean block 3 days, 5,000 draws, seed 0; MCS alpha 0.10 |
| Regimes | `cex_move`: abs(Binance 1 s return) >= 2 bps; `quiet`: the rest; `forced_60s`: a forced fill hit either side in the 60 s before the fill; `taker_liquidation`: taker was the liquidation engine (secondary) |

## Primary metrics

1. Classifier, 1 s horizon: daily mean **Brier**.
2. Quantile ladder, 1 s horizon: daily mean **pinball at tau = 0.1** (the quoting rule's input).

Secondary (reported, not used for claims): log loss; pinball at 0.5 and 0.9;
the 10 s horizon; per-regime results.

## Hypotheses and decision rules

"Supported" requires the stated sign, two-sided DM p < 0.05 after Holm
correction across H1-H4 within a metric, and a bootstrap 95% interval that
excludes zero. Both primary metrics are reported; a hypothesis is claimed only
if supported on both.

| ID | Comparison | Supported if |
| --- | --- | --- |
| H1 | L1 vs L0 | L1 lower loss overall |
| H2 | L2 vs L1 | L2 lower loss overall |
| H3 | L3a vs L2 | L3a lower loss in `cex_move`; and the placebo vs L2 is **not** significant (raw p > 0.10) in any regime |
| H4 | L3b vs L2 | L3b lower loss in `forced_60s` or overall |
| H5 | MCS over L0-L3 and the placebo | L0 and L1 excluded at alpha 0.10 |

A hypothesis that is not supported is reported as a null with its interval.
H3 fails if the placebo is significant, whatever L3a shows.

## What will not be done

- No hyperparameter, window, threshold or regime-boundary change after any
  December test-day result is seen.
- No dropping of days or rungs because of their results.
- No economic claim (PnL) from these tests; that needs the simulator.

## Deviations

### 2026-10-31: data bugs found after the registered run

The registered run finished on 2026-10-31 (code `7035c0c`, `8f731c0` before an author-only history rewrite on 2026-11-02; Dec 12 excluded). Its
reports are kept unchanged in `eval/sol_dec_registered/`. Three data bugs were found
afterwards, two of them *because of* those results, so everything below is post hoc:

1. **OFI windows across a book reset** (found before results, by Dec 12's failed
   leakage check; fixed after L0/L1 results were seen). A jump of more than 30 s
   between Silver book rows now restarts the OFI windows. 30 rows change, all on
   2025-12-12, which then passes its leakage check.
2. **Archive replays** (found after all results, from the validation files' crossed
   hours and an outlier day in the PnL). The status and trades files jump back in time
   and repeat windows on Dec 9, 15, 18, 21 and 30. Every status behind the newest
   timestamp is an exact copy of an earlier one, and exact repeats of a trade are not
   second trades; both are now dropped. Replaying them re-opened cancelled orders,
   crossed the rebuilt book for up to an hour each time, and duplicated fills and
   liquidation events.
3. **Trigger orders fired through the book** (same discovery). A stop that fires at
   a limit through the opposite best trades; it does not rest. On 2025-12-19 04:11 a
   buy stop at 131.61, with the best ask at 121.86, was rested and crossed the book
   until the archive gaps of Dec 20 reset it (28 hours; 79% of Dec 19's fills).

No hypothesis, metric, setting, fold or regime changes. The corrected run applies the
registered rules unchanged to the rebuilt month: the date-exclusion rule now keeps
Dec 12, because it passes. Both runs are reported in full, side by side. Because the
corrections were made after results were seen, a hypothesis is called supported only
if it is supported in **both** the registered and the corrected run; a result that
appears only in the corrected run is reported as exploratory.
