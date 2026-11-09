# Pre-registration: volatility-scaled deep quotes on HIP-3 markets while the underlying markets are closed

Written 2026-11-09 about 23:15 UTC, four days before the first test hour. Scored once.

## Where this comes from

`docs/research/paper-trading.md`, "Why the deep quotes lose on weekdays, and three ideas tested".

- **Deep fills pay when they are really deep.** On both Sunday 8 November and Monday 9 November,
  fills that were still 8 bp or more from the true mid made +2.0 bp at 10 s.
- **On Sunday most fills were like that.** With the fixed `hush@d=8/quiet=0/tol=0.3`, 73% of the
  filled $ traded 5 bp or more from the mid, and it made +$6.11/h [+0.44, +11.60] over 11.7 h
  (cloud recording, 32 markets) and +$9.13/h [−0.60, +18.60] over 3.7 other hours (PC recording).
- **On Monday most were not,** and the same setting made −$36.49/h [−81.96, −4.52].
- **The hypothesis:** with the stock and futures markets closed there are few jumps, so quotes
  stay deep until a sweep reaches them.
- **Which setting.** `hush@d=12/quiet=0/k=10/tol=0.3` (depth of 10 times the 1 s volatility, at
  least 12 bp) on Sunday's 11.7 h:
  - +$2.77/h [−3.00, +8.48], with an edge per fill of +2.61 bp [+0.42, +4.41] at 60 s;
  - with orders 700 ms late and fills capped: +$2.73/h [−3.68, +8.92], edge +1.78 bp
    [−1.32, +3.85].
  - Under the same stress the fixed 8 bp fell from +$6.11/h to +$1.84/h [−5.00, +8.16].
- **All the weekend evidence is one Sunday,** and both settings were picked on it.

## Registered

**Strategy and settings:**
- `hush@d=12/quiet=0/k=10/tol=0.3`, as in `paper-hip3-farsweep-20261109.md`: a bid and an ask at
  the larger of 12 bp and 10 times the mid's 1 s volatility from Hyperliquid's mid, passive only,
  no wallet gate.
- **Markets:** the 50 of `scripts/run_paper_hip3_wide.ps1`, no market dropped after the test. Four
  are among the 32 used for selection.
- **Settings:**
  - maker 0.3 bp, taker 0.9 bp;
  - $250 × 4 quotes a market, $5,000 budget, 200 ms order latency;
  - `paper_tune` replay with receive times corrected from Coinbase timestamps (`--clock test
    --causal-clock`), the engine's default fill rule.

**Test data:** the PC's `live-hip3-wide` recordings (`G:\Crypto Data\paper\live-hip3-wide`).
- **Hours:** every 2-hour segment that starts at or after 2026-11-14 00:00 UTC and ends by
  2026-11-15 20:00 UTC, about 44 h. CME futures are closed from Friday 22:00 to Sunday 23:00 UTC.
- **Why it stops at 20:00 UTC on Sunday:** on 8 November the fixed 8 bp quotes lost $88 between
  21:27 and 22:00 UTC, before the futures reopened. That is one observation; the cut is disclosed
  as chosen on it.
- **Warm-up:** the segment before the first test segment, replayed first and not scored.
- **Minimum:** at least 24 h of segments inside the window. With fewer, the test waits for the
  following weekend's same window.
- **If the run is not recording that weekend,** this registration moves once to the weekend of
  21–22 November and lapses after that.

**Primary:** both must hold.
- **P1 (edge per fill):** the fills' $-weighted 60 s markout minus the 0.3 bp fee is above zero,
  with the 95% interval above zero (`scripts/flow/edge.py`: 15-minute blocks resampled, 5,000
  draws, seed 0).
- **P2 (money):** $ an hour > 0. Its interval is reported, not required.

**Reported regardless:**
- **The fixed quotes:** `hush@d=8`, `hush@d=10` and `hush@d=12` (each `quiet=0/tol=0.3`), `mm@8`
  and `touch`, on the same hours.
