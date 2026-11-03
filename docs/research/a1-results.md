# A1 results: do priority fees predict toxic flow? (BTC, ETH, SOL, Apr 25 to Oct 31 2026)

Pre-registered in `docs/preregistration/a1-speed-bids-2026.md`, committed as 56ec53e on
2026-11-01, before any model was trained on a 2026 date (the hash was 7a9577c until an
author-only history rewrite on 2026-11-02; trees and dates unchanged). No deviations from its rules.
- The execution-order fix to the trade-implied mid came before registration and is disclosed
  there.
- One implementation change during the run: while BTC trained, `compare_rungs` was changed to
  read only the columns it uses. Rerun on SOL's discovery days, the new version gives the same
  rows, intervals and p-values, with mean losses equal to the 16th digit.

    powershell -ExecutionPolicy Bypass -File .\scripts\run_a1.ps1 -Coins SOL     # then ETH, BTC
    powershell -ExecutionPolicy Bypass -File .\scripts\run_a1_secondary.ps1       # secondary analyses
    python -m marketimmune.cli.a1_report --dir eval/a1 --out eval/a1/a1_tables.md

`eval/a1/a1_tables.md` has every number below, generated from the JSON next to it.

## Design in brief

- **Fills:** one row per match from `node_fills_by_block`, maker's side.
- **Label:** the maker's 10 s markout from the trade-implied mid before the fill's block;
  `toxic = markout < -1 bp`.
- **Rungs:**

  | Rung | Features |
  |---|---|
  | `l0_trade` | Trade state: quotes implied by trades, flow, volume, volatility |
  | `l1_trade` | `l0_trade` + the Binance-Hyperliquid gap |
  | `l2_trade` | `l1_trade` + the taker's wallet score |
  | `l3_fee` | `l2_trade` + fee pressure on the hit side over 3, 10 and 30 blocks |
  | `l3_fee_placebo` | `l2_trade` + the same fee features from the opposite side |

- **Models:** a CatBoost classifier (Brier) and a LightGBM quantile ladder (pinball at τ = 0.1).
  Each tested day is trained on the 7 days before it.
- **Tested days:**
  - Confirmation: every day Sep 1 – Oct 31 except Oct 28 (60 days).
  - Discovery: 17 Wednesdays May 6 – Aug 26, exploratory.
- **Tests:** a Diebold-Mariano test on daily mean loss, Holm correction across the 12 tests per
  metric, a stationary-bootstrap interval, and the placebo condition. Both metrics must agree.

## Verdicts (confirmation, Sep 1 - Oct 31, 60 days)

All 30 runs (5 rungs × 2 models × 3 coins, 77 tested days each) passed their leakage checks.
Matched fills in the confirmation months: BTC 17.5M, ETH 9.3M, SOL 5.0M.

| Claim | Result |
|---|---|
| **Fees** predict the markout beyond the CEX gap and the wallet score (A2 in ≥ 2 coins) | **Not supported.** A2 held in no coin |
| **The plan's gate** (A1 in ≥ 2 coins) | **Fails.** A1 held in no coin, so the A2 workstream (action log, missed races) is cancelled, as the plan says |
| A3: the CEX gap adds to trade state | **Replicated in 3 of 3 coins** |
| A4: the taker's wallet score adds to the CEX gap | **Replicated in 3 of 3 coins** (December's confirmed H2, now on 2026 and BTC) |

Per coin. Positive means the richer rung has the lower loss. Each cell gives the mean daily
improvement [bootstrap 95%], the days improved, and the Diebold-Mariano p.

| Test | Coin | Brier ×1e-3 | Pinball τ = 0.1, bps |
|---|---|---|---|
| A1: fees, during CEX moves | BTC | -0.33 [-1.61, +0.90], 26/60, p 0.61 | -0.010 [-0.021, -0.001], 25/60, p 0.057 |
| | ETH | -0.49 [-1.52, +0.57], 20/60, p 0.36 | -0.001 [-0.015, +0.012], 36/60, p 0.91 |
| | SOL | -0.57 [-1.60, +0.50], 25/60, p 0.36 | -0.008 [-0.024, +0.006], 26/60, p 0.32 |
| A2: fees, all fills | BTC | -0.01 [-0.27, +0.23], 31/60, p 0.95 | -0.001 [-0.002, +0.000], 25/60, p 0.17 |
| | ETH | +0.17 [-0.11, +0.45], 35/60, p 0.25 | +0.002 [-0.001, +0.005], 36/60, p 0.21 |
| | SOL | +0.06 [-0.26, +0.39], 33/60, p 0.74 | -0.002 [-0.007, +0.003], 28/60, p 0.44 |
| A3: CEX gap | BTC | +24.0 [+22.8, +25.1], 60/60, p < 1e-4 | +0.047 [+0.042, +0.051], 60/60 |
| | ETH | +24.8 [+23.6, +26.1], 60/60 | +0.067 [+0.061, +0.073], 60/60 |
| | SOL | +28.1 [+26.6, +29.7], 60/60 | +0.075 [+0.064, +0.087], 59/60 |
| A4: wallet score | BTC | +6.8 [+5.7, +7.9], 58/60, p < 1e-4 | +0.015 [+0.012, +0.018], 59/60 |
| | ETH | +6.0 [+4.8, +7.3], 58/60 | +0.017 [+0.011, +0.023], 53/60 |
| | SOL | +6.8 [+6.0, +7.7], 60/60 | +0.042 [+0.031, +0.054], 59/60 |

