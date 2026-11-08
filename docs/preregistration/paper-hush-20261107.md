# Pre-registration: the quiet-depth maker, `hush@` (2026-11-07, night)

Written 2026-11-07 about 22:30 UTC. The commit time is the registration time. No hour after
2026-11-07 20:00 UTC has been replayed with `hush@`. Drafted by Claude at Caesar's request for a
market-making strategy built on this project's own results rather than a textbook one:
> "the Market making strategy you gave me is literally the one that I saw online before, it's not
> unique, new ideas, and new perspective that based on our project research results."

## The idea, from the project's own data

**A1/A4's wallet score** (`paper/signals.py`, `Wallets`) gives each taker wallet a shrunk mean
10 s markout. It is shared across coins and updated live from the trade feed. It comes from a
check on 39.5 recorded hours (300k taker events, 27k wallets):
- **The top tenth of wallets** by score cost the maker −2.07 bp at 10 s. The bottom 80% pay the
  maker +0.1 to +0.3 bp.
- **Deep prints** (at least 1 bp from the mid) earned +1.52 bp at 30 s [1.06, 1.86] when no wallet
  scoring at least 1.3 bp, with at least 5 scored takes, had taken the coin in the last 5 s. Both
  halves of the sample agree (+1.66 / +1.13).
- **A1's lead time:** an informed wallet's toxicity decays over about 100 blocks (7 s).

**The rule** (`hush@d=<bps>/quiet=<s>/inf=<bps>/n=<takes>`):
- Rest a bid and an ask `d` bp from Hyperliquid's mid, passive only (never through the touch).
- Quote only while no informed wallet (score ≥ `inf`, with ≥ `n` scored takes) has taken the coin
  for `quiet` seconds. Otherwise quote nothing.
- The shared risk layer, latency, queue and fills of the engine apply, as for every quoter.

## Selection (all of it before this registration)

- **Replays:** `cli.paper_tune`, causal clock, $250 × 4 quotes, $5,000 budget, 200 ms, fees
  1.5 / 4.5 bp.
- **Hours:** every recorded hour to 2026-11-07 20:00 UTC: 31.9 h scored. The 04:41 segment is
  warm-up only. The tuned and market-maker runs are one chain, so the wallet scores stay warm as
  in a live run.
- **Grids:**
  - `eval/paper/tune_hush_selection_20261107.{json,md}`: 6 settings.
  - `eval/paper/tune_hush_controls_20261107.{json,md}`: 8 settings, including the ungated control
    (`quiet=0`). `hush@d=3/quiet=5` is in both and reproduces exactly.
- **Fill markouts:** `eval/paper/hush_markouts_20261107.csv`.

### Results within Hyperliquid's order-rate limit

$ an hour [95%], per filled $ in bp (`cli.paper_report`):

| Setting | $/h [95%] | Orders per $ | Total bp | Spread | Move in 1 s | Position |
|---|---|---:|---:|---:|---:|---:|
| `hush@d=1/quiet=5` | −19.64 [−26.12, −13.40] | 0.18 | −2.91 | +0.16 | −1.34 | −0.23 |
| `hush@d=2/quiet=5` | −6.15 [−9.12, −3.40] | 0.32 | −2.21 | +0.55 | −1.79 | +0.54 |
| `hush@d=2/quiet=30` | −2.92 [−5.28, −0.40] | 0.36 | −1.47 | +0.59 | −1.81 | +1.25 |
| `hush@d=3/quiet=0` (no gate) | −3.78 [−7.12, −0.60] | 0.44 | −2.34 | +0.97 | −2.35 | +0.55 |
| `hush@d=3/quiet=5` | +0.51 [−2.04, +3.12] | 0.50 | +0.38 | +1.08 | −2.40 | +3.20 |
| `hush@d=3/quiet=30` | +1.54 [−1.32, +4.64] | 0.55 | +1.54 | +1.12 | −2.36 | +4.28 |
| `hush@d=3/quiet=5/inf=0.665` | +1.61 [−0.92, +4.20] | 0.59 | +1.44 | +1.11 | −2.46 | +4.30 |
| **`hush@d=4/quiet=5`** | **+1.92 [−0.92, +4.72]** | 0.74 | +2.56 | +1.62 | −3.08 | +5.52 |
| `zgap@0.05` (running live) | −3.93 [−7.36, −0.52] | 0.36 | −0.89 | +0.23 | −0.36 | +0.74 |

All settings use `tol=0.3`. Over the rate limit, and not selectable:
- `hush@d=5/quiet=5`: +1.99, at 1.06 orders per $.
- The Coinbase-gap-gated variants (`z=0.05`): +2.2 to +2.6, at 3.2–3.7 orders per $.

