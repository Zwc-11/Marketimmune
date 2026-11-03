# Forced-flow forecaster v2: exact book and liquidation prices (SOL, ETH, Dec 2025 and 2025-10-10)

Exploratory. No pre-registration. v1 (`cli.forced_forecast`) gives every position a liquidation
price from a margin-free prior. `docs/research/position-book-validation.md` showed that prior is
wrong: it puts 74-93% of open notional within 5% of the mark, against 2-15% in Hydromancer's
snapshots. v2 replaces it with the snapshots' prices and rolls the accounts between them.

    python -m marketimmune.cli.forced_v2 --coin SOL --dates 20251201..20251231            # resumable; repeat until done
    python -m marketimmune.cli.forced_v2 --coin SOL --dates 20251201..20251231 --report eval/forced_v2_sol.json
    python -m marketimmune.cli.forced_v2 --coin ETH --dates 20251201..20251231            # then --report eval/forced_v2_eth.json
    python -m marketimmune.cli.forced_v2 --coin SOL --dates 20251008..20251012 --out-dir data/gold/hyperliquid/forced_v2_oct   # and ETH
    python -m marketimmune.cli.forced_v2_checks --coins SOL,ETH --out eval/forced_v2_checks.json

On a small machine, `--max-days` and `--parts` split the run and the report into pieces.

## What v2 is

Every variant reads node fills only:
- the trade-implied mid;
- market liquidations as the target;
- positions rolled from each leg's `start_position`.

So v1 here is v1's model on node-fill inputs, and the three variants differ only in the book and
its liquidation prices.

| Variant | Book | Liquidation price |
|---|---|---|
| `v1` | Rolled from the first date; wallets first seen mid-position have no entry and drop out | The prior, for every position |
| `v2a` | Reset to each day's snapshot at its block, rolled between snapshots | The snapshot's while the wallet has not traded since; else the prior |
| `v2` | Same as v2a | The snapshot's while untraded; after a trade, the account is rolled (below) and the price re-solved; the prior only for wallets not in the latest snapshot |

**Account roll** (`forced.node_book.Account`):
- Each snapshot wallet's account value, size and liquidation price fix what its account needs for everything else on the account.
- At each fill, equity moves with this coin's price times the held size, the size changes, and the liquidation price is re-solved with the docs' maintenance-margin formula.
- An isolated position brings its own margin: adding posts `added notional / leverage`; reducing keeps the remaining share.
- What the account holds in other coins is taken as constant. That is v2's main error source (see "Account roll" below).

**Stale prices.** If the mark has passed a known price and the wallet still holds the position
one grid step (10 s) later, the price is wrong: liquidation fires at the next mark update. The
price is dropped and the prior, conditioned on the excursion, takes over until the wallet's next
fill.
- Without this rule, a cross account whose real price had moved with its other coins counted as
  a certain liquidation at every grid time.
- A single crossed $52k SOL position adds $52k at every 10 s grid point: about $450M of raw
  60 s forecast a day, against $2.7M of realised 60 s flow summed the same way on Dec 16.

Everything else is v1's, fitted on earlier dates only: the distance prior, the hazard scale per
variant, and the cascade impact. v2 starts at the first snapshot (Dec 15 01:04 UTC). Its first
day only fits the scale.

**Paired comparisons** cover the 15 days both variants score, Dec 17-31. Each table below is
for those days. They give day-level Diebold-Mariano p and stationary-bootstrap 95% intervals,
overall and in the `fast` regime (the top 5% of volatility).

**What was seen before the final design (disclosed).**
- A first SOL run had v2a's rule only and no stale rule. It was scored on Dec 16-31.
- Its raw forecasts were 10-30 times too high (hazard scale 0.02-0.07), and that is what led to
  the account roll and the stale rule.
- So the SOL December numbers below are not out of sample for the design. ETH December and both
  October runs were run once, with the final code.

## Inputs: v1 on node fills reproduces v1 on the Albers rebuild

| Coin, Dec 3/4-31 | 60 s Brier ×1e3: model / raw / climatology / persistence | Lead time: model hit at alarm rate | Heatmap hit at alarm rate |
|---|---|---|---|
| SOL, node fills | 5.986 / 7.431 / 6.162 / 5.353 | 41.7% at 5.2% | 35.1% at 9.1% |
| SOL, Albers (`eval/sol_dec_corrected/forced_sol.json`) | 5.963 / 7.180 / 6.137 / 5.326 | 43.1% at 5.2% | 34.0% at 7.8% |
| ETH, node fills | 6.538 / 10.539 / 6.815 / 5.616 | 36.7% at 4.0% | 23.8% at 9.4% |
| ETH, Albers (`eval/eth_dec/forced_eth.json`) | 6.497 / 10.538 / 6.778 / 5.578 | 37.4% at 4.0% | 23.2% at 9.6% |

