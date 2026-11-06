# Live paper trading (Hyperliquid, night of 2026-11-05/06)

Every strategy the December 2025 simulator and A1 suggested might make money, run on the live
Hyperliquid feed through one night, with paper orders matched against the real trades. No order was
sent. Four strategies picked in the first hour were then tested on the following hours under a
registration committed before those hours existed (`docs/preregistration/paper-forward-test-20261106.md`).
The code is `marketimmune/paper/`.

    python -m marketimmune.cli.paper_trade --out data/paper/seg3 --hours 1.95 --state-dir data/paper/state --strategies touch,gap@0.25,...
    python -m marketimmune.cli.paper_report --runs data/paper/seg3-* data/paper/seg4-* --out eval/paper/forward_test_20261106.json
    python -m marketimmune.cli.paper_trade --out data/paper/replay --replay data/paper/seg3-.../raw --retime hl=50,cb=70 --latency-ms 20   # as if in Tokyo

**Summary.**

- **Quoting at the touch loses, live, as the December simulator said:** -3.49 bps per filled dollar,
  -$721 an hour over the nine coins, in every one of 15 quarter-hours. December's simulator had
  -3.19 (SOL) and -3.35 (ETH).
- **Everything from December still loses:**
  - the stale-quote rule (gap pulls at 1-2 bps): -1.9 to -2.6 bps;
  - the live walk-forward model: -2.0 to -2.9;
  - quoting inside wide spreads: -3.2;
  - taking on the gap: -3.6 to -4.6, although the price moves +3.4 bps its way within a second.
- **Pulling on very small gaps (0.25-0.5 bps) is the one thing that came out positive:** +0.4 to
  +1.7 bps per filled dollar, +$16 to +$61 an hour, over 3.5 held-out hours. In the selection hour
  they had -0.03 to +1.81 bps.
  - It beat the touch quoter in 14-15 of 15 quarter-hours, by about $700 an hour.
  - **It does not pass the registered rule.** Every interval includes zero, the 95% ones too.
  - Its gain is not the spread. Its fills are still adversely selected over 60 s. The gain comes from
    the positions it holds: it quotes only the side the Coinbase lead says will not be run over, so
    it ends up long before Hyperliquid catches up and short before it falls. That is lead-lag
    exposure, carried passively.

## Setup

- **Feeds.** Hyperliquid's public WebSocket: `bbo` (the best bid and ask, about once a block),
  `l2Book` (20 levels, every few seconds) and `trades` (with the buyer's and seller's wallets), for
  BTC, ETH, SOL, XRP, LTC, BCH, LINK, AVAX and DOGE. The price reference is Coinbase's `level2`
  book for `<COIN>-USD`.
  - Coinbase replaces Binance because it is licensed in Ontario. Binance's WebSocket there is an
    open question (`docs/research/jurisdiction.md`).
  - Reading Hyperliquid's public market data from Ontario was answered as allowed on 2026-10-31
    (same file).
- **Where it ran.** A cloud machine in the US East. Coinbase messages arrive 17-20 ms after their
  server time, so the clock is good. Hyperliquid's arrive about 330 ms after their block time
  (p10 290, p90 420-490 ms). That is the API's publication delay plus the distance to Tokyo, and it
  is part of the test: this is what a maker outside Tokyo sees.