Every A3 and A4 cell has a Holm-adjusted p below 1e-4. No A1 or A2 cell has the right sign with
an interval above zero.
- The closest to a result is BTC's A1 pinball, and it goes the wrong way: the fee rung is
  slightly *worse* during CEX moves (interval below zero, p 0.057, Holm 0.34).
- The placebo condition would have blocked A1 and A2 on pinball anyway, for BTC
  (`taker_liquidation`, p 0.035) and ETH (`quiet`, p 0.063). It is not needed: no cell passes
  the other rules.

**Loss levels** (confirmation, mean daily Brier; `l0` → `l1` → `l2` → `l3_fee` / placebo):

| Coin | `l0_trade` | `l1_trade` | `l2_trade` | `l3_fee` | `l3_fee_placebo` |
|---|---:|---:|---:|---:|---:|
| BTC | 0.2123 | 0.1884 | 0.1816 | 0.1816 | 0.1815 |
| ETH | 0.2224 | 0.1975 | 0.1915 | 0.1914 | 0.1914 |
| SOL | 0.2229 | 0.1948 | 0.1880 | 0.1879 | 0.1879 |

The model confidence set (α = 0.10) keeps `l2_trade`, `l3_fee` and the placebo together in
every coin and on both metrics, and excludes `l0_trade` and `l1_trade` everywhere.

**Discovery (17 Wednesdays, May-Aug, exploratory)** gives the same picture: A1 and A2 hold
nowhere, A3 and A4 everywhere (`eval/a1/a1_discovery_exploratory.json`).

## Reading

- **The raw fee pattern is real, but it is not new information.**
  - Makers hit by fee-paying takers lose far more: 2-4 bps band -5.6 to -6.5 bps at 10 s,
    against -0.2 to -0.3 for no fee (`docs/research/priority-fees.md`).
  - The lead-time curve below shows the warning fading over a few seconds.
  - Once the model knows how far Binance has moved since the quote (the CEX gap) and who the
    taker is (the wallet score), the fees in the last 3-30 blocks add nothing measurable, in any
    coin or regime.
  - Takers pay for priority when a quote is stale and they know it, and those two features
    already measure that. This is A.4's reading ("the fee is a lower bound on how stale
    the quote was"), and A1 shows the bound carries no information beyond the staleness itself.
- **The opposite-side placebo is as good as the real fee features.** In the confidence set the
  three cannot be told apart. Whatever the fee rung picks up is common to both sides, such as
  general activity, not the side-specific race the plan described.
- **The replications are the strongest results in the project so far.**
  - The CEX gap cuts Brier by 0.024-0.028 on every one of 60 days in all three coins.
  - The wallet score cuts it by a further 0.006-0.007.
  - This holds on BTC, which no earlier test covered, and on the 2026 market with priority fees.
- **Consequence for the plan.** The gate failed, so A2 (the action log and missed races) is
  cancelled. Speed bids are not a separate toxicity signal for a maker on these coins.

## Secondary

**Lead time** (plan A.5 test 4, `eval/a1/lead_time.json`). This is the maker's 1 s markout from
the pre-fill mid, by blocks since a fee-paying taker last hit the same side; a block is 69-72 ms.
Each cell is the mean of daily means over the confirmation months. There is no model and no
CEX-gap control.

| Coin | 1 block | 2-3 | 4-10 | 11-30 | 31-100 | 101-300 | none in 300 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | -2.02 | -1.58 | -1.21 | -0.84 | -0.56 | -0.39 | -0.26 |
| ETH | -2.47 | -1.74 | -1.56 | -1.10 | -0.67 | -0.44 | -0.26 |
| SOL | -3.26 | -3.12 | -2.21 | -1.95 | -1.01 | -0.63 | -0.36 |

- The warning halves within 4-30 blocks for BTC and ETH (0.3-2 s) and within 31-100 for SOL
  (2-7 s). It is near the base rate after 100-300 blocks (7-22 s).
