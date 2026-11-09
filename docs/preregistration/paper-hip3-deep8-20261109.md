# Pre-registration: 8 bp deep quotes on HIP-3 growth-mode markets, weekday hours

Written 2026-11-09 about 00:40 UTC, before any test hour is recorded. Scored once.

## Where this comes from

**The setting:** `hush@d=8/quiet=0/tol=0.3`, a bid and an ask 8 bp from Hyperliquid's mid on each
market, passive only, with no wallet gate (`quiet=0`). A resting order stays while it is within
0.3 × 8 = 2.4 bp of its target, so it keeps its place in the queue.

**The evidence so far:** the cloud's HIP-3 recording of 2026-11-08 00:24–12:05 UTC, a Sunday (11.7 h).
- **Selection window** (00:22–02:00, 1.6 h): +$13.53/h.
- **First registered test's window** (02:20–05:20, 3 h): +$6.66/h [+1.48, +12.88]. This setting
  was reported there, not registered; the registered gated one failed
  (`paper-hip3-20261108.md`).
- **All 11.7 h as recorded** (`eval/paper/latency/hip3_here_report.json`, exploratory; it includes
  both windows above): +$6.11/h [+0.44, +11.60].
  - $23k filled an hour; 0.35 orders per filled $; worst drawdown −$28.
  - Per filled $: +2.66 bp. Spread +6.42, move in 1 s −5.23, position +1.78, fee −0.30.
- **Concentration:** two-thirds of the 11.7 h total came from `xyz:ANT` and `io:ANTH`, the two
  pre-IPO Anthropic markets. Without them it made +$1.96/h.
- **Selection effects:** this setting was one of six reported together in each window, and it is
  picked here after seeing them. The true value is likely lower than the evidence.

**What is new in this test: weekday hours.** All evidence is from a weekend, when the equity
oracles barely move. On Monday the oracles follow live stock prices from the US open at 14:30 UTC.

## Registered

**Strategy and settings:**
- `hush@d=8/quiet=0/tol=0.3` on the 32 growth-mode markets of `scripts/run_paper_hip3.ps1`; no
  market is dropped after seeing the test;
- maker 0.3 bp, taker 0.9 bp;
- $250 × 4 quotes a market, $5,000 budget, 200 ms order latency;
- `paper_tune` replay, receive times corrected from Coinbase timestamps (`--clock test
  --causal-clock`).

**Test data:** Caesar's PC's `live-hip3` run (`G:\Crypto Data\paper\live-hip3`, started
2026-11-08 21:27 UTC, 168 h).
- **Hours:** the first eight 2-hour segments that start after this commit, from
  `seg-20261109T0128`: about 01:28–17:30 UTC on Monday 9 November, 16 h.
- **Warm-up:** `seg-20261108T2127` and `seg-20261108T2328`, replayed first and not scored. Neither
  has been looked at.
- **If the run stops early:** the test uses the segments recorded after this commit, if they add
  up to at least 8 h. With fewer, it is not scored until a restarted run supplies 16 h recorded
  after this commit.

**Primary (P1):** the setting makes money over the test hours: $ an hour > 0, with the
stationary-bootstrap 95% interval above zero (`paper_report`: 15-minute blocks, mean block 3,
5,000 draws, seed 0).

**Reported regardless:**
- **Other settings on the same hours:** `hush@d=8/quiet=5/tol=0.3`, `mm@8`, `mm@5`, `zgap@0.05`
  and `touch`.
- **Paired comparison:** the pick paired with `touch`.
- **Without `xyz:ANT` and `io:ANTH`.**
- **Split** before and after the US open (14:30 UTC).
- **Per filled $:** spread, move in 1 s, position, fee.
- **Fill markouts** at 1 s, 60 s, 5 min and 30 min.
- **By market.**
- **Orders per filled $** against the rate limit.
- **Risk:** the largest position and the worst drawdown.
- **The pick retimed** (exploratory, `--retime`) at a total delay of 300 ms and 200 ms: what a
  Tokyo server could buy.

## Power and limits

**Power.** Over 11.7 h the interval was about ±5.6 $/h, so over 16 h it is about ±5. A true +$6/h
would pass a little over half the time. The weekend-to-weekday change and the selection effects
both push the true value below +6.

**Limits:**
- **Paper fills:** they don't move the book, and nobody can step in front of them.
- **One location:** the PC's feed is about 300 ms behind block time.
- **The fee:** the `io:` markets' growth-mode fee is assumed equal to trade.xyz's.
- **Concentration:** if the pair carries the result again, it is a bet on one underlying.
- **Capacity:** $250 quotes.

## Correction (2026-11-09 about 01:35 UTC, before any test segment was read)

