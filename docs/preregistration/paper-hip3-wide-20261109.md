# Pre-registration: 10 bp deep quotes on the 50 wide-spread HIP-3 growth-mode markets

Written 2026-11-09 about 04:00 UTC. None of the test hours exists yet. None of the 50 markets'
recordings has been read, apart from a 70-second live smoke test whose results were not looked at.
Scored once.

## Where this comes from

`docs/research/paper-trading.md`, "Searching the deep quotes" and "HIP-3 growth-mode markets".

- **Deep passive quotes made money on the 32-market weekend hours:**
  - **Selection (cloud, 11.7 h):** +$6.07/h at 10 bp, +$6.12 at 8 bp.
  - **Check (PC, 12:19–16:20 UTC, 3.7 h):** +$12.39/h [+4.56, +19.60] at 10 bp.
- **Concentration:** most of it was on the two Anthropic markets, which have no listed stock
  behind them and the widest spreads of the 32. Their fills beat their own price at every horizon
  from 1 s to 30 min.
- **The question here:** whether the same quotes pay on other markets with wide spreads, at
  weekday hours.

## Registered

**Strategy and settings:**
- `hush@d=10/quiet=0/tol=0.3`: a bid and an ask 10 bp from Hyperliquid's mid, passive only, no
  wallet gate. A resting order stays while it is within 3 bp of its target.
- **Markets:** the 50 of `scripts/run_paper_hip3_wide.ps1`. These are every growth-mode market with
  over $300k a day and an impact spread of 6 bp or more at 2026-11-09 03:00 UTC. No market is
  dropped after seeing the test.
- **Settings:**
  - maker 0.3 bp, taker 0.9 bp (growth mode, deployer fee scale 1.0 on xyz, io and para);
  - $250 × 4 quotes a market, $5,000 budget, 200 ms order latency;
  - `paper_tune` replay with receive times corrected from Coinbase timestamps (`--clock test
    --causal-clock`).

**Test data:** the PC's `live-hip3-wide` run (`G:\Crypto Data\paper\live-hip3-wide`, started by
`run_paper_hip3_wide.ps1`).
- **Hours:** the first eight 2-hour segments that start after this commit, 16 h. No warm-up: the
  setting uses no wallet scores. Positions start flat.
- **If the run stops early:** the test uses what was recorded after this commit, if it is at least
  8 h. With less, it waits for a restarted run's first 16 h after this commit.
- **If the run is not started by 2026-11-12 00:00 UTC,** this registration lapses unscored.

**Primary (P1):** the setting makes money over the test hours: $ an hour > 0, with the
stationary-bootstrap 95% interval above zero (`paper_report`: 15-minute blocks, mean block 3,
5,000 draws, seed 0).

**Reported regardless:**
- **Other settings:** `hush@d=6`, `hush@d=8` and `hush@d=12` (each `quiet=0/tol=0.3`), `mm@8` and
  `touch`, on the same hours.
- **Market groups:** the three markets with no listed stock behind them (`io:OAI`, `io:ANTH`,
  `xyz:ANT`) against the other 47.
- **Split by session:** US regular hours (14:30–21:00 UTC) against the rest.
- **Per filled $:** spread, move in 1 s, position, fee.
- **Fill markouts** at 1 s, 60 s, 5 min and 30 min.
- **By market.**
- **Orders per filled $.**
- **Risk:** the largest position and the worst drawdown.

## Power and limits

**Power.**
- On the 32 markets, 10 bp quotes' interval was about ±$7/h over 11.7 h and ±$7.5 over 3.7 h, so
  over 16 h it is about ±$4 to ±$6.
- These 50 markets have not been replayed, so their size is unknown.
- A result like the weekend's +$6 to +$12 would pass. One like the weekend without the Anthropic
  markets (+$2) would not.

**Limits:**
- **Paper fills:** they don't move the book, and nobody can step in front of them.
- **One location:** the PC's feed arrives about 300 ms after the block.
- **The fee:** growth-mode fees are assumed to be trade.xyz's on every dex.
- **The market list:** it is one moment's snapshot, taken in the Asia session of a Monday.
- **Multiplicity:** this runs beside the 32-market weekday test
  (`paper-hip3-deep8-20261109.md`). Two markets and some hours overlap. Each is scored on its own
  criterion, and the write-up reports both.