- 36-52% of confirmation fills come within 300 blocks of a fee-paying taker on the same side.
- The 10 s markouts and the discovery months show the same shape (in the JSON).

**Other losses** (`eval/a1/secondary/`, confirmation months). Each cell is the mean daily
improvement of the fee rung over `l2_trade` [95%], with the DM p.

| Coin | Regime | Log loss ×1e-3 | Pinball τ = 0.5, bps | Pinball τ = 0.9, bps |
|---|---|---|---|---|
| BTC | all | -0.17 [-0.80, +0.44], p 0.62 | -0.004 [-0.008, +0.000], p 0.096 | -0.001 [-0.003, +0.000], p 0.075 |
| BTC | cex_move | -0.30 [-5.43, +5.41], p 0.92 | -0.024 [-0.049, +0.003], p 0.099 | -0.007 [-0.016, +0.002], p 0.15 |
| ETH | all | -1.05 [-3.38, +0.60], p 0.32 | +0.001 [-0.003, +0.005], p 0.82 | -0.001 [-0.003, +0.001], p 0.51 |
| ETH | cex_move | **-6.81 [-14.07, -0.90], p 0.051** | +0.004 [-0.017, +0.029], p 0.76 | -0.000 [-0.009, +0.010], p 0.99 |
| SOL | all | -0.05 [-0.99, +0.86], p 0.92 | +0.000 [-0.004, +0.005], p 0.85 | -0.000 [-0.004, +0.003], p 0.81 |
| SOL | cex_move | -1.94 [-5.35, +1.78], p 0.33 | -0.006 [-0.034, +0.020], p 0.66 | -0.007 [-0.030, +0.012], p 0.55 |

- **The other losses agree.** The fee rung is never better than `l2_trade`.
  - The one interval that excludes zero is ETH's log loss during CEX moves, and it points the
    wrong way: the fee features make the classifier's probabilities worse there.
  - The placebo is null on every loss.
- **The replications hold on these losses too.**
  - The CEX gap improves log loss by 0.056-0.065 and every pinball level, on 59-60 of 60 days.
  - The wallet score improves log loss by 0.015-0.018 (58-60 days) and pinball at τ = 0.5.
  - At τ = 0.9 the wallet score's gain is small: +0.002 to +0.003 bps, on 38-41 days; SOL
    p 0.11. The wallet score is about the loss tail, not the gain tail.

**The 1 s and 60 s horizons** (`eval/a1/h1s/`, `eval/a1/h60s/`; `run_a1_secondary.ps1
-WithHorizons`, run 2026-11-03). The whole ladder retrained at each horizon and scored by the same
rules; secondary, so they cannot change the verdicts above. Tables in `eval/a1/a1_tables.md`.

| Test | 1 s | 10 s (primary) | 60 s |
|---|---|---|---|
| A1/A2: fees beyond the gap and wallet | 0/3 coins | 0/3 | 0/3 |
| A3: CEX gap | 3/3 | 3/3 | 3/3 |
| A4: wallet score | 3/3 | 3/3 | 2/3 (ETH fails pinball, Holm 0.22) |

- **Fees leave a trace at 1 s, on one metric only.** Brier, all fills: +0.48 to +0.51 ×1e-3 per
  day in every coin (Holm 0.00075 to 0.0072; BTC misses the rule because its placebo has p 0.098),
  about 2% of what the CEX gap adds at the same horizon. Pinball at τ = 0.1 shows it only for BTC
  (+0.001 bps). No coin passes both metrics, and at 60 s nothing is left. This matches the
  lead-time curve: what a fee says is gone within a few hundred milliseconds to a few seconds.
  This trace was found here, so it is not a result: it is re-tested on its own, on a month no
  model has seen (`docs/preregistration/jan-2027-confirmation.md`, J3).
- **The gap holds at every horizon; the wallet score fades faster.** The gap's Brier gain is
  21.7-26.9 ×1e-3 at 1 s and 5.7-6.4 at 60 s; the wallet score's is 10.2-14.2 at 1 s and 0.9-1.5
  at 60 s. Relative to the gap, the wallet score is worth 0.42-0.53 of it at 1 s, 0.24-0.28 at
  10 s and 0.17-0.23 at 60 s: who the taker is matters most in the first second.

## Limits

- Trade-implied mid, not a book. Its 10 s markout agrees with the rebuilt book in December 2025
  (correlation 0.95 SOL, 0.98 ETH), its 1 s markout less (0.78, 0.83).
- Executed takers only. Fees paid by takers that lost the race (A2's action log) are not seen.
- The fee features are notional-weighted pressure over 3-30 blocks. Other encodings were not
  tried, by design.