- **Orders.** $1,000 quotes; a strategy stops quoting a side at 5 quotes of position. An order
  reaches the book 200 ms after the decision, and a cancel takes effect 200 ms after it is sent.
  Maker fee 1.5 bp, taker fee 4.5 bp (Hyperliquid's base tier).
- **Runs.** Segments of about 2 hours, each starting flat and marked to the mid at its end, so they
  add up. The model's rows and the wallet scores carry from one segment to the next. Every raw
  message is kept, so any segment can be replayed through the same code.

## Fill model (`marketimmune/paper/orders.py`)

There is no live L4 feed, so the queue comes from the public book, as in hftbacktest's risk-averse
model:

- An order joins behind the size the first book message after its arrival shows at its price.
  Later book messages can only shrink the queue ahead.
- A taker trade at the order's price uses up the queue ahead first and fills the order with the
  rest. A trade through the order's price fills it in full.
- Trades and book messages are placed by Hyperliquid's block time, not by when they arrived.

Biases, both ways:

- The order is not in the real book, so real takers never saw it. A sweep that filled it would have
  gone one order less deep.
- An order one tick inside the spread (`improve`) has nothing ahead of it here. A real one would
  draw other makers in front of it at the same price.
- Cancels are assumed to come from behind the order (risk-averse), so the queue ahead drains only
  through trades.

## Strategies (`marketimmune/paper/strategies.py`)

Each runs on every coin, on its own account; none sees the others' orders.

| Strategy | What it does | Where it comes from |
|---|---|---|
| `touch` | Quotes both sides at the best price | December's S1, the control |
| `gap@1`, `gap@2` | Pulls the side the demeaned Coinbase gap says is about to be picked off, beyond 1 or 2 bps | December's stale-quote rule |
| `model@0.5`, `model@1` | Pulls the side a walk-forward ridge model's next-second move points at, beyond 0.5 or 1 bp | December's S2, live |
| `improve` | When the spread is at least 3 ticks, quotes one tick inside it on both sides | The spread term: the only one positive in December |
| `improve+gap@2` | `improve` plus the 2 bps gap pull | Both |
| `taker@6`, `taker@10` | Buys (sells) $1,000 at the touch when the gap reaches 6 or 10 bps; closes 10 s after the fill | The other side of the maker's loss |

**Gap.** `ln(Coinbase mid) - ln(Hyperliquid mid)` in bps, minus its 5-minute EWMA, which removes
the perp-spot basis.

**Model.** Every 100 ms the features are stored with the seen Hyperliquid mid:

- the gap;
- Coinbase and Hyperliquid returns over 1 and 5 s;
- taker flow imbalance over 1 and 5 s;
- the wallet scores of the takers that bought and that sold in the last 5 s;
- the spread.

The wallet score is each taker's shrunk mean 10 s markout, learnt live from every coin. Every
10 minutes, once 20 minutes of rows exist, a ridge regression of the next second's seen-mid move is
refitted on all labelled rows. Each refit first scores the previous fit on the rows it had not seen,
so the model log is a walk-forward record.

## Results

**Hours.** All times UTC, 2026-11-06:

- **Selection: 04:48-05:59, 1.18 h** (`seg2`). Its first 70 minutes were also replayed with a grid of
  strategies (`eval/paper/selection_grid_*.json`).
- **Registration:** committed and pushed at 05:59.
- **Forward test: 05:59-07:56 and 07:57-09:31, 3.53 h** (`seg3`, `seg4`).
  - The cloud environment stopped at 09:31. Segment 4 ended there and was written by its stop
    handler; no fifth segment ran (registration, Deviations).
  - 13 feed reconnects in all. Hyperliquid's median delay was 336-344 ms.

### Forward test: every strategy (`eval/paper/forward_test_20261106.json`)

Nine coins summed, bps per filled dollar; USD an hour with its 95% interval over 15-minute blocks.

| Strategy | Fills | Spread | Adverse 1 s | Adverse 60 s | Inventory | Total | USD/h [95%] | Break-even fee |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| `improve+gap@0.25` | 1,860 | +0.23 | -0.44 | -0.88 | +3.38 | **+1.67** | +61 [-39, +164] | 3.17 |
| `gap@0.25` | 1,627 | +0.17 | -0.55 | -0.76 | +3.12 | **+1.25** | +34 [-61, +128] | 2.75 |
| `improve+gap@0.5` | 2,604 | +0.19 | -0.47 | -0.83 | +2.37 | +0.59 | +28 [-82, +153] | 2.09 |
| `gap@0.5` | 2,348 | +0.13 | -0.56 | -0.69 | +2.35 | +0.42 | +16 [-81, +125] | 1.92 |
| `gap@1` | 4,441 | +0.04 | -0.60 | -0.83 | +0.15 | -1.92 | -133 [-239, -5] | -0.42 |
| `model@0.5` | 6,071 | +0.02 | -0.65 | -0.90 | +0.10 | -2.04 | -185 [-294, -58] | -0.54 |
| `improve+gap@2` | 10,258 | -0.02 | -0.68 | -1.09 | -0.01 | -2.21 | -361 [-464, -195] | -0.71 |
| `gap@2` | 9,703 | -0.05 | -0.74 | -1.20 | -0.26 | -2.56 | -369 [-474, -207] | -1.06 |
| `model@1` | 10,563 | -0.05 | -0.77 | -1.18 | -0.56 | -2.88 | -441 [-568, -263] | -1.38 |
| `improve` | 14,786 | -0.21 | -1.04 | -1.52 | -0.49 | -3.24 | -747 [-825, -593] | -1.74 |
| `touch` | 14,143 | -0.22 | -1.11 | -1.60 | -0.66 | **-3.49** | -721 [-809, -561] | -1.99 |
| `taker@10` | 116 | -2.68 | +3.35 | +2.82 | +0.23 | -3.60 | -12 [-26, -1] | 0.90 |
| `taker@6` | 718 | -1.75 | +1.42 | +1.41 | +0.28 | -4.56 | -92 [-113, -59] | -0.06 |

Columns:

- **Spread** is measured against the mid before the fill's block. It is negative for `touch`,
  because with a 340 ms-old view plus 200 ms of order latency, a quote is often still resting where
  the book has already moved away.
- **Inventory** is everything after the first second, to the mark at the end of each segment.
- **Break-even fee** is the maker fee (taker fee for the takers) at which the total is zero.

### The registered test (`eval/paper/forward_test_verdict_20261106.json`)

| Candidate | Total | USD/h | 98.75% interval | Positive blocks | At 0.8 bp | vs `touch`, USD/h [95%] | Blocks better |
|---|---:|---:|---|---:|---:|---|---:|
| `improve+gap@0.25` | +$213 | +61 | [-59, +193] | 9/15 | +$303 | +735 [+595, +875] | 15/15 |
| `gap@0.25` | +$119 | +34 | [-84, +160] | 7/15 | +$186 | +709 [+582, +843] | 15/15 |
| `improve+gap@0.5` | +$99 | +28 | [-108, +187] | 8/15 | +$218 | +704 [+559, +854] | 14/15 |
| `gap@0.5` | +$56 | +16 | [-103, +160] | 7/15 | +$148 | +693 [+559, +829] | 14/15 |

**No candidate makes money under the registered rule.** All four are positive over the 3.5 held-out
hours, and three of them were in the selection hour too. Their 98.75% intervals are about $110-130
wide on each side of +$16 to +$61 an hour.

How much longer a test would need, on the square-root rule at the same spread:

- the best candidate (+$61 an hour) would need about 12 more hours to exclude zero;
- the others would need 30 hours or more.

**Where the gain comes from.** `forward_test_drift_timing_20261106.json` splits each strategy's
position PnL, minute by minute. Drift is the average position times the average move, which would
pay off simply from the night's trend. Timing is the covariance of the position with the next
minute's move.

| Strategy | Position PnL | Drift | Timing |
|---|---:|---:|---:|
| `improve+gap@0.25` | +$500 | +$56 | **+$444** |
| `gap@0.25` | +$334 | +$47 | **+$288** |
| `gap@0.5` | +$336 | +$92 | +$244 |
| `touch` | -$182 | +$37 | **-$220** |

The candidates' positions lead Hyperliquid's next move: the lead-lag between Coinbase and
Hyperliquid, carried as inventory. The touch quoter's positions trail it, which is adverse selection
at the minute scale.

The gain is not one coin. `improve+gap@0.25` is positive in 7 of 9 coins:

- ETH +$59, SOL +$77, BCH +$48, LINK +$32, DOGE +$32, XRP +$19, AVAX +$18;
- BTC -$67, LTC -$6.

**Takers.** The gap does move the price: a `taker@10` entry is +3.35 bps in its favour a second
later. Crossing the 340 ms-stale spread costs 2.68 bps and the fee 4.5, so it loses 3.6 bps.

**The model.** Its walk-forward out-of-sample R^2 on the next second's seen move was 0.27-0.48 in
every coin (22 refits each), yet trading on it lost. Most of what it predicts is Hyperliquid catching
up to moves that have already happened on the exchange and not yet reached this machine. That is
real for a quote that is already stale, but too late to act on.

### Location and latency (replays, exploratory)

The held-out hours replayed through the same code (`eval/paper/replay_*_20261106.json`, USD an hour):

| Strategy | As recorded (200 ms) | 50 ms orders | Tokyo (feed 50 ms after the block, Coinbase +70 ms, 20 ms orders) |
|---|---:|---:|---:|
| `touch` | -721 | -696 | -593 |
| `gap@1` | -136 | -100 | -84 |
| `gap@0.5` | +25 | +14 | +22 |
| `gap@0.25` | +43 | +48 | +48 |
| `improve+gap@0.25` | +71 | +58 | +66 |

Notes:

- The replay as recorded reproduces the live touch quoter exactly: 14,143 fills, -$720.67 an hour.
  The four candidates differ by $9-15 an hour, because live they started from the previous segment's
  basis and the replay starts from none.
- Being in Tokyo helps the touch quoter by $128 an hour and leaves the candidates where they were.
  Their edge is the Coinbase lead, which a Tokyo maker sees later.

## Strategies with more machinery (screen, exploratory)

Built after the night, on estimators updated every 100 ms (`marketimmune/paper/signals.py`):

- the gap's own volatility;
- a recursive-least-squares forecast of Hyperliquid's next 10 s from the gap (an
  Ornstein-Uhlenbeck closing, with exponential forgetting);