The realised targets agree within 0.03%. On Dec 16, 20 and 25, market liquidations from node
fills total $2.6686M / $0 / $10.608M, against $2.6692M / $0 / $10.611M from Albers order events.
The input switch does not move the results.

## December results (Dec 17-31, 15 scored days)

**60 s Brier ×1e3 on the same days.** Calibrated model, walk-forward binned as in v1. Binary
target: at least $10k forced on a side; 0.47-0.49% of windows.

| Coin | v1 | v2a | v2 | Climatology | Persistence | v1 split by persistence | v2 split by persistence |
|---|---:|---:|---:|---:|---:|---:|---:|
| SOL | 4.639 | 4.622 | **4.495** | 4.759 | 4.354 | 4.287 | **4.135** |
| ETH | 4.704 | 4.686 | **4.624** | 4.884 | 4.232 | 4.068 | **4.060** |

**v2 against v1, paired.** Brier ×1e3 per day, positive = v2 better.

| Coin | Horizon | All windows | Fast regime |
|---|---|---|---|
| SOL | 60 s | +0.144 [+0.071, +0.228], 14/15 days, p 0.007 | +2.08 [+1.61, +2.57], 14/14, p < 1e-4 |
| SOL | 15 s | +0.035 [+0.021, +0.050], 13/15, p 0.001 | +0.61 [+0.43, +0.81], 12/14, p < 1e-4 |
| ETH | 60 s | +0.080 [+0.036, +0.124], 12/15, p 0.004 | +1.76 [+1.55, +1.99], 15/15, p < 1e-4 |
| ETH | 15 s | +0.020 [+0.009, +0.032], 11/15, p 0.005 | +0.51 [+0.39, +0.62], 15/15, p < 1e-4 |

- **The account roll is what helps, not the snapshot prices alone.**
  - v2a over v1 at 60 s: SOL +0.017 (p 0.10), ETH +0.018 (p 0.17).
  - v2 over v2a: SOL +0.127 (p 0.02), ETH +0.062 (p 0.005).
  - v2a loses its exact prices as wallets trade: on average 73-76% of open notional still has a
    snapshot price, against 97-98% for v2.
- **v2 does not beat persistence on its own.** Persistence minus v2 at 60 s: SOL 0.142 (p 0.18),
  ETH 0.392 (p 0.04).
  - Split by persistence, v2 gains on persistence by 0.219 (SOL, p 0.08) and 0.172 (ETH,
    p 0.08), against v1's 0.067 and 0.164 on the same days.
  - Forced flow still comes in bursts that the book alone does not predict.
- **Raw probabilities are not better calibrated.**
  - The paired raw Brier is mixed: SOL +0.02 (p 0.90); ETH -4.65 (p 0.05, v2 worse). v2 is better
    in SOL's fast regime (+10.6, p 0.03).
  - The realised over raw-forecast ratio (hazard fit, 60 s) is 0.58 for SOL and 1.13 for ETH,
    against v1's 0.07 and 0.18. So v2's level is right to within a factor of 2.
  - But the ratio swings across horizons for ETH (0.35 at 5 s, 1.13 at 60 s). The diffusion
    trigger model, not the prices, sets the horizon profile.
- **Pinball at q90 is not different** (SOL +2.3, p 0.15; ETH -0.5, p 0.22). Most windows have
  zero forced flow, so the calibrated q90 is 0 for most rows in both variants.

**Lead time on the same 264-267 onsets.** The signal is on at the last grid time before each
onset, at each signal's training 95th percentile. The v2-vs-v1 difference in hit rate is not
tested.

| Coin | v1 model | v2 model | Heatmap, v1's book | Heatmap, v2's book |
|---|---|---|---|---|
| SOL | 26.8% at 2.2% alarms | **49.6% at 2.6%** | 16.4% at 4.7% | 41.2% at 6.3% |
| ETH | 36.0% at 2.9% | **50.2% at 2.7%** | 8.8% at 1.9% | 18.4% at 1.0% |

For ETH, v2's model beats its own heatmap by 26.8 points of hit rate (p < 0.001).

## Account roll: rolled prices against the next day's snapshot

Wallets that traded between two consecutive snapshots and hold the same size in the second.
Each cell is the share of their notional whose price is within 1% of the mark of the second
snapshot's price.