**The gate, paired on the same blocks** (gated minus `hush@d=3/quiet=0`, 130 fifteen-minute blocks):

| Gated setting | $/h better [95%] | Blocks better |
|---|---|---|
| `quiet=5` | +4.22 [+1.60, +7.52] | 82/130 |
| `quiet=30` | +5.22 [+2.08, +9.24] | 70/130 |
| `quiet=5/inf=0.665` | +5.29 [+2.64, +8.76] | 85/130 |

### What the selection says, before the test

1. **The wallet gate works.** On the same 3 bp quotes, it turns −$3.78/h into +$0.5 to +1.6/h. The
   interval is above zero at every gate setting. The fills' markout against the fill price
   improves at every horizon:

   | Horizon | Ungated | `quiet=5` |
   |---|---:|---:|
   | 60 s | −2.40 bp | −2.10 bp |
   | 30 min | −4.27 bp | −2.75 bp |

2. **The fills themselves still lose before the fee, at every horizon up to 30 minutes.** For
   `hush@d=4/quiet=5`, the markout is −1.46 bp at 1 s, −2.34 at 60 s, −3.56 at 5 min and −2.23 at
   30 min.
   - The positive total comes from positions held longer than that. Deep quotes on both sides
     build a position against large moves. In these range-bound hours the moves came back within
     the hour: the same reversion as the band test (gross +2.4 bp per round trip,
     `paper-range-20261107.md`).
   - In a trending market the same rule would hold the losing side.
3. **The trade-level +1.52 bp does not carry over to a resting quote.**
   - At 200 ms, a quote d bp from the mid is filled mostly by moves that slide to it over several
     blocks, not by single-print sweeps. For `hush@d=3/quiet=5`, 701 of 1,970 fills came less
     than 0.5 bp from the mid of the block before.
   - The fills preceded by a 2 bp+ move toward the quote in the previous 300 ms lose −3.0 bp at
     30 s. Those with no such move lose −0.6 bp.
4. **Selection bias.** 13 settings were tried. The pick is the best of the 9 within the rate limit.
   The interval of each is about ±2.8 $/h, so the test should be expected to come in below +1.9. The left-out
   (cross-validated) value is +1.3, and the folds do not all pick the same setting.

**Registered:** `hush@d=4/quiet=5/tol=0.3`, the best within the rate limit over all selection hours.

## Test hours

**The market-maker run's segments on Caesar's PC that start after this commit:** 2026-11-07 23:20
to 2026-11-08 15:20 UTC, eight 2-hour segments (16 h).
- **Interim, descriptive only:** after the first four segments (23:20–07:20). It is reported, and
  it decides nothing.
- **Final:** all eight segments, scored once.
- **If the recorder stops early,** the final uses the segments recorded by 2026-11-08 16:00 UTC,
  and the write-up says how many hours that is.

**Replay:**
- One chain: the selection's tuned chain and the 21:20 segment as warm-up only (not scored), then
  the test segments.
