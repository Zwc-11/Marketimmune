# Pre-registration: live forward test of four quoting strategies (night of 2026-11-06)

Written 2026-11-06 at about 06:05 UTC, before any of the data it tests exists. Drafted by Claude
at Caesar's request ("test all the strategies you think can make money, really live"). The commit
time is the registration time.

## What was seen first (selection, disclosed)

- **Selection data:** the live paper run from 04:48 to about 06:00 UTC (`data/paper/seg2-*`, its
  first 70 minutes), replayed through `cli.paper_trade` with a grid of 17 + 10 strategies (gap pulls
  at 0.25-3 bps, model pulls at 0.1-2 bps, inside-the-spread quoting with and without the gap pull,
  gap takers at 4-10 bps) and three latency settings.
- **What it showed:** pulling a side whenever the demeaned Coinbase gap exceeds a small threshold was
  the only family near or above zero after the 1.5 bp maker fee: `gap@0.25` +1.81 bps per filled
  dollar (429 fills, USD/h interval [-37, +117]), `improve+gap@0.25` +1.31, `improve+gap@0.5` +0.16,
  `gap@0.5` -0.03. Every interval included zero. `touch` was -2.85.
- These four were chosen **because** of that result, from many tried. That is why they are tested
  here, on hours that did not exist when they were chosen.

## Test

- **Data:** the live segments that start after this file is committed (`seg3` onward), until the
  run ends on the morning of 2026-11-06. Live, not replayed. Same feeds, coins (BTC, ETH, SOL, XRP,
  LTC, BCH, LINK, AVAX, DOGE), 200 ms order latency, $1,000 quotes, 5-quote position cap, 1.5 bp
  maker fee and fill model as `docs/research/paper-trading.md`.
- **Candidates:** `gap@0.25`, `gap@0.5`, `improve+gap@0.25`, `improve+gap@0.5` (definitions in
  `marketimmune/paper/strategies.py` at this commit), summed over the nine coins.
- **Metric:** PnL in USD per 15-minute block, summed over coins, from the minute equity snapshots
  (`cli.paper_report`, `by_strategy`), marked to the mid at the end of each segment.
- **Rule:** a candidate **makes money in the forward test** if its total PnL is positive and the
  stationary-bootstrap interval of its mean block PnL (mean block 3, 5,000 draws, seed 0) excludes
  zero at 98.75%, Bonferroni for the four candidates. The 95% intervals are reported too.
- **Secondary, no claim:** the same at the 0.8 bp tier (re-priced: a fee moves no fill); each
  candidate against `touch` on the same blocks; per coin.

## What will not be done

- No change to the candidates, their thresholds, the coins or the settings after this commit.
- No dropping of coins, hours or segments because of their results. A segment lost to a crash is
  reported as lost.
- A result here is one night, one market state and a paper fill model. It is not a claim that the
  strategy makes money with real orders; that would need a second registered night at least, and real
  fills.

## Deviations

(none)
