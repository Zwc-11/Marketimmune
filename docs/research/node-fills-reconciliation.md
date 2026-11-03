# Node fills against the Albers rebuild (December 2025)

The ladder's Gold rows come from the Albers L4 archive, rebuilt into Silver fills
(`build_albers_fills`). Hyperliquid's own `node_fills_by_block`, pulled in Tokyo with
`pull_node_fills`, is the complete record of trades. This checks one against the other, trade
by trade. Each trade is keyed by its maker and taker order ids; Albers has no trade id.

    python -m marketimmune.cli.reconcile_node_fills --coins SOL,ETH --dates 20251201..20251231 --out eval/node_fills_reconciliation.json

| | SOL | ETH |
|---|---:|---:|
| Node trades | 3,125,067 | 6,882,090 |
| Albers trades | 3,096,373 | 6,828,907 |
| Albers trades matched in node | 3,096,372 | 6,828,905 |
| Matched trades that differ in price, size, time, taker side or liquidation flag | 0 | 0 |
| Albers-only trades | 1 | 2 |
| Node-only trades | 28,695 (0.92%) | 53,185 (0.77%) |

- **Every Albers trade is a real trade, and every field the ladder uses is exact.** The three
  unmatched Albers trades are at 23:59:59. The two sources file them under adjacent dates, and
  each matches the node trade on the other date.
- **The node-only trades sit in 13 windows where the Albers archive has nothing.**
  - Both coins have the same 13 windows, so they are outages of the archive, not of one coin.
  - In each window there are no Albers fills and no Silver L2 rows.
  - They fall on six days: Dec 12, 15, 18, 20, 21 and 30.
  - Each lasts 17 to 68 minutes (median 23), 388 minutes in all, or 0.87% of the month.
  - On the worst days they hold 6% to 9% of the day's trades: Dec 18, 20, 21 and 30.

  | Date | Windows (UTC) |
  |---|---|
  | Dec 12 | 17:40-18:16 |
  | Dec 15 | 12:27-12:47 |
  | Dec 18 | 14:36-14:53, 15:09-15:33, 15:40-15:59 |
  | Dec 20 | 07:50-08:09, 08:18-08:36, 08:43-09:02, 09:54-10:22 |
  | Dec 21 | 13:39-14:09, 14:31-15:03 |
  | Dec 30 | 18:33-19:19, 19:33-20:40 |

- **The windows are ordinary market time.** Measured on node trades:

  | | SOL windows | SOL month | ETH windows | ETH month |
  |---|---:|---:|---:|---:|
  | Trades a minute | 79 | 70 | 145 | 154 |
  | Mean absolute 1-minute return (bps) | 6.4 | 5.97 | 5.49 | 5.28 |
  | Window minutes in the month's top 10% by trades | 14% | | 10% | |

  Leaving them out does not select calm or busy periods.
- **Gold leans on no stale book.**
  - Albers fills resume before the rebuilt book does: the book needs its 10-minute warm-up.
  - On Dec 12, 18 and 30, no Gold row on either coin has a feature book more than 30 s older
    than its fill. Fills in a warm-up have no fresh book or mid, so they are not in Gold.

## What this means

- The ladder (SOL and ETH) and the simulator are unaffected in what they contain: their trades
  are exact.
- They cover 99.1% of the month's time. A result about December is a result about December
  without these 388 minutes.
- Filling the windows would need a book as well as fills: node fills alone have no order book
  for the features, or mids for the labels. Hyperliquid's L2 snapshot archive could supply mids.
  That is not done here.
