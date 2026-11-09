# Pre-registration: 8 bp deep quotes on HIP-3 growth-mode markets, weekday hours

Written 2026-11-09 about 00:45 UTC, before any test hour is recorded. Scored once.

## Where this comes from

**The setting:** `hush@d=8/quiet=0/tol=0.3`, a bid and an ask 8 bp from Hyperliquid's mid on each
market, passive only, with no wallet gate (`quiet=0`). A resting order stays while it is within
0.3 × 8 = 2.4 bp of its target, so it keeps its place in the queue.

**The evidence so far:** the cloud's HIP-3 recording of 2026-11-08 00:00–13:00 UTC, a Sunday.
- **Selection window** (00:22–02:00, 1.6 h): +$13.53/h.
- **First registered test's window** (02:20–05:20, 3 h): +$6.66/h [+1.48, +12.88]. This setting
  was reported there, not registered; the registered gated one failed
  (`paper-hip3-20261108.md`).
- **All 13 h as recorded** (`eval/paper/latency/hip3_here_report.json`, exploratory; it includes
  both windows above): +$6.11/h [+0.44, +11.60].
  - $23k filled an hour; 0.35 orders per filled $; worst drawdown −$28.
  - Per filled $: +2.66 bp. Spread +6.42, move in 1 s −5.23, position +1.78, fee −0.30.
- **Concentration:** two-thirds of the 13 h total came from `xyz:ANT` and `io:ANTH`, the two
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

**Power.** Over 13 h the interval was about ±5.6 $/h, so over 16 h it is about ±5. A true +$6/h
would pass a little over half the time. The weekend-to-weekday change and the selection effects
both push the true value below +6.

**Limits:**
- **Paper fills:** they don't move the book, and nobody can step in front of them.
- **One location:** the PC's feed is about 300 ms behind block time.
- **The fee:** the `io:` markets' growth-mode fee is assumed equal to trade.xyz's.
- **Concentration:** if the pair carries the result again, it is a bet on one underlying.
- **Capacity:** $250 quotes.
