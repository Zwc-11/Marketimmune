# Pre-registration: one test of the market-making strategies on locked fresh hours (2026-11-07)

Written 2026-11-07 about 04:40 UTC, before the hours it names are replayed by anything. The commit
time is the registration time. Drafted by Claude at Caesar's request: "find a better market making
strategy that's not cheating", built from the project's results.

## The locked hours

Recorded live on Caesar's PC after every selection and held-out hour, copied at 04:05 UTC and not
replayed, sampled or read by any analysis before this commit:

| Segment | Recorded by | UTC | Files |
|---|---|---|---|
| `locked-test/tuned-20261106T2203` | tuned run (port 8766) | 22:03-00:03 | hl, cb, tick, hours 22-00 |
| `locked-test/tuned-20261107T0003` | tuned run | 00:03-02:03 | hours 00-02 |
| `locked-test/mm-20261107T0205` | market-maker run (port 8767) | 02:05-04:00 | hours 02-03 |

SHA-256 of the files' SHA-256 lines (`sha256sum data/paper/locked-test/*/raw/* | sha256sum`):
`ab56e3efadd9616a220be46287da27f3a74de586016d6445e43546402b1abff9`.

## What was built and chosen before this (exploratory; `docs/research/paper-trading.md`)

- **`immune@h=<s>/t=<bps>/risk=<phi>`**:
  - **Model:** predicts each touch fill's markout from the signals known 200 ms before it. Ridge per
    horizon with coin intercepts, fitted on 36,903 selection-hour touch fills
    (`marketimmune/paper/models/immune_*.json`, `eval/paper/immune_fit_20261106.json`).
  - **Rule:** quote a side only while predicted markout - fee - mean-variance inventory cost >= t.
  - **Held out:** the model's correlation is 0.30 at 10 s and 0.20 at 30 s, but touch fills lose
    2.9 bp after fees on average, and even its best tenth only breaks even before fees.
- **`optimal@phi=<phi>`**: the optimal-control policy (value iteration over position x 7 market
  states, calibrated per coin on the selection hours; `marketimmune/paper/models/optimal.json`,
  `eval/paper/optimal_fit_20261106.json`).
  - With any inventory aversion it never opens a position.
  - The predictable move (at most about 1.2 bp in the top state, spent within 5-15 s) does not pay
    the fee and the adverse move of a fill.
- **`guard@.../veto=<bps>`**: the gap + wallets quoter that also pulls a side whose fill the 10 s
  model expects to lose more than `-veto` bp after the fee.
- **Selection** (8.19 h; the 2 h held out at 20:03-22:03 never used to pick; causal clock;
  `eval/paper/tune_immune_home_20261106.{json,md}`, `tune_guard_home_20261106.{json,md}`):
  - **Best within the rate limit:** `guard@z=0.05/w=1.5/win=5`, +$4.3/h, +$3.8 held out.
  - **`immune@h=30/t=-1`:** +$8.5/h in-sample but over the rate limit (1.18 orders per $), and
    +$1.2/h held out. Its model was fitted on the same hours.
  - **`guard@z=0.05/w=1.5/win=5/veto=-2`:** +$2.5/h in-sample, +$7.2/h held out.
- **Overfitting** (`eval/paper/overfit_20261106.json`; 46 candidate settings, 34 fifteen-minute
  blocks):
  - **Probability of backtest overfitting (CSCV):** 0.03.
  - **Deflated Sharpe ratio of the pick:** 0.001, counting 186 settings tried on these hours today
    and before. Its plain probabilistic Sharpe is 0.78.
  - **Reading:** the pick cannot yet be told from the luckiest of that many settings.

## The test

- **Replay:**
  - **Chain:** the live chain warm-up 16:06, 18:06 and 20:03, not scored, then the three locked
    segments in order.
  - **Settings:** the clock corrected from earlier timestamps only (`--causal-clock`), $250 quotes,
    4 a coin, a $5,000 budget, 200 ms orders, 1.5 / 4.5 bp fees.
  - **Fixed:** the models and policies at this commit, unchanged.
- **Strategies:**
  - `guard@z=0.05/w=1.5/win=5` (the pick);
  - `zgap@0.05` (the baseline, running in the tuned run);
  - `guard@z=0.05/w=1.5/win=5/veto=-2`, `immune@h=30/t=-1`, `optimal@phi=0`, `optimal@phi=0.01`;
  - `mm@h=2/skew=6`, `touch`.
- **Primary:** the pick against `zgap@0.05`, paired on the same 15-minute blocks, summed over the
  coins.
  - The stationary bootstrap interval (mean block 3, 5,000 draws, seed 0) at 95% entirely above
    zero: the wallet factor adds to the gap quoter on fresh hours.
  - Otherwise: not shown on these hours.
- **Secondary, no claims:**
  - every other strategy's PnL and pairing with `zgap@0.05`;
  - orders per $ (over 1 is not runnable at this size);
  - PnL by component.
- This test is run once. Nothing chosen here is retuned on these hours. If the replay fails for a
  technical reason, the fix and a rerun are recorded under Deviations.

## Deviations

(none)
