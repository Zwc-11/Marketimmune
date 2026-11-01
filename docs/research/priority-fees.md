# Priority fees in fills: rollout, units and markout by fee band (BTC, ETH, SOL, 2026)

Plan v3, A.5 tests 1 (rollout) and 2 (raw separation), on Hyperliquid's `node_fills_by_block`,
Mar 1 to Oct 31, 2026 (`pull_node_fills`). These tests come before any model.

    python -m marketimmune.cli.pull_candles --coin HYPE --intervals 1h,4h --dates 20260301..20261031
    python -m marketimmune.cli.priority_fee_bands --coins BTC,ETH,SOL --dates 20260301..20261031
    python -m marketimmune.cli.priority_fee_bands --coins BTC,ETH,SOL --dates 20260301..20261031 --report eval/priority_fee_bands.json
    python -m marketimmune.cli.validate_trade_mids --coins SOL,ETH --dates 20251201..20251231 --out eval/trade_mid_validation.json

## Rollout

The first fill with `priorityGas > 0` is on **2026-04-25** for all three coins. No fill from
Mar 1 to Apr 24 has one.

Share of taker fills that paid a fee:

| Coin | Apr | May | Jun | Jul | Aug | Sep | Oct |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 0.1% | 0.7% | 0.8% | 1.8% | 4.5% | 7.4% | 8.5% |
| ETH | 0.2% | 1.5% | 2.6% | 4.4% | 7.5% | 14.0% | 12.9% |
| SOL | 0.4% | 2.3% | 3.2% | 4.9% | 10.6% | 6.4% | 7.4% |

## Units

`priorityGas` is the fee burned in HYPE, with 1e-8 (one wei) resolution. The docs say only that
the fee is converted to HYPE at the spot mark. To turn it into bps of notional,
`priority.fees` multiplies by HYPE's USD price (the hourly candle's (open + close) / 2 from the
`info` endpoint, or the 4-hour candle before Apr 7) and divides by notional. Two checks support
this:

- **An order's fee splits across its fills in proportion to size.** On BTC, 2026-10-15, an order
  filled 0.01197 and 0.00041 BTC paid 0.000142 and 0.000005.
- **The fees bunch at round bps every month, wherever HYPE's price is.**
  - The latency benefit stops at 8 bps, and fills bunch exactly at 4 and 8 bps.
  - HYPE's monthly mean doubled, from $41 in April to $84 in October, and the bunches stayed at
    4.0 and 8.0 bps.
  - Example, BTC in July: 3,780 fee-paying fills at 7.9-8.1 bps, against 234 at 7.5-7.9 and 151
    at 8.1-8.5.
  - With the wrong units, the bunches would move with HYPE's price.

Fees above 8 bps buy only tie-breaks within a 70 ms bucket.
- Through July they are under 5% of the fills paying more than 4 bps.
- In September and October they are 31% to 67% of those fills, depending on coin and month.

Fee among fee-paying fills since rollout:

| Coin | Median | 75th percentile | 90th | 99th |
|---|---:|---:|---:|---:|
| BTC | 0.11 bps | 0.41 bps | 1.49 bps | 8.0 bps |
| ETH | 0.11 bps | 0.51 bps | 1.73 bps | 9.6 bps |
| SOL | 0.11 bps | 0.51 bps | 2.09 bps | 8.5 bps |

## Maker markout by the taker's fee band

Apr 25 to Oct 31, 2026 (190 days): 66.3M BTC, 30.2M ETH and 17.2M SOL trades.

- The markout is the maker's, in bps, from the fill price: spread earned plus the move.
- Markouts are measured on a mid implied by trades. See "The trade-implied mid" below for why
  10 s and 60 s are reliable and 1 s is only indicative.
- Each cell is the mean of daily means with a day-level stationary-bootstrap 95% interval, over
  days with at least 30 fills in the band.

**10 s:**

| Band (bps) | BTC fills | BTC fee | BTC markout | ETH fills | ETH fee | ETH markout | SOL fills | SOL fee | SOL markout |
|---|---:|---:|---|---:|---:|---|---:|---:|---|
| 0 | 96.65% | 0 | -0.34 [-0.39, -0.29] | 93.11% | 0 | -0.24 [-0.30, -0.18] | 94.37% | 0 | -0.21 [-0.30, -0.13] |
| 0-2 | 3.15% | 0.30 | -2.08 [-2.24, -1.94] | 6.25% | 0.31 | -2.01 [-2.27, -1.79] | 5.03% | 0.28 | -2.13 [-2.31, -1.98] |
| 2-4 | 0.08% | 2.90 | -5.56 [-6.28, -4.85] | 0.20% | 2.74 | -5.67 [-6.36, -5.05] | 0.34% | 2.84 | -6.47 [-7.00, -5.96] |
| 4-8 | 0.09% | 5.83 | -7.97 [-9.03, -6.97] | 0.28% | 6.11 | -9.56 [-10.54, -8.62] | 0.15% | 5.71 | -8.53 [-10.04, -7.00] |
| 8+ | 0.04% | 10.23 | -10.82 [-14.57, -7.28] | 0.16% | 9.66 | -10.28 [-12.06, -8.63] | 0.11% | 9.62 | -13.19 [-15.76, -10.62] |