- Hawkes-kernel taker intensities.

They were screened on the night's whole recording, 4.71 hours replayed
(`eval/paper/advanced_screen_20261106.json`), all of it already seen:

| Strategy | Idea | Fills | bps per filled $ | USD/h [95%] |
|---|---|---:|---:|---|
| `zgap@0.25` | Pull on the gap in units of its volatility | 2,399 | +1.97 | +68 [-14, +160] |
| `improve+gap@0.25` | The night's best, for reference | 2,327 | +1.91 | +65 [-11, +150] |
| `hawkes@3` / `@2` | The best plus a pull while takers hit a side in a burst | 1,906 / 1,809 | +1.18 / +1.14 | +33 / +30 |
| `zgap@0.5` | | 3,443 | +0.40 | +19 |
| `reservation@1` / `@3` | Avellaneda-Stoikov reservation price with the forecast as drift; quote a side only past the fee | 249 / 263 | +1.20 / -0.16 | +5 / -1 |
| `kelly@1` / `@0.5` | Mean-variance (Kelly-style) target position from the 10 s forecast; quote only toward it | 1,225 / 1,651 | -1.21 / -1.05 | -22 / -26 |
| `touch` | Control | 18,028 | -3.34 | -665 |

- **None beats the simple strategy by more than its noise.** `zgap@0.25` is the same strategy with
  a per-coin threshold.
