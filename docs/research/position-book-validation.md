# The position book and the liquidation prior against Hydromancer (December 2025)

The forced-flow forecaster (`cli.forced_forecast`, ladder rung L3b) does two things:

- **Position book.** It rolls every wallet's position forward through fills (`build_positions`,
  from the Albers Silver fills since Dec 1).
- **Liquidation price.** With no margin data, it gives each position the liquidation price
  `entry * (1 - sign * median(delta | delta > excursion))`, where `delta` is the distance from
  entry at which earlier wallets were liquidated.

Hydromancer's daily snapshots hold every open position with its exact liquidation price, from
2025-12-15. At each of the 17 snapshots (Dec 15-31), `validate_positions` rebuilds the
forecaster's book as it stood: the same state and the same prior, from fills strictly before the
snapshot. It then compares the two.

    python -m marketimmune.cli.validate_positions --coins SOL,ETH --dates 20251201..20251231 --out eval/position_book_validation.json

## Positions: right where the book has the wallet

Ranges over the 17 snapshots:

| | SOL | ETH |
|---|---|---|
| Open notional whose wallet the book has, size exact | 64-85% | 87-93% |
| Open notional of wallets with no fill since Dec 1 (the book cannot know them) | 14-36% | 7-10% |
| Open notional with a size mismatch | 0-1% | 0-3% |
| Exact matches whose entry price agrees within 1 bp (entry known) | ≥ 99.96% | ≥ 99.98% |
| Exact matches with an unknown entry (chain break since last flat) | 24-29% | 15-18% |

- **Positions the book holds that Hydromancer shows closed** jump after the archive outages
  (`docs/research/node-fills-reconciliation.md`):

  | Snapshot | SOL | ETH |
  |---|---|---|
  | Dec 18 | 26 positions, $0.05M | 30, $0.08M |
  | Dec 19 | 201, $2.2M | 155, $7.6M |
  | Dec 22 | 229, $2.9M | 245, $10.3M |

- **The cause is the outages.** All 245 of ETH's on Dec 22 traded inside an archive outage
  window. Those fills are missing from the Albers rebuild, so the book never saw the positions
  close. Rolling the book from node fills, which are complete, removes this.

## Liquidation prices: the prior is wrong

For positions whose size and entry match:

| | SOL | ETH |
|---|---|---|
| Median distance of the liquidation price from the mark, Hydromancer | 14-18% | 21-32% |
| The same, the prior | 2.2-2.7% | 1.8-2.4% |
| Notional with a liquidation price within 5% of the mark, Hydromancer (matched positions) | 4-15% | 2-8% |
| The same, the prior | 74-93% | 77-90% |
| Notional within 1% of the mark, Hydromancer (all positions) | 0.0-0.3% | 0.0-0.2% |
| The same, the prior | 3-22% | 2-60% |
| Median error of the prior's liquidation price, % of the mark | 12-15% | 17-28% |
| Correlation of prior and true distance | -0.01 to 0.08 | 0.01 to 0.03 |

- **The prior places almost the whole book within a few percent of the mark.** Most of the real
  book is more than 20% away.
  - The prior's distances come only from wallets that were liquidated: the ones at maximum
    leverage.
  - The forecaster's fitted hazard scale corrects the total, not the distribution.
  - Treating every position as if opened at maximum leverage (`max_leverage_distance`) is no
    better: median error 15-17% (SOL), 19-32% (ETH).
- **Hydromancer's liquidation prices are where liquidations happen.**
  - Forced fills Dec 15-31: 4,154 SOL and 3,667 ETH market liquidations of wallets in the
    previous snapshot (median 15 h earlier).
  - The mark at liquidation was within 1% of the snapshot's liquidation price for 76% (SOL) and
    67% (ETH).
  - Median overshoot: +0.03% (SOL) and +0.02% (ETH).
  - Cross-margin accounts' liquidation prices move with their other positions and funding, so a
    day-old snapshot is close but not exact.
- **No backstop liquidations happen in Dec 15-31.** In the pulled node fills, backstops are
  almost all on 2025-10-10 (BTC $1.27B, ETH $0.96B, SOL $0.57B notional), plus small ones on
  2026-08-19 and 08-22. The backstop threshold belongs with the Oct 10 stress case
  (Hydromancer has Oct 8-12).

## What this means

- **The L3b forecast columns rest on liquidation prices that are wrong for most of the book.**
  That may be part of why H4 did not replicate on ETH. It is a hypothesis: the verdict stands as
  scored.
- **Hydromancer makes the plan's B design possible for Dec 15 on and all of 2026:** exact
  liquidation prices from the day's snapshot, rolled forward through fills.
  - Positions opened after the snapshot still need a price.
  - Leverage and margin type are in the snapshot for wallets that already hold a position.
- **Two fixes, if B is rebuilt:** roll the book from node fills (complete), and seed it from the
  first snapshot (the 7-36% of notional the book cannot see).