**60 s:**

| Band (bps) | BTC | ETH | SOL |
|---|---|---|---|
| 0 | -0.34 [-0.41, -0.28] | -0.31 [-0.39, -0.23] | -0.36 [-0.51, -0.24] |
| 0-2 | -2.21 [-2.50, -1.97] | -2.16 [-2.48, -1.85] | -2.58 [-2.80, -2.36] |
| 2-4 | -4.02 [-4.92, -3.12] | -5.27 [-6.26, -4.34] | -6.04 [-6.95, -5.17] |
| 4-8 | -6.75 [-8.83, -4.97] | -8.61 [-10.13, -7.22] | -7.53 [-9.43, -5.63] |
| 8+ | -8.92 [-12.77, -5.19] | -9.14 [-12.45, -5.97] | -10.78 [-14.05, -7.59] |

- **The separation is large, monotone in the fee and the same in all three coins.**
  - A maker hit by a taker that paid no fee loses 0.2 to 0.3 bps at 10 s.
  - Against a taker paying 0-2 bps, it loses about 2 bps.
  - Against 2-4 bps, 5.6 to 6.5. Against 8 bps or more, 10 to 13.
  - From band 0-2 up, the intervals do not overlap band 0's. This reproduces the pattern 0xArchive
    reported, before any model.
- **Each band's maker loss is larger than the fee its takers paid.**
  - At 10 s: 2-4 bps band, 2.7-2.9 paid against 5.6-6.5 lost. 4-8 bps band, 5.7-6.1 paid against
    8.0-9.6 lost.
  - The takers paid less than the move they captured, as A.4's inequality says they should.
  - So the fee is a lower bound on how stale the quote was.
- **Fee-paying fills are few: 3.4% to 6.9% of fills since rollout.** They are 7% to 14% of
  fills in the last 60 days (`eval/priority_fee_bands.json`, `last_60_days`).
  - The 2+ bps bands are 0.2% to 0.6% of fills, and carry the large losses.

## The trade-implied mid

From April 2026 there is no rebuilt order book for these coins. `priority.fees.trade_mids`
takes, after each block, the last price a taker bought at and the last price a taker sold at,
carried forward, and uses their mean. While they cross, it uses the block's last trade price.

On December 2025 both this mid and the rebuilt book exist. `validate_trade_mids` joins each node
trade to its Gold row (taker order id, time, price, size): SOL, Dec 1-31, 2,883,611 trades; ETH,
Dec 1-15, 3,824,772.

| Measure | SOL corr | SOL mean, trade mid / Gold | ETH corr | ETH mean, trade mid / Gold |
|---|---:|---|---:|---|
| Markout from fill price, 1 s | 0.68 | +0.53 / -0.23 | 0.83 | +0.16 / -0.47 |
| Markout from fill price, 10 s | 0.97 | -0.28 / -0.33 | 0.99 | -0.60 / -0.61 |
| Markout from fill price, 60 s | 0.99 | -0.37 / -0.39 | 1.00 | -0.56 / -0.56 |
| Move from the pre-fill mid, 1 s | 0.76 | -0.85 / -1.20 | 0.84 | -1.34 / -1.48 |

- **10 s and 60 s:** the markout from the fill price matches the book's: correlation 0.97 to
  1.00, and the same mean.
- **1 s and the split:** the pre-fill mid from trades sits off the book's mid, so the 1 s markout
  and the split into half-spread and move are biased.
- **Differences survive at 1 s, compressed by about a third.** By bucket of the CEX gap, the
  trade-mid move at 1 s orders the same way as the book's:
  - SOL: -2.21 vs -3.34 bps when the gap is ≤ -2, against +0.02 vs +0.71 when it is ≥ 2.
  - So the 1 s fee-band differences in the report understate the true ones.

## Limits

- **No control yet for the CEX gap.** The plan's claim is that fees predict the markout beyond
  `g_b`, the Binance move the quote has not followed. Fee-paying takers chase exactly those
  moves, so this table cannot tell fee information from staleness. That is the A1 ladder's
  question (L3a vs L2, with `g_b` in every rung).
  - It needs Binance aggTrades for Apr 25 to Oct 31, 2026.
  - It also needs book features for 2026. There is no L4 archive for 2026, so the source is open.
- **Executed takers only (A1).** Fees paid by takers that lost the race are in `replica_cmds`,
  which is A2.
- **HYPE's price is an hourly average.** It moves the fee by about ±1% within an hour, which is
  small next to the band widths.
- **The last minute of each day** reads its future mid from the same day's trades only.
