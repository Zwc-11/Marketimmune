# Pre-registration: the ETH December 2025 feature ladder (confirmatory)

Written 2026-10-31 15:15 ET, before any ETH model result existed. Commit this file
before running `marketimmune.cli.train`, `train_quantile`, `compare_rungs` or
`mcs_rungs` on ETH; the commit time is the registration time. Any later change goes
in **Deviations** with its date and reason.

**Why this run.** The SOL December 2025 ladder
(`docs/research/sol-dec-2025-ladder-results.md`) left two results that only its
corrected run supports, because its data fixes came after results were seen: H2
(wallet scores over the CEX gap) and H4 on pinball (the forced-flow columns in the 60 s
after a forced fill). This run tests them on data no analysis has touched, with the
same code, settings and rules. It also replicates H1, H3 and H5.

**Seen before registration (disclosed):**

- **All SOL results.** Both SOL runs in full; they are why these hypotheses were chosen.
- **ETH order-book rebuild, Dec 1 hours 0-1:** no crossed blocks, fills at the touch
  0.997 to 0.999.
- **A pipeline smoke run on ETH Dec 1-2, every stage, in a scratch lake that was then
  deleted:**
  - Books: no crossed block in any of the 48 hours; fills at the touch at least 0.9959.
  - Archive problems: 0 replayed statuses dropped; 1 and 2 trigger orders traded
    instead of resting.
  - Fills: 402,483 and 270,879 matches, of which 3,391 and 670 were liquidations.
  - Positions: no chain breaks.
  - Gold: 385,911 and 268,705 training rows; every leakage check passed.
  - Forecast: the liquidation-distance prior had 571 positions on Dec 2.
- **Not seen:** the Gold stage's log line also prints the day's toxic rate; it was
  masked before display. No label distribution, markout, feature value or model on
  ETH has been looked at.

## Data

Identical to the SOL pre-registration except for the coin:

| Item | Value |
| --- | --- |
| Market | Hyperliquid ETH perpetual |
| Period | 2025-12-01 to 2025-12-31 (UTC) |
| Code | Commit `286ead8`: the corrected pipeline (archive replays dropped, triggers that would cross trade instead of resting, OFI windows restart at a book reset) |
| Book, fills, positions, forecast, label | As in `sol-dec-2025-ladder.md` (Albers L4 rebuild, 10-min warm-up and gap resets; `trades_2025_12`; positions rolled forward from Dec 1; forecast columns missing on Dec 1-2; maker markout from the last pre-fill mid at 1 s (primary) and 10 s (secondary), `toxic = markout < -1 bp`) |
| Reference | Binance USD-M ETHUSDT aggTrades, 2025-11-30 to 2025-12-31, feed latency 300 ms |
| Margin tiers | ETH 25x below 100M USD notional, 15x above (`forced/margin_tiers.py`). A max-leverage position's liquidation sits 2.04% below entry (long) and 1.96% above (short). The forecaster's distance prior is fitted on earlier dates, as for SOL |
| Data gaps | The archive gap of 2025-12-12 17:40:43 to 18:16:01 UTC applies to every coin; handled as for SOL |
| Exclusions | A date whose `.leakage.json` has `passed = false` is excluded from every rung and reported |
| Data-quality gate (new) | `run_albers_month` exits non-zero when any hour has a crossed-block share above 0.001 or fills at the touch below 0.90 (`gate_failures`). The corrected SOL month passes: no crossed hour, worst fill-at-touch hour 0.941, where takers swept a thin book. If ETH fails, no model is trained; the cause is diagnosed, fixed, and recorded in Deviations before any training. A date is never dropped for failing this gate |

## Validation, rungs, settings, metrics

Unchanged from `sol-dec-2025-ladder.md`:

- **Validation:** rolling daily walk-forward, 7-day training window, 60 s purge.
  Tested days 2025-12-08 to 12-31; L3b and L3 from 12-10.
- **Rungs:** `l0_book`, `l1_book`, `l2_book`, `l3a_book`, `l3b_book`, `l3_book`,
  placebo `l3a_placebo_book`; secondary `l3b_realised_book`.
- **Settings:**
  - CatBoost: 150 iterations, depth 6, learning rate 0.08, seed 42, calibration 0.2.
  - LightGBM quantile: tau 0.1/0.5/0.9, 300 trees, learning rate 0.05, 31 leaves,
    min child 200, seed 42.
  - Tests: DM with Newey-West lag 2 and HLN; stationary bootstrap, mean block 3 days,
    5,000 draws, seed 0; MCS alpha 0.10.
  - Regimes: the same definitions.
