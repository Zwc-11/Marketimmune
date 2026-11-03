# Pre-registration: A1, priority fees in fills (BTC, ETH, SOL, Apr to Oct 2026)

Written 2026-11-01, before any model on a 2026 date in the registered period. Drafted by Claude;
Caesar reviews it and commits it. The commit time is the registration time. Commit this file
before running `a1_ladder`, `train`, `train_quantile`, `compare_rungs`, `mcs_rungs` or `score_a1`
on any 2026 date; `scripts/run_a1.ps1` refuses to start until it is committed and unchanged. Any
later change goes in **Deviations** with its date and reason.

**The question (plan v3, A).** Do the priority fees takers paid in the last few blocks predict
the maker's markout on the next fill, beyond the Binance-Hyperliquid gap and the taker's own
wallet score?

**Split (Caesar, 2026-11-01).**

- **Discovery:** 2026-04-25 to 2026-08-31.
- **Confirmation:** 2026-09-01 to 2026-10-31.
- Every coin in both.
- The claim rests on the confirmation months only. Discovery results are reported as
  exploratory.

**Seen before registration (disclosed):**

- **All December 2025 results** (SOL, ETH), and the block simulator.
- **The raw separation table** (plan A.5 test 2, `docs/research/priority-fees.md`): maker
  markout by the taker's fee band, every month Apr 25 to Oct 31 and every coin.
  - It is monotone, with large gaps between bands.
  - No model was fitted. The CEX gap was not in it.
  - It is why this test is worth running. It says nothing about the increment over the CEX
    gap, which is what is tested here.
- **The fee-paying share by month and the fee distribution** (same document).
- **The trade-implied mid's agreement with the rebuilt book on December 2025**
  (`eval/trade_mid_validation.json`).
- **Pipeline smoke run** on SOL 2026-03-01 to 03-10 (before the rollout, outside the registered
  period), in a scratch lake: Gold build and leakage checks, wallet stage, and `train` and
  `train_quantile` with 10 and 20 trees on `l3_fee` and `l2_trade`. It checked that every stage
  runs and writes `leakage_safe` reports. No metric was read.
- **One Gold build test on 2026-06-01 (SOL, BTC):** while debugging the builder, the summary
  statistics of that day's rows were printed:
  - null counts, mean, min, median and max of some trade-state and fee columns, the CEX gap,
    the 10 s markouts and `toxic_10s` (BTC toxic rate 0.47);
  - the share of rows with nonzero fee pressure (SOL 0.025, BTC 0.036).
  No relationship between a feature and a label was computed, and no model was fitted.
- **A fix before registration (2026-11-01):** the trade-implied mid and the block table first
  took a block's "last" prices in trade-id order, which is not execution order, so they picked
  an arbitrary fill of the block. Found while rolling positions from node fills for an
  unrelated forecaster; fixed to execution order (`priority.fills.execution_order`). The band
  table and the trade-mid validation above were rerun with the fix (band markouts moved by at
  most 0.05 bps at 10 s and 60 s). The 2026-06-01 summary statistics above came from the first
  version.
- **Not seen:** any model result, or any feature-label relationship, for a date in the
  registered period.

## Data