- Same settings as the selection: causal clock, $250 × 4, $5,000 budget, 200 ms, fees 1.5 / 4.5 bp.
- **Strategies:**
  - `hush@d=4/quiet=5/tol=0.3` (registered);
  - `hush@d=4/quiet=0/tol=0.3` (its ungated control);
  - `hush@d=3/quiet=5/tol=0.3` and `hush@d=3/quiet=0/tol=0.3` (the selection's control pair);
  - `zgap@0.05` (baseline).

## Primary criteria

Both use the stationary-bootstrap 95% interval (15-minute blocks, mean block 3, 5,000 draws, seed 0).

- **P1, the strategy:** `hush@d=4/quiet=5/tol=0.3` makes money: $ an hour > 0, with the interval
  above zero.
- **P2, the project's claim:** the wallet gate adds value. `hush@d=3/quiet=5/tol=0.3` minus
  `hush@d=3/quiet=0/tol=0.3`, paired on the same blocks, is > 0 with the interval above zero.
  This is the pair measured in selection (+4.22 [+1.60, +7.52]).

## Reported regardless

- **Paired comparisons:**
  - the registered setting against its own ungated control (not run in selection);
  - the registered setting against `zgap@0.05`.
- **Per filled $:** spread, move in 1 s, position, fee.
- **Fill markouts:** at 1 s, 60 s, 5 min and 30 min, before the fee.
- **By coin.**
- **Orders per filled $** against the rate limit.

## Power

- **P1:** the selection's interval over 31.9 h is about ±2.8 $/h. Over 16 h it is about ±4. P1
  needs the test to come in well above the selection's +1.9, so a pass is unlikely even if the
  edge is real.
- **P2:** better placed. A paired effect the size of the selection's (+4.2) would roughly reach
  its bound over 16 h.
- **A fail on P1 with a pass on P2** would mean: the wallet score keeps the maker out of informed
  flow, but the base fee still takes the rest.

## Addendum A: the clock fix and the pick that follows (written 2026-11-07 about 22:45 UTC, before any test hour is recorded)

**Error in the selection above.** `paper_tune --clock` takes one comma-separated list. The
replays above passed `--clock live --clock tuned`, so only the last value counted, and the 16:06 and
18:06 segments of 2026-11-06 (the "live" chain, 3.5 h) ran without the PC's clock correction.
That PC clock was 223-345 ms fast then, which turns 200 ms of order latency into 420-550 ms.
Both grids' live chain was replayed again with `--clock live,tuned`; nothing else changed. The
corrected files replace the ones above:
- `eval/paper/tune_hush_selection_20261107.{json,md}`, `tune_hush_controls_20261107.{json,md}`;
- `eval/paper/tune_hush_selection_report_20261107.json`, `tune_hush_controls_report_20261107.json`;
- `eval/paper/hush_markouts_20261107.csv`.

**Corrected, within the rate limit** (31.9 h; $ an hour [95%]; per filled $ in bp):

| Setting | $/h [95%] | Orders per $ | Total bp | Spread | Move in 1 s | Position | Gated minus `hush@d=3/quiet=0` [95%], blocks better |
|---|---|---:|---:|---:|---:|---:|---|
| `hush@d=1/quiet=5` | −18.72 [−24.56, −13.00] | 0.19 | −2.90 | +0.22 | −1.38 | −0.24 | - |
| `hush@d=2/quiet=5` | −5.23 [−8.08, −2.64] | 0.34 | −1.96 | +0.64 | −1.86 | +0.76 | - |
| `hush@d=2/quiet=30` | −2.95 [−5.36, −0.36] | 0.38 | −1.52 | +0.66 | −1.84 | +1.15 | - |
| `hush@d=3/quiet=0` (no gate) | −2.57 [−5.92, +0.56] | 0.46 | −1.68 | +1.08 | −2.43 | +1.17 | - |
| `hush@d=3/quiet=5` | +1.06 [−1.72, +3.88] | 0.53 | +0.84 | +1.21 | −2.46 | +3.60 | +3.57 [+1.16, +6.76], 82/130 |
| `hush@d=3/quiet=30` | +1.62 [−1.28, +4.76] | 0.57 | +1.68 | +1.23 | −2.37 | +4.32 | +4.12 [+1.12, +8.00], 69/130 |
| **`hush@d=3/quiet=5/inf=0.665`** | **+2.28 [−0.52, +5.12]** | 0.62 | +2.14 | +1.22 | −2.53 | +4.96 | **+4.77 [+2.24, +8.16], 84/130** |
| `hush@d=4/quiet=5` | +1.57 [−1.24, +4.32] | 0.79 | +2.20 | +1.72 | −3.18 | +5.16 | +4.06 [+1.28, +7.60], 76/130 |
| `zgap@0.05` | −2.71 [−5.40, +0.32] | 0.38 | −0.65 | +0.25 | −0.27 | +0.87 | - |

All settings use `tol=0.3`.

**Over the rate limit:**
- `hush@d=5/quiet=5`: +2.05, at 1.11 orders per $.
- The Coinbase-gap variants: +2.2 to +2.5 $/h, at 3.6-4.2 orders per $. Their intervals are above
  zero, and their fills' markouts are positive (about +0.3 to +0.9 bp at 1 s to 30 min). They send
  about four orders per filled $, so Hyperliquid's limit rules them out at this size.

**Fill markouts before the fee** (vs the fill price, bp):

| Setting | 1 s | 60 s | 5 min | 30 min |
|---|---:|---:|---:|---:|
| `hush@d=3/quiet=0` | −1.35 | −2.28 | −3.68 | −3.71 |
| `hush@d=3/quiet=5/inf=0.665` | −1.31 | −2.43 | −3.41 | −2.19 |
| `hush@d=4/quiet=5` | −1.46 | −2.66 | −4.37 | −2.80 |

The reading in "What the selection says" stands with the corrected numbers:
- the gate helps (every gated setting beats the ungated one, with the interval above zero);
- the fills lose before the fee up to 30 min;
- the total comes from positions held past that.

**The pick changes.** By the registered rule (best within the rate limit over all selection hours)
the pick is now `hush@d=3/quiet=5/inf=0.665/tol=0.3`: +2.28 $/h. Its left-out value is +2.3, and
the folds agree. The 0.665 bp threshold is the 80th percentile of wallet scores among wallets with
≥5 scored takes. This replaces `hush@d=4/quiet=5/tol=0.3` above, before any test hour exists.

**Registered from here:**
- **P1:** `hush@d=3/quiet=5/inf=0.665/tol=0.3` $ an hour > 0, with the interval above zero.
- **P2:** that setting minus `hush@d=3/quiet=0/tol=0.3`, paired, > 0 with the interval above zero.
  Selection: +4.77 [+2.24, +8.16].
- **Test replay strategies:**
  - `hush@d=3/quiet=5/inf=0.665/tol=0.3` (registered);
  - `hush@d=3/quiet=0/tol=0.3` (its ungated control);
  - `hush@d=4/quiet=5/tol=0.3` (the pick before this addendum, reported);
  - `hush@d=3/quiet=5/tol=0.3` (reported);
  - `zgap@0.05` (baseline).
- **The test replay passes `--clock live,tuned,test`.**

Test hours, interim, scoring and power are as above. The test chain is clock-corrected like the
tuned chain.

## Interim, descriptive only (2026-11-08 ~08:00 UTC)

**Deviation in the data source.** The market-maker run on the PC stopped at 23:33 UTC, when the live
`hush@` run started in its place. The live `hush@` run then stopped at 04:18, when the HIP-3 run
started.
- **What was used:** the market-maker run's 23:20–23:33 piece, then the live `hush@` run's own raw
  recording of the same nine majors and Coinbase feeds, 23:34–04:18. Same PC, same feeds, all of it
  recorded after the registration. 4.95 h in all.
- **Warm-up:** as registered, the tuned chain plus the 21:20 segment, not scored.
- **Files:** `eval/paper/test_hush_interim_report_20261108.json` (paired with the ungated control)
  and `test_hush_interim_vs_zgap_20261108.json`.

| Setting | $/h [95%] | Over `hush@d=3/quiet=0` [95%], blocks better |
|---|---|---|
| `hush@d=3/quiet=5/inf=0.665/tol=0.3` (registered) | −2.70 [−8.24, +1.68] | −0.96 [−3.32, +1.28], 11/20 |
| `hush@d=3/quiet=0/tol=0.3` (control) | −1.73 [−6.52, +2.68] | — |
| `hush@d=4/quiet=5/tol=0.3` | −2.37 [−5.56, +0.40] | −0.63 [−3.68, +1.84], 12/20 |
| `hush@d=3/quiet=5/tol=0.3` | −2.29 [−7.12, +1.92] | −0.55 [−1.80, +0.64], 10/20 |
| `zgap@0.05` | −4.46 [−11.16, +2.52] | — |

Every setting lost. The registered one had spread +1.50 bp, move in 1 s −2.43, position −0.90.

**Fill markouts before the fee** (`eval/paper/test_hush_interim_markouts_20261108.csv`):

| Setting | 1 s | 60 s | 5 min | 30 min |
|---|---:|---:|---:|---:|
| Registered | −0.94 bp | −1.30 | −2.90 | −1.18 |
| Ungated control | −0.85 bp | −0.89 | −2.74 | −1.25 |
| `zgap@0.05` | +0.10 bp | +0.06 | −0.35 | −0.14 |
The gate's paired gain from selection (+4.77) did not appear: −0.96 here. This interim decides
nothing. The final uses whatever majors data exist by 16:00 UTC; unless the majors run is
restarted, that is these same 4.95 h.

## Addendum B: data for the final score (written 2026-11-08 15:45 UTC, before the final replay)

The market-maker run stopped at 23:33 UTC and the live `hush@` run at 04:18, so neither covers the
registered window. A third run on the same PC, `live-optimized-20261107T192854Z` (port 8766,
started 19:28 UTC on 7 November by another session), recorded the same nine Hyperliquid perps and
Coinbase products the whole time, with clock correction.

**Final test data:**
- its eight segments `seg-20261107T2329` to `seg-20261108T1329`, 23:29 to 15:29 UTC, about 16 h,
  all recorded after the registration commit;
- **warm-up:** the registered chain (the selection's tuned chain and the market-maker run's 21:20
  segment, not scored), then the test segments;
- **settings and strategies:** as registered (`--clock test --causal-clock`, $250 × 4, $5,000,
  200 ms).

**Also reported:** the interim's 4.95 h, the market-maker run's 23:20–23:33 piece plus the `hush@`
run's own recording 23:34–04:18. It overlaps the first 4.8 h of the window above, so the two are
not independent.
