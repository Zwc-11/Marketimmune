# Pre-registration: 24-hour live confirmation of the gap-pull quoters (from 2026-11-06)

Written 2026-11-06 at about 15:40 UTC, before the run it governs starts. Drafted by Claude at
Caesar's request ("keep doing the testing ... like we are in the real market"). The commit time is
the registration time; the run starts after it.

## Why

The first forward test (`paper-forward-test-20261106.md`) had all four candidates positive over
3.5 held-out hours (+$16 to +$61 an hour) but none past its rule. Its write-up said a second
registered run of 15-30 hours, unchanged, would settle it. This is that run.

## Run

- **Where:** Caesar's machine in Toronto, `scripts/run_paper_live.ps1`:
  `cli.paper_trade --hours 24 --segment-hours 2 --serve 8765 --web frontend/dist`.
  Hyperliquid's feed delay there is not known in advance; it is measured and reported.
- **Unchanged from the first test:**
  - the same nine coins;
  - 200 ms order latency, $1,000 quotes, 5-quote position cap;
  - 1.5 bp maker and 4.5 bp taker fee;
  - the fill model, and the four candidates' code (`marketimmune/paper/strategies.py` at this
    commit; `Improve` and `GapPull` behave exactly as at 659b94f).
- **Length:**
  - the first 24 hours of live data after the run starts;
  - hours lost to sleep, crashes or feed outages are excluded, reported, and made up by
    continuing until 24 hours exist;
  - if 24 hours cannot be collected within 72 hours of the start, the test is scored on what
    exists if it is at least 12 hours; under 12 hours there is no verdict.

## Hypotheses

- **Candidates (confirmatory):** `improve+gap@0.25`, `gap@0.25`, `improve+gap@0.5`, `gap@0.5`,
  each summed over the nine coins.
- **Rule, as before:** a candidate makes money if its total PnL is positive and the stationary
  bootstrap interval of its mean 15-minute block PnL (mean block 3, 5,000 draws, seed 0) excludes
  zero at 98.75% (Bonferroni for four).
- **Also reported, no claim:**
  - the same at the 0.8 bp tier;
  - each candidate against `touch` on the same blocks;
  - per coin, and by hour of day (UTC).

## Exploratory, no claims

The run also carries:

- the December strategies (`touch`, `gap@1`, `gap@2`, `model@0.5`, `model@1`, `improve`,
  `improve+gap@2`, `taker@6`, `taker@10`);
- eight strategies built on 2026-11-06 and screened on that night's recording
  (`eval/paper/advanced_screen_20261106.json`): `zgap@0.25`, `zgap@0.5`, `hawkes@2`, `hawkes@3`,
  `kelly@0.5`, `kelly@1`, `reservation@1`, `reservation@3`.

They were chosen after seeing the night, so their results here are reported as exploratory. The
screen's best, `zgap@0.25` (+$68 an hour over 4.7 recorded hours), would need its own registered
run.

## What will not be done

- No change to the candidates, settings, coins or fill model during the run. A bug fix that changes
  fills would end the test and be recorded here.
- No stopping or extending the run because of its results.
- No claim about real orders. Paper fills are not real fills.

## Deviations

(none)
