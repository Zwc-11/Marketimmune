# Pre-registration: a range (band) maker on held-out hours (2026-11-07)

Written 2026-11-07 about 15:47 UTC, before the band maker is run on the hours it names. The
commit time is the registration time. Drafted by Claude at Caesar's request: "All the strategy are
losing money ... There's no volatility, it should be super easy to predict the range and making
money."

## Why every strategy loses (descriptive; fresh live hours 04:09-14:10 UTC)

Per filled dollar, from `paper_report` on the tuned run's five fresh segments:

| | spread earned | move in 1 s | position after | fee | total | break-even maker fee |
|---|---:|---:|---:|---:|---:|---:|
| `zgap@0.05` (running now) | +0.33 | -0.20 | +0.39 | -1.50 | -0.98 | 0.52 |
| `gap@0.1` | +0.25 | -0.43 | +0.54 | -1.50 | -1.14 | 0.36 |
| `touch` | +0.04 | -1.11 | -0.38 | -1.50 | -2.94 | -1.44 |

- **The fee does it:** every strategy's break-even maker fee is 0.6 bp or less, and the account pays 1.5.
- **Spreads are too narrow:** the median spread at a fill is 0.1 bp (BTC, SOL) to 1.8 bp (LINK).
  A maker round trip at the touch earns at most one spread and pays two fees (3 bp).
- **Prices trend within the minute:** Var(n s)/(n Var(1 s)) is 1.3-1.8 up to 60 s, so a touch fill
  is followed by a move against it.

## The hypothesis

Quiet markets do not move much, but they still range: the median hourly high-low range is 23 bp
(BTC) to 78 bp (BCH) over the recorded hours. Quoting far from the mid and holding for minutes
could earn a reversion larger than the 3 bp of fees.

What is known before this test (selection hours only unless stated):

- **Variance ratios, all recorded hours (computed before this split was written down):**
  - **1-minute returns are close to a random walk:** 5-30 minute variance ratios average 0.83-1.00.
    The shuffled-minute null averages 0.91-0.99, and no horizon passes a permutation test (p = 0.34 at 30 minutes).
  - **Weak evidence:** a range edge, if any, is weak evidence and needs its own test.
- **Band-maker sweep, selection hours** (2026-11-06 04:41 to 2026-11-07 04:09, 16.7 h;
  `eval/paper/range_sweep_selection_20261107.json`):
  - **Grid:** 96 settings.
  - **Best region:** a 60-minute centre, a 3-band stop, 120 minutes at most, and bands of 5.5-8
    one-minute sd. It earns +4 to +10 bp gross per round trip.
  - **Null on the same hours:** the same rule on three hour-shuffled copies earns −2 to +1 bp.
  - **Net:** after fees it makes $0.1-1.2 an hour at $500 a trade.
  - **Best of noise is as good:** the best of the 96 settings on a shuffled copy makes $0.8-1.3 an
    hour. The real best ($1.24) is no better.
  - **Reading:** the selection hours do not show an edge beyond what the number of settings can
    produce. This test is its one honest chance.

## The test

- **Hours:** 2026-11-07 04:09 to 15:19 UTC (11.2 h).
  - **Recorded by:** the tuned run on Caesar's PC; never used by any selection.
  - **Data:** the nine coins' `mids.parquet` of segments `live-tuned/seg-20261107T{0409,0609,0810,1010,1210,1410}`.
  - **Hash:** SHA-256 of their SHA-256 lines is `4496a8e5779da2b5337f225a58dc385503cc0f3dca41d9ef99eceb0c3247c80c`.
  - **Warm-up:** the run starts its averages 3 h earlier, using past data only.
- **Primary setting:** `band@k=1/h=60/c=60/stop=3/max=120`.
  - **Quotes:** band = 1 x the 1-minute sd x sqrt(60), about 7.7 sd; centre = 60-minute half-life average.
  - **Exits:** a stop at 3 bands, out after 120 minutes.
  - **Size:** $500 a trade on each of the nine coins.
  - **Fees:** maker 1.5 bp, taker 4.5 bp.
  - **Why this setting:** the best on the selection hours, in the middle of its region (bands of 5.5-8 sd).
- **Neighbours, secondary:** the same with h=30 (5.5 sd) and with k=1.5, h=30 (8.2 sd).
- **Command:**
  ```
  python -m marketimmune.cli.paper_range test --mids <all segments' mids.parquet> --from 2026-11-07T04:09 \
      --k 1 --horizon 60 --centre 60 --stop 3 --max-min 120 --null-draws 40 --out eval/paper/range_test_20261107.json
  ```
- **Primary, both required:**
  1. Net $ an hour > 0.
  2. Gross bp per round trip above the same rule's result on at least 95% of 40 hour-shuffled
     copies of the held-out hours (`share_gross_at_least_real` <= 0.05).
- **Reported regardless:**
  - The bootstrap interval by hour.
  - Trades by coin.
  - The result at maker fees of 1.2, 0.8, 0.4 and 0 bp, with taker 3 bp above the maker fee.
- **Power:** about 40-60 round trips are expected, so the interval will be wide. A pass decides
  whether to build the band maker into the paper engine (queue, latency) and run it live in paper.
  It does not decide on real money.
- **Fill model:** this is a mid-based simulation, not the paper engine.
  - **Fills:** an entry or exit fills only when the mid trades through it by half a tick.
  - **Passive only:** orders never rest inside the touch.
  - **Stops:** stop and time exits pay half a tick and the taker fee.

## Result (scored once, 2026-11-07 about 16:00 UTC; `eval/paper/range_test*_20261107.json`)

11.18 held-out hours, $500 a trade, nine coins.

| Setting | Round trips | Gross bp | Net bp | $ an hour [95%] | Null gross bp (40 copies) | Copies >= real |
|---|---:|---:|---:|---|---:|---:|
| **`band@k=1/h=60` (primary)** | 31 | +2.37 | -1.02 | -0.14 [-2.07, +1.47] | -2.29 | 0/40 |
| `band@k=1/h=30` | 57 | -0.42 | -3.95 | -1.01 [-2.98, +1.00] | -2.26 | 4/40 |
| `band@k=1.5/h=30` | 28 | +3.23 | -0.20 | -0.02 [-1.78, +1.46] | -2.19 | 0/40 |

- **Primary: not shown.**
  - **What failed:** the band maker lost $0.14 an hour after fees, so the first criterion fails.
  - **What passed:** its gross edge beat all 40 hour-shuffled copies, so the second criterion passes.
  - **Reading:** the reversion is there, and it is smaller than the fees: about +2.4 bp per round
    trip against 3 bp of maker fees.
- **At lower maker fees** (primary): 1.2 bp -$0.06/h, 0.8 bp +$0.05/h, 0.4 bp +$0.16/h, 0 bp +$0.27/h.
  Even fee-free it makes about $0.3 an hour on $500 trades.
- **Decision:** the band maker is not built into the paper engine and not run live.