The evidence recording was first described as 13 h (00:00–13:00 UTC). The replay covers
00:24–12:05 UTC, 11.7 h; the text above now says so. Nothing registered changed.

## Result (2026-11-09 about 19:00 UTC)

**Data.** The PC's `live-hip3` segments `seg-20261109T0129` to `seg-20261109T1334`, 01:29 to
15:31 UTC on Monday 9 November, 13.9 h. Warm-up was `seg-20261108T2127` and `seg-20261108T2328`.
Settings as registered (`eval/paper/hip3/test_deep8_*`).

**Deviations, both covered by the registration's own rules:**
- **Segment name:** the first test segment is `seg-20261109T0129`, not `…0128` as written above.
  The rule ("the first eight segments that start after this commit") picks the same segment.
- **Seven segments, not eight:** the run stopped at 15:31 UTC, when the 50-market run
  (`live-hip3-wide`) started. 13.9 h is above the 8 h minimum, so the test is scored on these.

**Verdict.** **P1 fails.** `hush@d=8/quiet=0/tol=0.3` made −$36.49/h [−81.96, −4.52]. The whole
interval is below zero.

| Setting | $/h [95%] | Filled $/h | bp per filled $ | Spread | Move in 1 s | Position | Orders per $ |
|---|---|---:|---:|---:|---:|---:|---:|
| `hush@d=8/quiet=0` (registered) | −36.49 [−81.96, −4.52] | 118,332 | −3.08 | +1.98 | −4.43 | −0.33 | 0.26 |
| `hush@d=8/quiet=5` | −8.22 [−20.28, +3.04] | 28,949 | −2.84 | +3.01 | −4.49 | −1.06 | 0.65 |
| `mm@8` | −29.15 [−47.40, −15.20] | 154,677 | −1.89 | +1.75 | −2.91 | −0.36 | 0.50 |
| `mm@5` | −63.87 [−89.28, −43.64] | 314,377 | −2.03 | +0.58 | −1.99 | −0.29 | 0.35 |
| `zgap@0.05` | −172.30 [−264.00, −108.92] | 941,131 | −1.83 | −0.48 | −0.89 | −0.16 | 0.08 |
| `touch` | −498.64 [−773.80, −318.80] | 2,833,802 | −1.76 | −0.34 | −0.97 | −0.15 | 0.08 |

**Reported regardless:**
- **The pick paired with `touch`:** +$459.15/h [+305.52, +693.88], better in 56 of 56 blocks. It
  lost far less than quoting at the touch.
- **Without `xyz:ANT` and `io:ANTH`:** −$37.04/h. The pair made +$0.53/h (`io:ANTH` +2.64,
  `xyz:ANT` −2.11).
- **Before and after the US open** (by equity change in each window):
  - 01:29–14:30 UTC, 12.8 h: −$16.44/h;
  - 14:30–15:31 UTC, 1.0 h: −$291.18/h.
- **Fill markouts before the fee, bp:** −2.45 at 1 s, −2.98 at 60 s, −1.91 at 5 min, −3.10 at
  30 min. On Sunday the same setting's fills were +1.18 at 1 s, +0.78 at 60 s, +1.87 at 5 min and
  +2.65 at 30 min.
- **By market:**
  - It lost on 24 of 32 markets; most on `xyz:SOXL` (−$5.78/h), `xyz:SNDK` (−$4.94) and
    `xyz:MRVL` (−$3.52).
  - `io:ANTH` (+$2.64) and `xyz:SKHX` (+$1.37) were the largest gains.
  - `xyz:SP500`, `xyz:XYZ100`, `xyz:JPY` and `xyz:SILVER` never filled.
- **Orders per filled $:** 0.26, within the rate limit.
- **Risk:** the largest gross position was $9,868; the worst drawdown −$525.70.

**Sensitivity** (not registered; from the 2026-11-09 audit, `claude/hush-d10-check-2026-11-09.md`):
- **Closing each segment's leftover positions** through the last book seen, plus the taker fee:
  $6.61 over the 13.9 h, about −$0.5/h more.
- **Capped through-fills** (`--cap-through-fills`: a trade through a quote fills at most its own
  size): −$43.53/h [−95.00, −8.16] on $104k filled an hour; `mm@8` −$25.57.
- **Retimed, as from a faster server** (exploratory, registered as reported): total delay 300 ms
  −$16.26/h [−42.00, +4.80]; 200 ms −$7.26 [−25.84, +11.88]. Speed cuts the loss but does not turn
  it positive.

**Reading:**
- **The weekend edge does not survive a weekday.** On Sunday the equity oracles barely moved, and
  8 bp quotes filled mostly when takers overshot.
- **On Monday the same quotes filled five times as much,** on moves that kept going: the fills
  were behind at every horizon.
- **The Anthropic pair,** with no listed stock behind it, was about flat.