- **The burst filter costs fills without removing the bad ones.**
- **Sizing by the 10 s forecast loses.** It flattens when the forecast fades, which gives up the
  minute-scale position timing where the gain was. A longer forecast horizon is the obvious
  variant.
- All of them run in the 24-hour confirmation as exploratory
  (`docs/preregistration/paper-confirmation-20261106.md`).

## Live view

`--serve 8765 --web frontend/dist` serves the web terminal with a **Paper trading** page
(`#/paper`), refreshed every second. `scripts/run_paper_live.ps1` starts it on Windows. The page
shows:

- each strategy's PnL, per hour and per filled dollar, with its fills, gross position and order
  actions a minute (Hyperliquid's rate limit counts those);
- the cumulative PnL curves;
- per coin: the signals (gap, gap z, 10 s forecast, model, bursts), the selected strategy's live
  bid and ask with the queue ahead, its position and PnL, and the reason for its quotes;
- a log of each time it starts or stops quoting a side, with the reason.

The live run measured order actions too: the makers send about 2,500-4,500 orders and cancels a
minute over the nine coins. At $1,000 quotes their fills earn enough of Hyperliquid's per-address
request budget (one request per dollar traded). At minimum size they would not.

## Decision journal (`marketimmune/paper/journal.py`, `cli.paper_journal`)

Every run now writes `journal/` next to its summary, as it goes (flushed every minute, readable while
the run is on):

| File | One row per |
|---|---|
| `decisions.jsonl.gz` | change of the sides a maker quotes on a coin: the sides the quoter wanted, the sides sent after the budget, its reason, the position, and the signals then |
| `fills.jsonl.gz` | paper fill: block and local time, price, size, fee, position after; for a maker, when the order was sent and reached the book, the queue ahead when it joined and just before the fill, whether the trade went through the price, the mid before the block, and the signals when the order was sent |
| `taker.jsonl.gz` | taker entry or exit sent, with the signals |
| `signals.jsonl.gz` | coin and second: mid, spread, Coinbase mid, gap, gap z, 10 s forecast, 1 s model, 1 s volatility, buy and sell bursts |
| `minutes.jsonl.gz` | strategy, coin and minute: orders and cancels sent, fills, time quoted on both sides / one side / none, sides the budget dropped, position, PnL |

The order actions themselves (1,200-1,800 a minute per strategy over the nine coins) are counted,
not listed. At the night's pace the journal of 21 strategies is about 11 MB an hour; the raw
recording is 60-120 MB an hour.

- **It only reads.** A replay with and without it gives the same fills, byte for byte
  (`tests/paper/test_paper_journal.py`; also the night's second segment, 26,217 fills).
- **Replays are now exact.** The raw recording also keeps the time of each 100 ms engine tick
  (`raw/tick-*.log.gz`). A recording that has them replays every live decision in the same order
  (tested). Without them a replay ticks on its own 100 ms grid. On the first 23 minutes of the
  24-hour run, which started before this change, the replay saw the same 146,599 events and
  reproduced `touch`, `improve` and both takers exactly, but the signal quoters' fills only to
  within 1-8%: the basis, volatilities and model they read are updated on the ticks.
- **Other settings on the same live data.** Paper orders do not touch the market, so a
  recording with its ticks can be replayed with any settings and the result is what the live run
  would have shown with them. One new setting: `--budget-usd 5000` gives each strategy one budget
  of gross exposure over all coins (each position at its mid); a side that would take it past the
  budget is not quoted, a side that reduces the position always is, and a taker does not enter.
- `python -m marketimmune.cli.paper_journal --runs <run dirs> --out <json> --md <md>` reads the
  journals (`eval/paper/journal_night_20261106.{json,md}` for the night, replayed with all 21
  strategies).

### What the night's journal shows (4.76 replayed hours, exploratory)

- **The candidates' fills are adversely selected like everyone's.** Over the first five minutes
  after a fill, the mid moves against it for every quoter (`improve+gap@0.25`: -0.4 bps at 1 s,
  -0.7 bps at 5 min; `touch`: -1.1 and -1.5). Net of the fee, their fills lose about 2 bps over a
  minute.
- **Their PnL accrues later.** Summed in USD over the fills, the mid's move after them is negative
  up to five minutes and turns positive after: for `improve+gap@0.25`, -$112 at 5 min, +$330 at
  15 min, +$521 by the segment's end, which is its whole position PnL. So the gain is held inventory
  over a quarter of an hour or more. The Coinbase lead picks which side fills; the position it
  leaves rides the night's moves. That is a directional position at a slow pace, not a spread.
  It agrees with the drift/timing split above (positions that covary with the next minutes' move)
  and makes its risk plain: it needs the moves to persist.
- **Fills that grow the position gain; fills that shrink it lose.** `improve+gap@0.25`: +2.4 bps
  at 5 min for the 1,328 opening fills, -4.2 bps for the 1,139 closing ones (`gap@0.25`: +1.9 and
  -3.7). `touch` shows the same tilt (-0.5 and -2.6), so part of it is how a capped position fills.
- **The 0.25-bp quoters change their mind every 1.5 s.** About 40 side changes a coin and minute.
  After a pull, the mid moves 0.56 bps towards the pulled side within 10 s (54% of pulls): the pulls
  are right on average, by less than the fee.
- **Fills alone at a new level do better than fills behind a queue.** -1.6 bps against -2.5 at
  1 minute for `improve+gap@0.25`, -1.0 against -2.4 for `gap@0.25`.
- **Rate limit:** 0.05-0.3 order actions per USD filled for every quoter but the reservation pair
  (0.75), under Hyperliquid's one per USD.

Ideas these point to, none tested: a hysteresis band on the pull threshold (fewer flips, fewer
actions, queue kept); a position target from a forecast over 15 minutes rather than 10 s; holding
the position longer when the lead still points its way (closing fills lose).

## Reading

- **The December conclusions hold live.** Quoting at the touch on Hyperliquid at retail latency
  loses about 3.5 bps per filled dollar, and the loss is adverse selection, not fees.
  - The stale-quote rule and the model cut the loss; they do not reverse it.
  - Quoting inside wide spreads earns nothing extra.
  - Taking on the gap pays a real move to the fee.
- **The one positive family is a lead-lag position taken passively.** Quote only the side the
  Coinbase lead leaves safe, and hold what fills, up to the position cap. It needs no speed, and a
  lower fee tier helps it: at 0.8 bp, every candidate's 3.5-hour total is +$148 to +$303.
  - It is not established. 3.5 hours do not separate +$16 to +$61 an hour from zero.
  - Its risk is the inventory: up to $5,000 a coin, nine coins.
- **What would establish it:**
  - a second registered run of 15-30 hours, unchanged, including a weekday's US hours;
  - then real orders at the minimum size, which the fill model cannot replace.

## Limits

- One night (Asia afternoon to Europe morning) and one market state.
- **Paper fills.** The orders were never in the book: takers did not react to them, and other
  makers could not step in front of the inside-the-spread quotes. Cancels are assumed to come from
  behind (risk-averse), so the queue ahead drains only through trades.
- **Coinbase is spot; Hyperliquid is a perp.** The 5-minute EWMA removes the basis, not funding
  jumps.
- Each 10-minute refit of the model stalls the event loop briefly (`slow_ticks`, up to 18 per
  segment). The gap strategies do not use the model, but they stall with it.
- Segments start flat and are marked to the mid at their end, with no exit cost. Flattening
  $5,000 at the touch would cost about the half-spread plus the taker fee once per coin and segment,
  under $25 a segment in all.

## Files

| File | What |
|---|---|
| `eval/paper/forward_test_20261106.json` | The held-out hours, every strategy and coin (`cli.paper_report`) |
| `eval/paper/forward_test_verdict_20261106.json` | The registered statistic, 0.8 bp tier, and each candidate vs `touch` |
| `eval/paper/forward_test_drift_timing_20261106.json` | Position PnL split into drift and timing, per coin and segment |
| `eval/paper/selection_20261106.json` | The live selection hour |
| `eval/paper/selection_grid_*.json` | The grid the candidates were picked from (first 70 minutes, replayed) |
| `eval/paper/replay_{us200,us50,tokyo}_20261106.json` | The held-out hours replayed at each location and latency |
| `eval/paper/journal_night_20261106.{json,md}` | The night's decision journals read by `cli.paper_journal`: fills by markout horizon and by what the strategy saw, side changes, pulls, actions |

The raw recordings (about 300 MB, `data/paper/*/raw/`) are not committed.