- **Sensitivity:** the pick with `--latency-ms 700 --cap-through-fills`, and the cost of closing
  each segment's leftover positions (`scripts/search/exit_cost.py`).
- **Mechanism:** the share of filled $ at 5 bp or more from the true mid at the fill
  (`scripts/flow/ourfills.py`).
- **Market groups:** `io:OAI`, `io:ANTH` and `xyz:ANT` against the other 47.
- **Saturday against Sunday.**
- **Per filled $:** spread, move in 1 s, position, fee.
- **By market,** orders per filled $, the largest position and the worst drawdown.

## Power and limits

**Power.** On Sunday the pick had 276 fills in 11.7 h and an edge interval of about ±2 bp. Over
44 h on 50 markets it should be about ±1 bp. A true edge of +2 bp would pass P1 most of the time.

**Limits:**
- **Paper fills:** they don't move the book, and nobody can step in front of them.
- **Order latency is assumed,** not measured (200 ms; the 700 ms stress is reported).
- **Small numbers:** about $5k filled an hour in selection, so a pass means a few $ an hour on a
  $5,000 budget.
- **Selection bias:** the pick was chosen from about a dozen settings tried on one weekday and
  one Sunday.
- **One location:** the PC's feed arrives about 0.33 s after the block.

## Addendum, 2026-11-09 about 23:37 UTC (four days before the first test hour)

Two things changed after the registration above was committed at 23:15 UTC. Neither the pick, the
window nor the criteria change.

**1. Where the test data is recorded.** `live-hip3-wide` stopped at 20:54 UTC on 9 November. The
same 50 markets are being recorded by an audited copy of the runner, in
`G:\Crypto Data\paper\live-hip3-audited-20261109T2056`, scheduled to run until about
16 November 15:30 UTC. That recording, or a restart of it on the same 50 markets, is the test
data. The window, the warm-up and the minimum are as registered.

**2. The engine that scores it.** An audit of the paper engine finished the same evening
(`G:\Crypto Data\paper\audit-hip3-20261109`, in this repository as branch `audit/hip3-20261109`).
It found that the engine this registration names fills too much:
- a trade through a quote filled the whole order, whatever the trade's size;
- displayed size that shrank was counted as the queue ahead cancelling;
- a quote beyond the recorded book levels was treated as first in line;
- each 2-hour segment started flat, so leftover positions were closed for free.

All four flatter deep quotes. So:
- **Primary:** P1 and P2 are scored on the audited engine (branch `audit/hip3-20261109` at
  `a1c3d11`, which also carries `k`). It decides the result.
- **Also reported:** the same replay on the engine as registered (master at `ff481d8`).
- **Sensitivity:** `--cap-through-fills` no longer does anything, because the audited engine
  always caps a fill at its trade's size. The stress is `--latency-ms 700` alone.
- **Positions** now carry from one segment to the next. "The cost of closing each segment's
  leftover positions" becomes the cost of closing what is held at the end of the test.

**3. A limit that was not stated.** Hyperliquid allows an address one request per $1 it has
traded, plus 10,000. On the selection data the pick sent more than that: 1.2 orders per filled $
on the registered engine, and the audited engine fills less. The test reports orders and cancels
per filled $, and a pass on P1 and P2 with that number above 1 is a pass for the fills only, not for
a strategy a new account could run.

**4. One more setting reported (added 23:45 UTC, before any test segment).** The audited engine
pulls a market's quotes when that market's own book has not changed for 3 s (`stale`, default 3).
The engine as registered pulled them only when the whole feed was silent. In two Sunday selection
hours (02:00 and 06:00 UTC on 8 November) a market's book went unchanged for more than 3 s during
45% to 55% of the time, averaged over the 32 markets, so under the audited engine the pick is out
of the book for about half of a quiet market's hours. Reported beside the primary: the pick with
`/stale=30` on the audited engine. The primary is unchanged.