## Addendum, 2026-11-09 about 23:37 UTC (before any test segment was read)

**1. The run stopped early and was restarted.** `live-hip3-wide` recorded 5.4 h (15:31 to
20:54 UTC), under the 8 h minimum. An audited copy of the runner restarted the same 50 markets at
20:55 UTC, in `G:\Crypto Data\paper\live-hip3-audited-20261109T2056`. By the rule above, the
test is that run's first eight 2-hour segments, 20:55 UTC on 9 November to about 12:56 UTC on
10 November. The 5.4 h of `live-hip3-wide` are reported beside it and do not count.
- **Read so far:** file listings, the first two segments' `meta.json` and `manifest.json`, and
  the runner's log. No fills, prices or reports.

**2. The engine that scores it.** An audit of the paper engine finished the same evening (branch
`audit/hip3-20261109`). It found that the engine this registration names fills too much: a trade
through a quote filled the whole order, shrinking displayed size counted as cancellations ahead, a
quote beyond the recorded levels was first in line, and each segment started flat. All four
flatter deep quotes. So P1 is scored on the audited engine (branch `audit/hip3-20261109` at
`a1c3d11`), which decides the result, and the engine as registered (master at `e68c306`) is
reported beside it. Positions carry across segments, so "positions start flat" holds for the
first segment only.

**3. One more setting reported (added 23:45 UTC, before any test segment was read).** The audited
engine pulls a market's quotes when that market's own book has not changed for 3 s; the engine as
registered pulled them only when the whole feed was silent. Reported beside P1: `hush@d=10` with
`/stale=30` on the audited engine, replayed from the same recording. P1 is unchanged.

**4. Interim look (10 November, 01:47 UTC).** The runner's live view was opened at 4.9 h into the
test (segment 3). It showed each strategy's running PnL on the test hours. Nothing was replayed or
changed. The rule and the scoring are as above.

**Interruption (recorded 10 November, 02:39 UTC).** The runner was stopped at 02:33:50 UTC and
restarted into the same folder at 02:38:28 UTC, with positions and wallet scores carried
(`seg-20261110T023827-65c867b8`). So segment `seg-20261110T005608-825965b3` is 1.6 h, not 2 h, and
4.6 minutes are missing. A 75-second run on the earlier engine, 02:36:49–02:38:04 UTC, went to
`live-hip3-wide\seg-20261110T0236` and is not test data. The counting rule above is unchanged:
segments are counted as recorded, the short one included.

The first eight segments now end at about 12:38 UTC on 10 November (15.6 h of data).

## Result (scored 10 November 2026, from about 13:30 UTC)

**P1 fails: `hush@d=10/quiet=0/tol=0.3` made −$4.12 an hour [−10.72, +2.16]** on the audited
engine. It lost before the fee, too.

**Data.** The first eight segments of `live-hip3-audited-20261109T2056`, 20:55 UTC on 9 November
to 12:44 UTC on 10 November: 15.6 h, all 50 markets.
- All 100 files were checked against the PC by name and size.
- Three files of segment 3 end mid-stream (the runner was stopped at 02:33:50 UTC). The replay
  uses every whole line before the cut.

**Engines.** Audited: branch `audit/hip3-20261109`; its engine code is unchanged since `a1c3d11`
(`git diff` of `marketimmune/` is empty). As registered: `e68c306`. Both use the same replay
command, `--clock test --causal-clock`, 0.3 / 0.9 bp, $250 × 4, $5,000, 200 ms.

**Every setting on the test hours**, audited engine unless marked:

