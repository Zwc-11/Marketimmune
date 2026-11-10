# Pre-registration: volatility-scaled deep quotes on HIP-3 markets, weekday hours

Written 2026-11-09 about 23:15 UTC. Every test hour is recorded after this commit. Scored once.

## Where this comes from

`docs/research/paper-trading.md`, "Why the deep quotes lose on weekdays, and three ideas tested".

- **The fixed 8 bp quotes failed on weekdays** (`paper-hip3-deep8-20261109.md`): −$36.49/h
  [−81.96, −4.52] on Monday 9 November.
- **The cause was measured:** 74% of the filled $ traded when the true mid was already within
  5 bp of the quote, all within 1 s of the move that brought it there. Fills that were still 8 bp
  or more away made +2.0 bp at 10 s.
- **The fix tried:** set the depth in units of each market's own 1 s volatility (`k`), so a jump
  cannot reach the quote inside the reaction time.
- **Selection** (Monday's 13.9 h and Sunday's 11.7 h, 32 markets; about a dozen settings tried, so
  these numbers are biased upward):

| `hush@…/quiet=0/tol=0.3` | Monday $/h [95%] | Monday edge per fill, 60 s | Sunday $/h | Sunday edge per fill, 60 s |
|---|---|---|---:|---|
| `d=8` (fixed) | −36.49 [−81.96, −4.52] | −3.28 [−4.66, −1.25] | +6.11 | +0.48 [−0.59, +1.50] |
| `d=8/k=6` | +2.90 [−18.76, +26.48] | −0.76 [−2.86, +1.07] | +4.34 | |
| `d=8/k=10` | +1.17 [−7.88, +10.68] | +1.05 [−3.35, +4.41] | +2.20 | |
| `d=12/k=10` (the pick) | +2.89 [−8.04, +16.12] | +3.41 [−0.66, +6.95] | +2.77 | +2.61 [+0.42, +4.41] |
| `d=8/k=14` | −4.70 [−14.80, +4.80] | | +1.18 | |

"Edge per fill" is the fills' $-weighted markout against the fill price, minus the 0.3 bp fee, in
bp (`scripts/flow/edge.py`).

- **Known weakness:** with orders 700 ms late instead of 200 ms and fills capped at each trade's
  size, the pick made −$2.44/h [−19.60, +12.84] on Monday, with an edge per fill of −0.45 bp
  [−7.39, +4.98]. On Sunday the same stress left it at +$2.73/h. The real order delay has not been
  measured.

## Registered

**Strategy and settings:**
- `hush@d=12/quiet=0/k=10/tol=0.3`: a bid and an ask at the larger of 12 bp and 10 times the
  mid's 1 s volatility (an average with a 5-minute half-life) from Hyperliquid's mid. Passive only,
  no wallet gate. A resting order stays while it is within 0.3 of that depth of its target.
- **Markets:** the 50 of `scripts/run_paper_hip3_wide.ps1`, no market dropped after the test. Four
  are among the 32 used for selection (`io:ANTH`, `io:NVDA`, `xyz:ANT`, `xyz:KORU`).
- **Settings:**
  - maker 0.3 bp, taker 0.9 bp;
  - $250 × 4 quotes a market, $5,000 budget, 200 ms order latency;
  - `paper_tune` replay with receive times corrected from Coinbase timestamps (`--clock test
    --causal-clock`), the engine's default fill rule.

**Test data:** the PC's `live-hip3-wide` recordings (`G:\Crypto Data\paper\live-hip3-wide`).
- **Hours:** the first 24 two-hour segments that start after this commit, about 48 h, from late
  Monday 9 November to late Wednesday 11 November UTC.
- **Warm-up:** the segment in progress at the commit, replayed first and not scored (it starts the
  volatility estimate).
- **If the run stops early:** what was recorded after this commit, if at least 30 h; with less,
  the test waits for a restarted run to supply the rest.

**Primary:** both must hold.
- **P1 (edge per fill):** the fills' $-weighted 60 s markout minus the 0.3 bp fee is above zero,
  with the 95% interval above zero (`scripts/flow/edge.py`: 15-minute blocks resampled, 5,000
  draws, seed 0).
- **P2 (money):** $ an hour > 0. Its interval is reported, not required.

**Reported regardless:**
- **Control:** `hush@d=8/quiet=0/tol=0.3` on the same hours, and the pick's edge minus the
  control's.
- **Sensitivity:** the pick with `--latency-ms 700 --cap-through-fills`, and the cost of closing
  each segment's leftover positions.
- **Mechanism:** the share of filled $ at 5 bp or more from the true mid at the fill
  (`scripts/flow/ourfills.py`).
- **Other settings:** `d=8/k=10` and `d=8/k=6`.
- **Split** by session: 14:30–21:00 UTC against the rest.
- **Per filled $:** spread, move in 1 s, position, fee.
- **By market,** orders per filled $, the largest position and the worst drawdown.

## Power and limits

**Power.** On Monday the pick had 546 fills in 13.9 h and an edge interval of about ±3.8 bp. Over
48 h on 50 markets the interval should be about ±2 bp. A true edge of +3 bp would pass P1 about
four times in five; +1 bp would not.

**Limits:**
- **Paper fills:** they don't move the book, and nobody can step in front of them.
- **Order latency is assumed,** not measured. The 700 ms sensitivity is reported because measured
  order round trips on Hyperliquid are longer than 200 ms (a median 884 ms from Tokyo, Glassnode).
- **Small numbers:** about $8k filled an hour in selection. $ an hour is mostly the PnL of a few
  positions, which is why the edge per fill is the first criterion.
- **Selection bias:** the pick was chosen from about a dozen settings tried on one weekday and
  one Sunday.
- **Overlap:** the first hours coincide with the last hours of `paper-hip3-wide-20261109.md`
  (10 bp fixed quotes). Each test is scored on its own criterion.

## Addendum, 2026-11-09 about 23:37 UTC (before any test segment was recorded)

Two things changed after the registration above was committed at 23:15 UTC. Neither the pick nor
the criteria change.

**1. Where the test data is recorded.** `live-hip3-wide` stopped at 20:54 UTC, before this
registration was written (5.4 h recorded; found at 23:17 UTC). The same 50 markets are being
recorded by an audited copy of the runner, in
`G:\Crypto Data\paper\live-hip3-audited-20261109T2056` (segments `seg-<start>-<id>`, started
20:55 UTC). That recording is the test data:
- **Hours:** the first 24 two-hour segments that start after this addendum's commit, about 48 h.
- **Warm-up:** the segment in progress at this addendum's commit (started 22:55 UTC).
- **Read so far:** file listings, the first two segments' `meta.json` and `manifest.json` (market
  list and settings), and the runner's log. No fills, prices or reports.
- The recording is scheduled to run until about 16 November 15:30 UTC.

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
