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

## Result (scored once, 2026-11-07 04:37 UTC; `eval/paper/locked_test_20261107.{json,md}`, `locked_test_report_20261107.json`)

The locked hours ran 5.91 h in 24 fifteen-minute blocks.

| Strategy | $/h [95%] | Against `zgap@0.05`, $/h [95%] | Blocks better | Orders per $ | Mean net position | BTC correlation |
|---|---|---|---:|---:|---:|---:|
| `immune@h=30/t=-1` | +2.40 [-1.04, +5.44] | +3.52 [-1.24, +7.56] | 16/24 | 0.61 | $818 | +0.01 |
| `optimal@phi=0.01` | 0.00 (never traded) | +1.16 [-2.60, +4.80] | 14/24 | 0 | $0 | |
| `guard@z=0.05/w=1.5/win=5/veto=-2` | -0.13 [-3.36, +3.40] | +1.03 [-1.88, +3.88] | 11/24 | 0.27 | $1,243 | +0.04 |
| `optimal@phi=0` | -0.39 [-4.32, +3.80] | +0.78 [-5.84, +7.04] | 11/24 | 0.48 | $1,138 | +0.16 |
| `zgap@0.05` | -1.18 [-4.80, +2.60] | | | 0.26 | $1,344 | -0.11 |
| `guard@z=0.05/w=1.5/win=5` | -1.75 [-5.16, +1.76] | -0.56 [-1.64, +0.56] | 10/24 | 0.28 | $1,219 | -0.14 |
| `mm@h=2/skew=6` | -7.04 [-9.08, -5.04] | -5.77 [-10.72, -1.08] | 7/24 | 0.51 | $172 | +0.22 |
| `touch` | -46.88 [-56.24, -37.48] | -44.97 [-56.20, -34.80] | 0/24 | 0.09 | $1,604 | +0.25 |

- **Primary: not shown.** The gap + wallets pick made $0.56 an hour less than `zgap@0.05` on these
  hours [-1.64, +0.56]. The wallet factor's in-sample and held-out gain did not carry over.
- **The fill-toxicity quoter did best.** `immune@h=30/t=-1` made +$2.40 an hour.
  - **Where it comes from, per filled dollar:** spread +0.60 bp, the move within 1 s -0.13, fee
    -1.50, position +3.39.
  - **Exposure:** the lowest net position of the gap-type quoters and no correlation with BTC.
  - **Not significant:** its interval includes zero. With the held-out hours it has made about
    +$2/h over 7.9 fresh hours.
- **The optimal-control policy did as its calibration said.** With inventory aversion it never
  traded; without it, it lost a little.
- **Every gap quoter lost or broke even on these hours.** They are UTC night, recorded on the PC
  with the live clock correction.