| Item | Value |
| --- | --- |
| Markets | Hyperliquid BTC, ETH and SOL perpetuals, each tested on its own |
| Period | Gold rows from 2026-04-25, the rollout, so no model sees days before the fees existed (plan A.5 test 1). The 7-day training window puts the first tested day at 2026-05-02 |
| Fills | `node_fills_by_block` (`pull_node_fills`), one row per match, maker's side |
| Book | None: there is no L4 archive for 2026. The state rung is built from trades only (below) |
| Mid | The trade-implied mid (`priority.fees.trade_mids`): after each block, the mean of the last taker-buy and taker-sell prices, "last" in execution order (taker order id, then along the order's sweep; `priority.fills.execution_order`); the block's last price while they cross |
| Reference | Binance USD-M BTCUSDT, ETHUSDT and SOLUSDT aggTrades, feed latency 300 ms. 2026-10-28 has no Binance file, so it is excluded from every rung |
| Fee | `priorityGas` x HYPE/USD (`info` candles, hourly where served, 4-hourly before Apr 7) / notional, in bps |
| Label | Maker markout in bps from the last trade-implied mid strictly before the fill's block. Horizons: **10 s (primary)**, 1 s and 60 s (secondary). `toxic = markout < -1 bp`. 10 s is primary because on December 2025 this markout agrees with the book's at 10 s (correlation 0.95 SOL, 0.98 ETH; `eval/trade_mid_validation.json`, `adv_10s`) but less at 1 s (0.78, 0.83) |
| Exclusions | A date with no Binance file or whose `.leakage.json` has `passed = false` is excluded from every rung and reported |

## Rungs (feature sets)

Every feature uses only blocks strictly before the fill's block, and Binance trades at or before
`t - 300 ms`.

| Rung | Adds |
| --- | --- |
| `l0_trade` | `sz`, `maker_side`, and the trade state: spread of the trade-implied quotes (bps), signed taker flow imbalance over 1, 5 and 10 s, log taker notional over 1, 5 and 10 s, log trade count over 1 and 10 s, realised volatility of the trade-implied mid over 10 and 60 s (bps), log time since the last trade |
| `l1_trade` | + the CEX gap columns (`features.cex_gap`, on the trade-implied mid) |
| `l2_trade` | + taker-wallet scores (`taker_tox_1s`, `taker_tox_10s`, `taker_log_n`, from trade-implied markouts) |
| `l3_fee` | + fee pressure for k = 3, 10 and 30 blocks (plan A.3): on the side that hits the maker, the notional-weighted mean fee FP, the fee-paying count FC, the maximum fee FM, and the priced-taker share; and FP same side minus FP opposite side |
| `l3_fee_placebo` | `l2_trade` + the same fee pressure from takers hitting the **opposite** side only |

Fee windows count blocks by block number: blocks b-k to b-1 for a fill in block b.

## Tested days

- **Confirmation:** every date from 2026-09-01 to 2026-10-31 except 10-28 (no Binance file):
  60 days.
- **Discovery:** each Wednesday from 2026-05-06 to 2026-08-26: 17 days, exploratory.
- **Training data:** every date from 2026-04-25 trains the folds of the tested days after it:
  the 7 days before each.
- **Why not every discovery day:** compute. A day of BTC is about 350,000 rows, and the full
  set would be 183 folds x 10 models x 3 coins.
- **One panel per tested day.** The whole period does not fit in memory as one training panel.
  `a1_ladder` therefore runs `train` / `train_quantile` once per tested day, on that day and the
  7 before it. This is the same fold the full run would make.
- **Seeds:** 42 plus the day's place in the tested list, standing in for "seed + fold number".

## Fixed settings

As in the December ladders, unchanged:

- **Validation:** rolling daily walk-forward, 7-day training window, 60 s purge.
- **CatBoost:** 150 iterations, depth 6, learning rate 0.08, seed 42, calibration 0.2.
- **LightGBM quantile:** tau 0.1/0.5/0.9, 300 trees, learning rate 0.05, 31 leaves, min child
  200, seed 42.
- **Tests:**
  - Daily mean loss.
  - Diebold-Mariano with Newey-West lag 2 and the HLN factor.
  - Stationary bootstrap, mean block 3 days, 5,000 draws, seed 0.
  - MCS alpha 0.10.
- **Regimes:** `cex_move` when |Binance 1 s return| ≥ 2 bps; `quiet` for the rest.

## Primary metrics

1. Classifier, 10 s: daily mean **Brier**.
2. Quantile ladder, 10 s: daily mean **pinball at tau = 0.1**.

Secondary: the 1 s and 60 s horizons, log loss, pinball at 0.5 and 0.9, the lead-time curve
(plan A.5 test 4), and discovery-month results.

## Hypotheses and decision rules (confirmation months)

"Supported" for a coin needs all three of:

- the stated sign;
- a two-sided DM p < 0.05 after Holm across the 12 tests (4 hypotheses x 3 coins) within a
  metric;
- a bootstrap 95% interval that excludes zero.

Both primary metrics are required.

| ID | Role | Comparison | Supported for a coin if |
| --- | --- | --- | --- |
| A1 | **Confirmatory, the plan's gate** | `l3_fee` vs `l2_trade` | Lower loss in `cex_move`, and the placebo vs `l2_trade` is not significant (raw p > 0.10) in any regime |
| A2 | **Confirmatory** | `l3_fee` vs `l2_trade` | Lower loss over all fills, with the same placebo condition |
| A3 | Replication | `l1_trade` vs `l0_trade` | Lower loss over all fills (the CEX gap without a book) |
| A4 | Replication | `l2_trade` vs `l1_trade` | Lower loss over all fills (December's confirmed H2, on 2026 and BTC) |

**Claims:**

- **Fees:** "fee pressure predicts the maker's markout beyond the CEX gap and the taker's wallet
  score" if A2 is supported in at least two of the three coins and its point estimate is not
  negative in the third.
- **The plan's gate:** passes if A1 is supported in at least two coins. If it fails, A2 (the
  action log) is cancelled, as the plan says.

A hypothesis that is not supported is reported as a null with its interval. `score_a1` computes
all of this from the confirmation reports (`scripts/run_a1.ps1`).

## What will not be done

- No change to features, windows, thresholds, regimes, settings or rules after any 2026 model
  result is seen.
- No dropping of days, coins or rungs because of their results.
- No economic claim (PnL) from these tests.

## Deviations

(none)
