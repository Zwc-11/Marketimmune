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
