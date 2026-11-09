# Pre-registration: 10 bp deep quotes on the 50 wide-spread HIP-3 growth-mode markets

Written 2026-11-09 about 04:15 UTC. None of the test hours exists yet. None of the 50 markets'
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
