# Pre-registration: five candidate winning strategies (2026-11-07)

Written 2026-11-07 about 17:25 UTC, before any candidate below is run on its held-out data. The
commit time is the registration time. Two candidates get their settings in an addendum, committed
before their held-out runs. Drafted by Claude at Caesar's request:

> "think about how can we improve the strategy, and really guess it, using Transformer knowledge ...
> I need the top 5 guessing winning strategy that could use our information to win this."

## What the project knows (from `docs/research/paper-trading.md`)

- **Fee:** the maker fee (1.5 bp) is about three times the gap quoters' edge (0.4-0.5 bp per filled $).
- **Within a minute, moves continue:** touch fills are adversely selected.
- **Minutes look like a random walk:** a band maker's reversion is real (+2.4 bp per round trip) but
  smaller than two maker fees.
- **Coinbase leads Hyperliquid:** IC 0.5 / 0.23 / 0.10 at 1 / 10 / 60 s.
- **Funding:** in quiet markets shorts are paid the interest rate, about 11% a year.

## The five candidates

1. **Funding carry:** short the perp and hold the coin on Hyperliquid spot. The universe is the coins
   with a Hyperliquid spot market: BTC (UBTC), ETH (UETH), SOL (USOL), HYPE and AVAX (UAVAX). Equal
   dollars each, held throughout, with maker fees on both legs (perp 1.5 bp, spot 4 bp, in and out).
2. **Fill-toxicity quoter, `immune@h=30/t=-1`:** unchanged since the locked test, which it won with
   +$2.40 an hour [-1.04, +5.44]. It quotes a side only while the 30 s markout predicted from the
   signals before the fill clears the fee and an inventory cost.
3. **Range swing maker:** Caesar's range idea taken literally. Buy near the bottom of the expected
   range and sell near the top, instead of at the average. Its settings go in Addendum A.
4. **Transformer toxicity quoter:** the same rule as candidate 2, with the ridge model replaced by a
   small Transformer. The Transformer reads the last two minutes of one-second bars: the Hyperliquid
   mid, Coinbase mid, gap, spread and taker flow, for the coin and for BTC. Its settings go in Addendum B.
5. **Cross-coin pairs:** each coin against BTC, as a band maker on the hedged price. Coins' moves net
   of BTC look mean-reverting at 30-60 minutes on the selection hours: variance ratio 0.84 / 0.77,
   permutation p = 0.09 / 0.07.
   - **Eliminated on the selection hours, before this registration:** all 36 settings lost after the
     four maker fees of a round trip, and the grid's average gross was worse than shuffled copies
     (`/tmp`-only exploration, recorded here).
   - **Also eliminated:** a band maker vetoed by the Coinbase gap did no better than the plain band
     maker on the selection hours (16 settings).
   - **Not run on held-out hours.**

## Data and splits

- **Selection hours:** 2026-11-06 04:41 to 2026-11-07 04:09 UTC (16.7 h).
- **Held-out A:** 2026-11-07 04:09-15:19 UTC (11.2 h, the tuned run).
  - **Already seen:** the live PnL diagnosis and the band maker's registered test (exits at the average).
  - **Candidates 3 and 4:** their settings are fixed on the selection hours only, but held-out A is
    not blind to the band family.
- **Held-out B:** 2026-11-07 15:20-17:00 UTC (1.7 h, the market-maker run), never used by anything.
  - **Hash:** SHA-256 of the SHA-256 lines of its bars and raw logs is
    `96f208a60177fef48cbadd438f9309bd83e0f499a1ee3d751aecfbd536649676`.
  - **Not tested alone:** too short for most candidates; it is reported separately and pooled with A.
- **Funding:** 60 days of hourly funding to 2026-11-07 15:00 UTC.
  - **Candidate 1 has no tuned parameter:** the universe comes from spot availability, and both
    30-day halves were computed in one run (first half 7.5% a year net, second 6.2%). They are
    descriptive, not a held-out test.
  - **Its forward test:** the funding paid from this commit onward, read again later.

## Candidate 2: test on held-out A + B (replay, unchanged)

- **Chain:** `paper_tune` with the causal clock, $250 x 4 quotes, $5,000 budget, 200 ms, 1.5 / 4.5 bp.
  - **Warm-up, not scored:** the three locked-test segments (22:03-04:00).
  - **Scored:** tuned 04:09, 06:09, 08:10, 10:10, 12:10, 14:10 and mm 15:20.
- **Strategies:** `immune@h=30/t=-1`, `zgap@0.05` and `touch`.
- **Primary:**
  - **Criterion:** `immune@h=30/t=-1` makes more than $0 an hour, and its stationary-bootstrap
    95% interval (15-minute blocks, mean block 3, 5,000 draws, seed 0) lies entirely above zero.
  - **Reported regardless:** its pairing with `zgap@0.05`.

## Ranking rule for the write-up

Rank by the strength of held-out evidence, not by the point estimate:

1. an interval above zero on held-out data;
2. a positive point estimate with an interval including zero;
3. negative.

Ties are broken by the interval's lower bound.

## Addendum A: candidate 3, the range swing maker (written about 17:40 UTC, before its held-out run)

- **Selection sweep:** 48 settings on the selection hours, $500 a trade, with hour-shuffled nulls
  (`eval/paper/swing_selection_20261107.json`).
  - **Exit halfway to the far band** (`target=0.5`, on the centre-to-band scale): the grid averages
    +$1.16 an hour. The null averages -$0.10.
  - **Exit at the average** (`target=0`): +$0.27, null -$0.77.
  - **Exit at the far band** (`target=1`): +$0.73, null -$0.27.
  - **Best:** $2.30 an hour. The best of the 48 on each of two shuffled copies is $0.95 and $0.97.
- **Primary setting:** `band@k=1/h=30/c=60/stop=3/max=240/target=0.5`.
  - **Quotes:** band = 1 x the 1-minute sd x sqrt(30); centre = 60-minute half-life average of the mid.
  - **Exits:** at the centre plus half a band (maker), a stop at 3 bands (taker), or after 240 minutes
    (taker).
  - **Size and fees:** $500 a trade on each of the nine coins; maker 1.5 bp, taker 4.5 bp.
- **Neighbours, secondary:** the same with h=60, and with k=1.5.
- **Held-out run:**
  - **Data:** held-out A + B, on the Hyperliquid mid from the one-second bars, with a 3-hour causal warm-up.
  - **Null:** 40 hour-shuffled copies.
- **Primary, both required:**
  1. Net $ an hour > 0 on A + B.
  2. Gross bp per round trip above the null in at least 95% of the copies.
- **Reported regardless:** the bootstrap interval by hour, A and B separately, and lower maker fees.