- **Primary metrics:** daily mean Brier (classifier, 1 s) and daily mean pinball at
  tau 0.1 (quantile, 1 s).

Every step runs from `scripts/run_ladder.ps1 -Coin ETH -Name eth_dec`, the same steps as the
SOL runs. Reports go to `eval/eth_dec/`, named `eth_dec_<rung>.json` and `q_eth_dec_<rung>.json`.
Only the `l3_book` quantile rung runs with `--contrib`, which writes the contributions
the decomposition reads; it does not change predictions.

## Hypotheses and decision rules

H1-H5 and their rules are the SOL ones, word for word. Each needs:

- the stated sign;
- a two-sided DM p < 0.05 after Holm across H1-H4 within a metric;
- a bootstrap 95% interval that excludes zero.

H3 also needs the placebo vs L2 not significant (raw p > 0.10) in any regime. H5 needs
L0 and L1 outside the MCS at alpha 0.10. H4 enters Holm through its route (`forced_60s`
or overall) with the smaller p, that p doubled. All of this is computed by:

    python -m marketimmune.cli.score_ladder --runs eval/eth_dec --name eth_dec --out eval/eth_dec/ladder_verdicts.json

| ID | Role | Confirmed / replicated if (on ETH) |
| --- | --- | --- |
| H2 | **Confirmatory** | Supported on both primary metrics |
| H4 (pinball) | **Confirmatory** | The pinball H4 row is supported **and** its route is `forced_60s`. The SOL result was pinball-only, so this part needs no Brier support. H4 as a whole, on both metrics, is reported too |
| H1 | Replication | Supported on both primary metrics |
| H5 | Replication | Supported on both primary metrics |
| H3 | Replication of a null | Reported; SOL found nothing in both runs |

**What follows:**

- **If ETH confirms H2:** the claim is "taker-wallet scores add to the CEX gap", with
  SOL as the discovery and ETH as the test.
- **If ETH confirms the H4 pinball result:** the claim is "the forced-flow columns
  improve the 10th-percentile markout forecast in the 60 s after forced fills". It is
  about the quantile; it is not a claim about the toxicity probability.
- **If ETH does not confirm:** the result is reported as a failed replication with its
  interval. BTC may be run later, under its own pre-registration, and reported whatever
  it shows. It does not replace or overrule this verdict.

**Later, in January 2027:** the plan's held-out month stays as a second confirmatory
test, recorded live (the data-access terms question was answered 2026-10-31; see
`docs/research/jurisdiction.md`). It will be scored once, after its own
pre-registration.

## Secondary (reported, not used for claims)

The same secondaries as for SOL:

- log loss; pinball at 0.5 and 0.9; the 10 s horizon; per-regime results;
- `l3b_realised` vs L2;
- the forced-flow forecaster's evaluation;
- the decomposition (L3 quantile at tau 0.5, and the Gold one);
- the S1, S2 (`q_eth_dec_l2_book`), S3 (`q_eth_dec_l3_book`) and stale-quote (500 ms)
  policies under the fill-filter approximation. As for SOL, there is no economic claim
  without the block-accurate simulator.

## What will not be done

- No hyperparameter, window, threshold, regime or rule change after any ETH test-day
  result is seen.
- No dropping of days or rungs because of their results.
- No second ETH run with changed rules. A data bug found after results is fixed and
  reported as for SOL, and both runs must then agree.
- No economic claim (PnL) from these tests.

## Deviations

### 2026-10-31: the data-quality gate stopped the run on 2025-12-15 (no data error)

`run_albers_month` stopped the run before any model was trained. In 2025-12-15 hour 3
(03:00 to 04:00 UTC), 89.7% of resting fills were at the touch (2,238 of 2,494), below the
gate's 0.90. The diagnosis used the Silver L2 rows and fills of that hour.

- **One sweep.** At 03:03:21 a single taker order (oid 269411640410) bought 5,207 ETH in 666
  fills across 77 price levels, clearing the asks up to 76 ticks above the touch. That minute
  holds 706 of the hour's 1,828 fills away from the touch.
- **Other sweeps.** 65% of the fills away from the touch come from taker orders that also hit
  the touch, which is what a sweep looks like.
- **No sign of a data error.** The book never crossed that day. Every resting fill in that
  hour was within the top five levels when it happened (2,494 of 2,494). No archive replay
  fell in that hour.

This is a market event, not a data error, so nothing changes: no fix, and no date dropped,
as registered. Training starts on the month as rebuilt. Seen while diagnosing: that hour's
fill prices, sizes, taker order ids and book tops. No label, markout, feature value or model
was looked at.