| Coin, period | Margin | Wallets | Rolled | First snapshot's price kept (v2a) | Wallets that did not trade (drift) |
|---|---|---:|---:|---:|---:|
| SOL, Dec 15-31 (16 pairs) | cross | 18,213 | 34% | 16% | 52% |
| SOL, Dec | isolated | 7,713 | 80% | 53% | 97% |
| ETH, Dec | cross | 30,277 | 47% | 22% | 72% |
| ETH, Dec | isolated | 6,486 | 64% | 35% | 98% |
| SOL, Oct 8-12 (4 pairs) | cross | 6,899 | 21% | 16% | 18% |
| ETH, Oct 8-12 | cross | 11,033 | 19% | 8% | 28% |

- Rolling roughly doubles accuracy over keeping the old price.
- Isolated positions are mostly right.
- Cross accounts are not, and even the ones that did not trade drift: their other coins move
  their price. That drift is the floor for a one-coin book.
- In October, the rolled book overstates the cross notional within 3% of liquidation for ETH:
  $453M against $207M in the next snapshot. $366M of rolled ETH cross notional is already past
  its price, which is what the stale rule removes.
  - In December, the rolled within-3% notional is close to the truth: SOL $17.5M vs $11.5M,
    ETH $382M vs $354M.

## Liquidations against snapshot prices, and the backstop threshold

Each wallet's first liquidation after a snapshot, if it had not traded since. The overshoot is
how far the mark at liquidation (`liquidation_mark_px`) was past the snapshot's price, as a
share of it.

The docs say:
- **Book liquidation** happens when equity falls below maintenance margin.
- **The backstop** takes over below 2/3 of it.

For an untouched isolated position, that puts the backstop `(r/3)/(1 - 2r/3)` past the
liquidation price for a long, where `r` is the maintenance rate:
- 0.85% for SOL (20x, r = 2.5%);
- 0.68% for ETH (25x, r = 2%).

| Coin, Oct 8-12 | Method, margin | Events | Overshoot p10 / p50 / p90 | Within 1% | Past the 2/3 threshold |
|---|---|---:|---|---:|---:|
| SOL | market, isolated | 2,603 | -0.01% / +0.09% / +0.51% | 98.8% | 1.5% |
| SOL | backstop, isolated | 379 | +0.98% / +1.34% / +1.83% | 13.5% | **100%** |
| ETH | market, isolated | 2,809 | -0.00% / +0.06% / +0.35% | 99.1% | 1.1% |
| ETH | backstop, isolated | 124 | +0.72% / +0.97% / +1.50% | 53.2% | **100%** |
| SOL | market, cross | 1,390 | -87.6% / -2.77% / +0.36% | 43.8% | 1.7% |
| ETH | market, cross | 2,618 | -49.4% / -0.01% / +0.27% | 54.1% | 1.5% |

- **The 2/3 rule holds.** Every one of the 503 isolated backstop liquidations happened past the
  backstop price the snapshot implies. Of 5,412 isolated market liquidations, 1.1-1.5% did.
- **Market liquidations fire at the snapshot's price.** The median is 0.06-0.09% past it, and
  99% are within 1%.
- **Backstops happen when the mark gaps through both levels between updates.** On Oct 10, the
  median isolated backstop sat 0.3 (ETH) to 0.5 (SOL) points beyond its threshold.
- **Cross accounts are liquidated well before their single-coin price**: median 2.8% early for
  SOL, with a long tail. Their other coins lost first.
- **December had no backstops.** Isolated market liquidations were within 1% of the snapshot's
  price 99.9% of the time; cross ones 68% (SOL) and 75% (ETH).

## 2025-10-10

Hydromancer's Oct 10 snapshot is at 20:04:54 UTC, about 50 minutes before the crash.

| | SOL | ETH |
|---|---|---|
| Mark at the snapshot | 206.32 | 4,016.2 |
| Trade-mid low | 137.79 at 21:20:50 (-33%) | 3,261.4 at 21:19:47 (-19%) |
| Long notional within 2% / 5% / 10% / 20% / 35% of its price | $5M / 28M / 55M / 276M / 359M | $103M / 239M / 465M / 800M / 951M |
| Snapshot wallets the price path crossed and that were liquidated | 3,258, $355M | 3,197, $739M |
| Crossed, not liquidated by the next snapshot | 536, $30M | 744, $76M |
| Liquidated without the path crossing their snapshot price | 1,013, $183M | 1,460, $277M |
| Market liquidations, to the next snapshot (wallets in the snapshot) | $258M ($229M) | $561M ($507M) |
| Backstop liquidations (wallets in the snapshot) | $570M ($274M) | $959M ($453M) |

- **The snapshot is a good map of what a given fall liquidates.** The wallets whose prices the
  path crossed account for $355M (SOL) and $739M (ETH) of liquidated positions. Only 8% (SOL)
  and 9% (ETH) of crossed notional survived.
  - The path is the trade-implied mid. The mark, which decides liquidation, can differ during a
    crash.