| Setting | $ an hour [95%] | Fills | Filled $ an hour | Spread | Move in 1 s | Position | Edge per fill, 60 s [95%] | Engine as registered |
|---|---|---:|---:|---:|---:|---:|---|---|
| `hush@d=10` (registered) | −4.12 [−10.72, +2.16] | 2,784 | 16,603 | +3.40 | −4.67 | −0.91 | −3.36 [−4.82, −1.90] | −11.57 [−23.12, −0.04] |
| `hush@d=10/stale=30` | −4.95 [−9.32, −1.12] | 1,587 | 9,760 | +3.04 | −5.36 | −2.46 | −4.43 [−7.73, −1.26] | |
| `hush@d=6` | −3.78 [−9.16, +1.44] | 5,459 | 32,037 | +2.27 | −3.72 | +0.57 | −2.66 [−3.82, −1.55] | −48.82 [−71.04, −28.72] |
| `hush@d=8` | −8.34 [−15.76, −1.64] | 4,064 | 24,218 | +2.49 | −4.09 | −1.54 | −3.75 [−5.11, −2.37] | −30.14 [−44.08, −16.20] |
| `hush@d=12` | +0.19 [−6.68, +6.92] | 2,502 | 15,668 | +4.07 | −4.64 | +0.99 | −3.37 [−5.84, −1.08] | −7.91 [−21.04, +5.72] |
| `mm@8` | −9.11 [−13.48, −4.84] | 5,402 | 38,647 | +0.94 | −1.87 | −1.03 | −1.98 [−3.10, −0.92] | −27.21 [−37.92, −15.88] |
| `touch` | −16.98 [−22.08, −11.92] | 10,796 | 65,486 | +0.74 | −2.65 | −0.38 | −2.72 [−3.30, −2.18] | −176.80 [−204.32, −148.48] |

All `hush@` rows are `quiet=0/tol=0.3`. Spread, move in 1 s and position are bp per filled $
before the fee. The edge per fill is the $-weighted 60 s markout less the 0.3 bp maker fee, with a
15-minute block bootstrap (`scripts/flow/edge.py`).

**Reported regardless (registered setting, audited engine):**
- **Market groups:** the three markets with no listed stock behind them made +$0.34 an hour
  (`io:ANTH` +0.90, `io:OAI` −0.13 on 5 fills, `xyz:ANT` −0.43). The other 47 made −$4.46.
- **Session:** only 4 minutes of the test (20:55–21:00 UTC) were in US regular hours. The split
  carries no information; the test is the Asia and Europe session.
- **Fill markouts before the fee:** −1.27 bp at 1 s, −3.06 at 60 s, −3.59 at 5 min, +0.96 at
  30 min.
- **By market** (`eval/paper/wide/audA_markets.csv`):
  - 14 markets positive, 20 negative, and 15 never filled.
  - `xyz:KORU` (−$1.74 an hour) and `xyz:KIOXIA` (−$1.69) are 83% of the loss.
  - Best: `io:ANTH` +$0.90 and `xyz:MINIMAX` +$0.76.
- **Orders and cancels per filled $:** 1.51. Hyperliquid allows one per $1 traded plus 10,000,
  so a new account could not keep it up.
- **Risk:**
  - largest position $945 in one market, $4,389 across markets;
  - worst drawdown −$83.80;
  - closing what was held at the end would have cost $1.72.

**On the engine as registered:**
- **Result:** the registered setting made −$11.57 an hour [−23.12, −0.04]. P1 fails on that engine
  too.
- **Fills:** it filled $2,283,652 against the audited engine's $258,914, 8.8 times as much.
- **Free closes:** closing each segment's leftover positions, which that engine does for free,
  would have cost $21.82 more ($1.40 an hour).

**The 5.4 h of `live-hip3-wide` (15:31–20:54 UTC on 9 November, US regular hours; not test data):**
- **Audited engine:** the registered setting made +$0.80 an hour [−10.72, +10.32], `hush@d=12`
  +$5.40 [−2.24, +12.44].
- **Engine as registered:** the registered setting made −$14.42 [−31.40, +2.24].

**Interim look.** At 4.9 h into the test, the runner's live board showed the registered setting at
+$2.28. The full replay is what scores.

**Reading.**
- **Fills:** 10 bp quotes on these 50 markets are filled by moves that keep going. They lose
  4.7 bp in the first second and 6.5 bp by the minute, against 3.4 bp of spread.
- **No setting has a positive edge per fill.** `hush@d=12`'s +$0.19 an hour comes from positions
  held for half an hour, not from its fills.

**Files:**
- `eval/paper/wide/`: reports, groups, markets, risk, markouts, edge and `wide_test.csv`.
- `scripts/wide/`: `score.py` and `table.py`.
