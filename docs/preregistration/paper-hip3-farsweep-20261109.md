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

**Interruption (recorded 10 November, 02:39 UTC).** The runner was stopped at 02:33:50 UTC and
restarted into the same folder at 02:38:28 UTC, with positions and wallet scores carried
(`seg-20261110T023827-65c867b8`). So segment `seg-20261110T005608-825965b3` is 1.6 h, not 2 h, and
4.6 minutes are missing. A 75-second run on the earlier engine, 02:36:49–02:38:04 UTC, went to
`live-hip3-wide\seg-20261110T0236` and is not test data. The counting rule above is unchanged:
segments are counted as recorded, the short one included.

The 24 test segments now end at about 00:38 UTC on 12 November (47.6 h of data).

## Result (scored 12 November 2026, from 01:30 UTC)

**Both criteria fail. P1: the pick's edge per fill is −6.75 bp [−14.22, −0.00]. P2: it made
−$0.37 an hour [−5.92, +4.96].** Audited engine, as addendum 2 requires.

**Data.** The runner stopped at 12:45:54 UTC on 11 November, partway through its 20th segment, and
recorded nothing after. 18 test segments exist: 00:57 UTC on 10 November to 12:45 UTC on
11 November, 35.3 h, all 50 markets. The rule for a run that stops early (at least 30 h) applies,
so the test is scored on those 18.
- Warm-up: `seg-20261109T225523-bfcba6ca`, replayed first and not scored.
- All 213 files (19 segments' raw files and `meta.json`) were checked against the PC by name and
  size.
- The last segment (1.75 h) has no `recording.json`, and its last files end mid-stream. The
  replay uses every whole line before the cut.

**Engines.**
- **Audited:** branch `audit/hip3-20261109`. Its engine code is unchanged since `a1c3d11`
  (`git diff` of `marketimmune/` is empty).
- **As registered:** `ff481d8`.
- **Replay command, both:** `--clock test --causal-clock`, 0.3 / 0.9 bp, $250 × 4, $5,000,
  200 ms, the 50 markets.

**Every setting on the test hours**, audited engine unless marked:

| Setting | $ an hour [95%] | Fills | Filled $ an hour | Spread | Move in 1 s | Position | Edge per fill, 60 s [95%] | Engine as registered |
|---|---|---:|---:|---:|---:|---:|---|---|
| `d=12/k=10` (the pick) | −0.37 [−5.92, +4.96] | 634 | 1,926 | +9.19 | −8.77 | −2.06 | −6.75 [−14.22, −0.00] | −4.12 [−14.24, +7.04] |
| `d=8` (control) | −6.33 [−10.52, −1.88] | 6,862 | 21,395 | +2.31 | −3.69 | −1.28 | −3.92 [−5.53, −2.33] | −39.74 [−63.88, −20.60] |
| `d=12/k=10/stale=30` | +0.78 [−4.48, +5.80] | 600 | 1,973 | +9.14 | −7.15 | +2.27 | +0.10 [−6.24, +4.89] | |
| `d=8/k=10` | −6.14 [−13.08, +0.28] | 793 | 2,403 | +8.07 | −7.57 | −25.74 | −3.59 [−10.31, +2.44] | −5.61 [−18.12, +9.04] |
| `d=8/k=6` | −3.60 [−9.64, +2.12] | 1,943 | 5,744 | +5.36 | −5.73 | −5.60 | −3.63 [−7.59, +0.06] | +2.18 [−5.80, +10.56] |
| `d=12/k=10`, orders 700 ms late | +0.73 [−3.88, +5.48] | 904 | 2,899 | +6.91 | −7.61 | +3.52 | −5.05 [−12.63, +1.51] | |

All rows are `hush@…/quiet=0/tol=0.3`. Spread, move in 1 s and position are bp per filled $
before the 0.3 bp fee. The edge per fill is the $-weighted 60 s markout less the fee, with a
15-minute block bootstrap (`scripts/flow/edge.py`). The pick's upper bound is −0.004 before
rounding.

**Reported regardless (the pick, audited engine):**
- **Against the control:**
  - $ an hour: +5.89 [−1.52, +13.04], better in 81 of 143 blocks (`paper_report --baseline`).
  - Edge per fill: −2.84 bp [−9.77, +3.76], paired on the same blocks
    (`scripts/flow/edge_diff.py`). The pick's fills were worth less than the control's.
- **Mechanism** (`scripts/flow/ourfills.py`): 62% of the pick's filled $ traded when the true mid
  was still 5 bp or more from the quote. That is against 28% for the control, and 26% for the
  fixed 8 bp quotes on Monday 9 November (earlier engine). The far fills lost anyway:
  - the 36% filled more than 12 bp from the mid made −5.97 bp at 60 s;
  - the 16% at 8–12 bp made −13.10 bp.
- **Fill markouts before the fee:** +0.42 bp at 1 s, −6.45 at 60 s, −9.48 at 5 min, −10.01 at
  30 min.
- **Session:** US regular hours (14:30–21:00 UTC, 6.5 h) −$0.76 an hour, the rest −$0.29.
- **By market** (`eval/paper/farsweep/A_markets.csv`):
  - 18 markets positive, 12 negative, 19 never filled.
  - `xyz:CRWV` lost $3.01 an hour, more than the whole loss.
  - Best: `xyz:ANT` +$1.00, `xyz:ARM` +$0.90, `xyz:KIOXIA` +$0.61.
  - The three markets with no listed stock behind them (`io:OAI`, `io:ANTH`, `xyz:ANT`) made
    +$1.49 an hour; the other 47 −$1.87.
- **Orders and cancels per filled $:** 6.01 (the control 1.43). Above 1, so by addendum 3 a pass
  would have been a pass for the fills only.
- **Risk:**
  - largest position $1,126 in one market, $5,920 across markets;
  - worst drawdown −$148.44;
  - closing what was held at the end would have cost $1.63.
- **Orders 700 ms late:** +$0.73 an hour [−3.88, +5.48], edge per fill −5.05 bp [−12.63, +1.51]. It
  filled half as much again (904 fills, $102,430) and earned less spread (6.9 bp). The dollars
  were positive from held positions (+3.5 bp per filled $), not from the fills.

**On the engine as registered:**
- **Result:** the pick made −$4.12 an hour [−14.24, +7.04], with an edge per fill of +1.76 bp
  [−0.65, +3.96]. Both criteria fail on that engine too.
- **Fills:** it filled $506,439 against the audited engine's $68,047, 7.4 times as much.
- **Against the control:** it beat it by +$35.45 an hour [+10.92, +66.92], because the control
  lost −$39.74 there.
- **Free closes:** closing each segment's leftover positions, which that engine does for free,
  would have cost $64.51 ($1.83 an hour).

**Against selection.** On Monday's hours replayed on the audited engine the pick made −$7.04 an
hour [−16.56, −0.08], with an edge of −4.0 bp [−14.84, +6.4] (`eval/paper/audit/deep_audit.csv`). A
fail was expected, and the test agrees.

**Reading.**
- **The volatility scaling works as built.** It moves the fills away from the mid: most of the
  pick's filled dollars traded with the mid still 5 bp or more away.
- **The fills it keeps are informed too.** On these 50 markets, a trade that reaches a quote 12 bp
  or more out is part of a move that keeps going. The fills lose 6 bp by the minute and 10 bp by
  half an hour, against 9 bp of spread.
- **What kept the dollars near zero** is that the pick barely traded: $1,926 filled an hour against
  the control's $21,395.
- **Weekend test:** `paper-hip3-weekend-20261109.md` is still to be scored. It needs the runner to
  be recording from 14 November 00:00 UTC.

**Files:**
- `eval/paper/farsweep/`: the reports (A: audited engine, R: engine as registered, L: audited
  engine at 700 ms), and by market, groups, risk, markouts, edge per fill, the paired edge
  difference, fill distance, exit costs and `farsweep_test.csv`.
- `scripts/farsweep/table.py`, `scripts/flow/edge_diff.py` and `scripts/wide/final_exit.py`.