- **"Liquidated without being crossed" is large: 34% (SOL) and 27% (ETH) of liquidated snapshot
  notional** (the last wallet row, against it plus the first).
  - These are cross accounts whose other coins fell further (alts fell more than SOL and ETH),
    and positions added after 20:04.
  - A one-coin book cannot see that contagion.
- **Backstop exceeded market liquidation**: 69% of liquidated notional for SOL, 63% for ETH. It
  happened off the book.

**Minute by minute.** Long liquidations hitting bids, and each forecast's expected notional.
Expected notional is the sum of `F_bid_60s / 6` over the grid; v2's is v2's own scale fitted on
Oct 9.

| Window (UTC) | Realised market + backstop, SOL | v1 / v2 expected, SOL | Realised, ETH | v1 / v2 expected, ETH |
|---|---|---|---|---|
| 20:50-21:00 (first wave) | $47M + 0 | $4.4M / $0.8M | $146M + 0 | $17.8M / $1.8M |
| 21:11-21:21 (cascade) | $188M + $568M | $9.1M / $22.8M | $349M + $958M | $27.2M / $35.3M |

| Signal (alarm at Oct 9's 95th percentile) | First alarm after 20:45, SOL | ETH |
|---|---|---|
| v2 expected flow, 60 s | 20:56:20 | 21:13:10 |
| v1 expected flow, 60 s | 21:13:40 | 21:13:50 |
| Heatmap within 1%, v2's book | 21:13:10 | 20:50:20 |
| Heatmap within 1%, v1's book | already on at 20:45 | already on at 20:45 |

- **Every forecast misses the crash by an order of magnitude.**
  - A diffusion trigger model with an EWMA volatility cannot expect a 19-33% gap within a minute.
  - The one-pass cascade adds 0.2-2% to the forecast in the cascade window (impact fitted on
    Oct 8-9: 0.7 bps per $1M for SOL, 1.4 for ETH).
  - What the snapshot offers here is the conditional map above, not a 60-second probability.
- **v1's probabilities are meaningless on Oct 10.** Before the crash (20:45-20:50), v1's
  P(≥ $10k forced into bids within 60 s) averages 0.57 (SOL) and 0.70 (ETH), against 0.00 and
  0.02 for v2.
  - v1's book has two days of history, so most wallets have no entry. A one-day scale fit cannot
    repair the prior.
- **v2's flow alarm came during SOL's first wave (20:56), 16 minutes before the cascade; for ETH
  it came only once the cascade had started (21:13).** v2's heatmap alarmed during ETH's first
  wave (20:50). These are single events, so no rate can be read from them.

## Limits

- **Exploratory.** One December half-month, two coins. The design was chosen after seeing an
  earlier SOL December run (see above).
- **One coin at a time.** Cross-margin accounts are liquidated by their whole portfolio. The
  account roll holds other coins fixed, which is v2's main error, and on Oct 10 it is most of
  the "liquidated without being crossed" notional.
  - Rolling all coins together needs snapshots and fills for every coin an account holds.
- **Snapshots are daily, and the archive has them only for Oct 8-12 and Dec 15-31, 2025.**
  Between snapshots, deposits, withdrawals, funding and fees are not seen.
- **The trigger model is unchanged.** The horizon profile of the raw forecast is off by a factor
  that varies by coin and horizon, so only calibrated scores are compared.
- **The crash timeline uses the trade-implied mid, not the mark.**

## Closed (2026-11-03)

Forced flow is closed as a toxicity signal for this project. Every place it was tested, it added
nothing a maker can use:

- **As a markout feature** (L3b, forecast liquidations), it came back null in both December
  ladders. On ETH, where it was confirmatory, H4 had a Holm p of 0.15 on Brier and 0.95 on pinball
  (`docs/research/eth-dec-2025-ladder-results.md`).
- **As a 60 s forecaster,** v2 beats v1 in both coins but not persistence on its own (above).
- **In the simulator,** S3 (S2 plus the race and forced-flow columns) is level with S2 on SOL,
  -23 USD a day [-71, +24], and worse on ETH, -84 [-146, -11] (`docs/research/block-simulator.md`).
- **The fixes need data the archive does not have.** Snapshots exist only for Oct 8-12 and
  Dec 15-31, 2025, and the cross-coin roll below needs them for every coin an account holds.

What would reopen it, in order:

1. Roll accounts across coins. Snapshots and node fills for BTC and the large alts would let
   cross accounts be priced as portfolios. That is the error the checks above point at.
2. A gap-aware trigger model, for example a jump component fitted on large one-minute moves,
   evaluated on Oct 10-12 and any later stress day the archive covers.
3. If the backstop matters for a maker (it does not hit the book), the 2/3 rule is now checked
   and can be used to split forecast liquidations into book and off-book.
