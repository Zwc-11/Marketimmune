# Pre-registration: the tuned gap quoters at a $5,000 budget, 14 days live on paper (from 2026-11-06)

Written 2026-11-06 at about 20:30 UTC, before the run it governs starts. Drafted by Claude at
Caesar's request ("I only want to use $5000 in total", "implement and use optimization to find the
best variable value for each of the strategy"). The commit time is the registration time; the run
starts after it.

## Why

`cli.paper_tune` replayed every strategy family over a grid of its parameter on 8.19 hours of
2026-11-06: the night's segments 2-4 (cloud, clock correct) and the live run's first two segments
(Caesar's PC, clock corrected from Coinbase's timestamps). Every strategy had a $5,000 budget of
gross exposure over the nine coins. Only settings within Hyperliquid's order-rate limit (one order
request per USD filled) could be chosen (`eval/paper/tune_20261106.{json,md}`):

| Pick | Sizing | Orders per USD filled | In-sample $/h | Left-one-segment-out $/h |
|---|---|---:|---:|---:|
| `improve+gap@0.05` | $250 quotes, 4 a coin | 0.60 | +1.7 | +1.7 |
| `zgap@0.05` | $250 quotes, 4 a coin | 0.59 | +2.1 | +1.3 |
| `gap@0.1` | $250 quotes, 4 a coin | 0.71 | +1.8 | +0.6 |

All three made money on four of the five segments and lost $12-13 an hour on the choppy
16:06-18:06 UTC one. Their 15-minute block PnL has a standard deviation of about $6.3 against a
mean of about $0.45: 24 hours could not tell such an edge from zero (t about 0.7 if the mean held).
At the tuning's estimate, 14 days give t about 2.5. A smaller real edge will not pass.

## Run

- **Where:** Caesar's machine, `scripts/run_paper_tuned.ps1`, beside the 24-hour run (port 8766):
  `cli.paper_trade --hours 336 --segment-hours 2 --clock coinbase --quote-usd 250 --max-quotes 4
  --budget-usd 5000`, the model state carried between segments, the decision journal on.
- **Fixed:** the nine coins; 200 ms order latency on the corrected clock; 1.5 bp maker and 4.5 bp
  taker fee; the fill model and the strategies' code at this commit.
- **Length:**
  - 14 days (336 hours) of live data after the start;
  - hours lost to sleep, crashes or feed outages are excluded, reported, and made up by continuing,
    up to 21 days from the start;
  - at 21 days the test is scored on what exists if it is at least 7 days; under 7 days there is no
    verdict.
- Looking at the live view during the run is allowed. It does not stop or extend the run.

## Hypotheses

- **Candidates (confirmatory):** `improve+gap@0.05`, `zgap@0.05`, `gap@0.1`, each summed over the
  nine coins.
- **Rule:** a candidate makes money if its total PnL is positive and the stationary bootstrap
  interval of its mean 15-minute block PnL (mean block 3, 5,000 draws, seed 0) excludes zero at
  98.33% (Bonferroni for three).
- **Feasibility:** a candidate whose orders per USD filled exceed 1 over the test is reported as not
  runnable on Hyperliquid, whatever its PnL.
- **Also reported, no claim:**
  - each candidate against `touch` on the same blocks;
  - per coin, by hour of day (UTC), and by week;
  - the 0.8 bp fee tier.

## Exploratory, no claims

`hawkes@1.25`, `kelly@5`, `model@0.25` and `taker@25` (each family's best within the rate limit at
this sizing), `touch` (control), `improve`, and the 24-hour run's values `improve+gap@0.25`,
`gap@0.25`, `zgap@0.25` at this sizing. The reservation-price quoter is left out: at $250 quotes
every value tried sent 1.3-1.9 orders per USD filled.

## What will not be done

- No change to the candidates, settings, coins or fill model during the run. A bug fix that changes
  fills would end the test and be recorded here.
- No stopping or extending the run because of its results.
- No claim about real orders. Paper fills are not real fills.

## Deviations

(none)
