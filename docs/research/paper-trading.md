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

The order actions themselves (500-1,800 a minute per strategy over the nine coins) are counted,
not listed. At the night's pace the journal of 21 strategies is about 12 MB an hour; the raw
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
- **Rate limit:** 0.05-0.35 order actions per USD filled for every quoter but the reservation pair
  (0.75), all under Hyperliquid's one per USD.

Ideas these point to, none tested: a hysteresis band on the pull threshold (fewer flips, fewer
actions, queue kept); a position target from a forecast over 15 minutes rather than 10 s; holding
the position longer when the lead still points its way (closing fills lose).

## The 24-hour run's first hours: a fast clock and a choppy market (`eval/paper/clock_and_market_20261106.json`)

From 16:06 to 18:06 UTC every strategy lost: the four candidates -$163 to -$212 an hour, against
+$16 to +$61 in the night's forward test, and `touch` -$834 against -$721. Two causes, measured.

- **Caesar's PC clock was 223-345 ms fast.** On that machine Coinbase messages arrived at least
  238-360 ms after Coinbase stamped them; in the cloud the night before, 14-25 ms. The gap grew in a
  straight line, +61 ms an hour (a quartz clock left unsynced), and from 18:09 Windows slewed it back
  (206 ms at 18:44). Hyperliquid's minimum delay moved by the same amount. So the dashboard's 612 ms
  Hyperliquid delay is about 340 ms of real delay (the cloud's) plus the clock.
  - The engine times paper orders on the local clock against Hyperliquid's block times. A fast
    clock delays every order and cancel by its offset: 420-550 ms, not the registered 200 ms.
  - On the night's held-out hours, a replay as recorded matches the live forward test
    (`improve+gap@0.25` +$61 an hour; live +$60.5). With a clock 285 ms fast it is -$27 an hour,
    and every candidate turns negative (-$27 to -$124). Cancels land late, so fills rise by half.
  - On the first live segment, taking the measured offset off every receive time
    (`--clock-offset coinbase`) moves `improve+gap@0.25` from -$162 to -$97 an hour and cuts its
    fills by 35%.
- **The afternoon market did not trend.** In the night's held-out hours seven of nine coins rose
  steadily (+66 to +138 bps) and BCH fell 236 (median 15-minute variance ratio 1.07). From 16:06 to 18:06 none moved
  far (within -56 and +11 bps), one-minute volatility was a third higher (10.2 against 7.6 bps a
  minute), and moves reverted over 15 minutes (variance ratio 0.89).
  - With the clock fixed, the candidates' fills look like the night's over the first minute
    (`improve+gap@0.25` markout -$14 an hour at 60 s; night -$33). The difference is later: at
    15 minutes the night's fills were +$48 an hour, today's -$126.
  - The lead still works: after a pull the mid moves 0.59 bps towards the pulled side within 10 s
    (55% of pulls), as at night (0.56, 54%).
- **Reading.** The night's profit was the inventory riding a steady move, as the journal showed.
  In a choppy afternoon it is not there. The pulls still cut the loss against `touch` by about
  $650 an hour, but they do not make money on their own. The registered run cannot be read from its
  live PnL while the clock is off. Its recordings can be replayed with the offset taken off, which
  restores the registered 200 ms (deviation in the pre-registration).

## Tuning at a $5,000 budget (`cli.paper_tune`, `eval/paper/tune_20261106.{json,md}`)

Each family ran over a grid of its parameter, at three sizings (quote USD x quotes a coin: 100x10,
250x4, 500x2), with one $5,000 budget of gross exposure per strategy over the nine coins. Data:
8.19 hours of 2026-11-06, the night's segments 2-4 and the live run's first two segments with the
clock corrected. A segment chain carries the model state, as the live run does. A second pass
extended the grid where the first one's best sat on its edge.

- **Selection.** Per family, the setting with the most PnL over all five segments. The honest
  number is the left-one-segment-out estimate: pick on four segments, score on the fifth.
- **Hyperliquid's rate limit decides.** Hyperliquid allows one order request per USD traded, after
  a 10,000-request buffer; cancels get twice that. A maker's actions are half orders (50.0-50.2% in
  the journal). The paper winners at $100 quotes (+$7-8 an hour) sent 1.2-1.7 orders per USD filled:
  live, they would run out of requests within the hour and be cut to one every 10 s. They are not
  selectable.
- **Within the limit**, the best are the gap quoters with near-zero thresholds at $250 quotes: quote
  only the side the Coinbase lead favours, almost always.

| Family | Pick | Orders per $ | In-sample $/h | Left-out $/h | Each segment $/h |
|---|---|---:|---:|---:|---|
| improve+gap | `improve+gap@0.05`, 250x4 | 0.60 | +1.7 | +1.7 | +5.4, +6.8, +4.0, -11.8, +8.0 |
| zgap | `zgap@0.05`, 250x4 | 0.59 | +2.1 | +1.3 | +4.7, +9.0, +4.5, -13.0, +9.1 |
| gap | `gap@0.1`, 250x4 | 0.71 | +1.8 | +0.6 | +7.1, +8.0, +4.2, -13.4, +7.6 |
| hawkes | `hawkes@1.25`, 250x4 | 0.58 | +0.1 | -1.6 | |
| kelly | `kelly@5`, 250x4 | 0.96 | -1.0 | -1.0 | |
| model | `model@0.25`, 250x4 | 0.31 | -26.2 | -26.2 | |
| touch | 100x10 | 0.22 | -67.7 | -67.7 | |

- At $5,000 the registered values lose: `improve+gap@0.25` -$4.6 an hour, `gap@0.25` -$2.4 at
  250x4. The night's +$61 an hour at $1,000 quotes and no budget was the uncapped inventory riding
  the trend; the budget caps that.
- The reservation-price quoter sends 1.3-1.9 orders per USD filled at $250 quotes, at every skew.
- **Noise.** The picks' 15-minute block PnL has a standard deviation of about $6.3 against a mean of
  about $0.45. A day cannot tell that from zero; about 9-13 days can.
- **Registered:** the three picks, 14 days live on paper from 2026-11-06
  (`docs/preregistration/paper-tuned-5k-20261106.md`, `scripts/run_paper_tuned.ps1`, port 8766,
  beside the 24-hour run). Its live view shows the BTC mid on the PnL chart and the clock
  correction in the header.

## A market maker with inventory and risk control (`paper/mm.py`, `eval/paper/*mm*_20261106.*`)

The gap quoters sit at the touch and stop a side only at a coin's position limit. Their PnL is
mostly the position they hold times the market's move: net short, it moves against BTC. `mm@...` is
the textbook market maker instead.

- **Fair price:** the mid, plus the 10 s Coinbase lead-lag forecast, plus the microprice's offset.
- **Centre:** the fair price, shifted by the coin's position (`skew` bps at its limit) and the
  strategy's net dollars over the nine coins (`nskew` bps at `net`). Avellaneda-Stoikov's
  reservation price, with the drift and the inventory term set in bps.
- **Quotes:** `h` bps either side of the centre, rounded away from it, post-only. A live order stays
  while it is within a quarter of `h` of its target, which keeps its place in the queue and the
  cancels inside Hyperliquid's rate limit.
- **Limits:** no bid at the coin's limit or at `+net` net dollars; no ask at the opposites. A side
  is pulled while takers hit it in a burst.
- **Exits with a taker order** (4.5 bp, through the seen book):
  - **stop:** the mid 30 bps against the position's average entry; then no quotes in that coin for
    60 s;
  - **kill switch:** the strategy's equity $50 below its peak; every coin is closed and nothing is
    quoted for 10 minutes;
  - **hold (off by default):** a position open longer than `hold` seconds.
- **Dead man's switch:** either feed silent for 3 s cancels every quote, as Hyperliquid's
  `scheduleCancel` would.

**Replays.** The tuned run's 8.19 hours selected on (night segments 2-4, live segments 1-2 with the
clock corrected), with the tuned run's first 0.95 hour held out (20:03-21:00 UTC, never used to
pick). $250 quotes, 4 a coin, $5,000 gross budget. The grid was `h` 0-5 bps at two skews, plus each
risk control switched off in turn at `h` 1.5 and 3.

| Strategy | Orders per $ | Here, 200 ms | Held-out hour | Tokyo, 20 ms | 0 bp maker fee | Tokyo and -0.3 bp |
|---|---:|---:|---:|---:|---:|---:|
| `touch` | 0.10 | -145.5 | -98.7 | -125.7 | -74.4 | -43.7 |
| `mm@0` | 0.19 | -64.6 | -55.1 | -52.1 | -27.7 | -5.3 |
| `mm@1` | 0.64 | -22.6 | -23.5 | -11.6 | -6.7 | +2.6 |
| `mm@1.5` | 0.97 | -13.8 | -9.7 | -6.0 | -4.6 | +2.1 |
| `mm@h=2/skew=6` (pick) | 0.86 | -12.7 | -11.4 | -6.1 | -3.9 | +1.1 |
| `mm@3` | 2.00 | -6.5 | -2.3 | -0.8 | -3.9 | +1.3 |
| `mm@5` | 3.86 | -3.6 | | -1.0 | -2.9 | -0.5 |
| `zgap@0.05` | 0.59 | +2.1 | +9.7 | +4.3 | +10.2 | +17.8 |

$ an hour over the nine coins. Orders per $ are at 200 ms; the Tokyo replays send more (`mm@1.5`
1.27). Tokyo: each Hyperliquid message 50 ms after its block, Coinbase 70 ms later than here,
orders in 20 ms.

- **Every setting loses at this PC's speed and the base fee.** The pick within the rate limit,
  `mm@h=2/skew=6`, loses $12.7 an hour in-sample, $14.9 left-one-segment-out and $11.4 on the
  held-out hour. Quoting further away loses less an hour, but only by trading less: per filled
  dollar it loses more. `mm@2` and wider are over the rate limit.
- **Where the money goes** (`mm@1.5`, bps of each filled dollar):

  | | Spread earned | Move within 1 s | Fee | Rest | Total |
  |---|---:|---:|---:|---:|---:|
  | Here, 200 ms | +0.58 | -1.27 | -1.63 | +0.17 | -2.15 |
  | Tokyo, 20 ms | +0.99 | -0.94 | -1.63 | +0.31 | -1.28 |

  The spread is there. The mid moves against each fill by more than that within a second: takers hit
  the quotes that are about to be stale. Further away the spread grows, and so does the move against
  (`mm@3`: +0.84 against -2.04). The fee then takes 1.5 bp more. The stops' taker orders add about
  0.1 bp.
- **Speed:** from Tokyo the spread covers the move against it, but not the fee. Half the loss goes.
- **Fees:** a 0 bp maker fee needs $500M of volume in 14 days; the -0.3 bp rebate needs over 3% of
  all of Hyperliquid's maker volume. Only with both Tokyo and the rebate do the market makers turn
  positive: +$1 to +$3 an hour, inside their intervals, and `mm@1` loses $3.2 on the held-out hour.
  At $5,000 these trade $0.5-2.5M a day; the 0 bp tier alone needs about $36M a day.
- **The risk controls** (`mm@1.5`, $ an hour): all off -16.7; without the stop -15.6; without the
  net cap -16.4. The stop fired 61 times in 8.19 hours. The kill switch never fired at $50.
  Closing every position after 60 s costs more than it saves (-28.9). Without the forecast in the
  fair price the loss nearly triples (-37.5). The controls cut the loss by about $3 an hour; they
  do not turn it into a profit.
- **The gap quoters are not market makers.** `zgap@0.05` earns +0.15 bp of spread, loses 0.37 bp
  within a second, and pays 1.5 bp in fees. It makes its +2.12 bp from holding positions the Coinbase
  lead points to. It is a slow directional strategy that enters with maker orders, and a lower fee
  helps it more than speed does.
- **Registered:** `mm@h=2/skew=6`, 7 days live on paper beside the other runs
  (`docs/preregistration/paper-mm-20261106.md`, `scripts/run_paper_mm.ps1`, port 8767). The
  prediction is that it loses; the live view now shows each strategy's net position beside its
  gross.

## From the research: the wallet factor in the gap quoter (`guard@`, `eval/paper/results_20261106/`)

A1 found two signals that hold out of sample: the Coinbase gap (3 of 3 coins at 1, 10 and 60 s)
and the wallet score, each taker's past markout (3 of 3 at 1 and 10 s). The gap quoters use the
first. `CoinState.informed` makes the second live: over the last 1 or 5 s, the takers' signed
notional times each taker's wallet score as it stood when the trade arrived, over the notional, and
`informed_z` divides it by its own volatility. `guard@z=<z>/w=<w>/win=<s>` is `zgap@<z>` that also
pulls the side informed wallets are taking (`|wallet z| > w`). `paper.mm`'s position control and
exits are available on it (`lean`, `net`, `stop`, `dd`).

**No look-ahead** (`cli.paper_lookahead`, `eval/paper/lookahead_20261106.json`). The live segment
of 18:06 UTC was replayed in full and again cut off at a third and at two thirds of the way. A
decision that used anything received after the cut would differ before it. Before the two-thirds
cut, every one of 38,006 side changes, 2,868 fills, 6 taker exits and 320,883 per-coin signal
readings was identical. The check has power: with the clock correction the earlier replays used
(each minute's offset interpolated between minute midpoints, so up to 30 s of later Coinbase
timestamps), 472 decisions, 28 fills and 2,695 signal readings before the first cut differ
(`lookahead_interpolated_clock_20261106.json`). Replays now correct the clock from earlier
timestamps only (`--clock-offset coinbase-causal`, `paper_tune --causal-clock`). On the replays
before this, the difference is confined to the clock-corrected 16:06 segment: `zgap@0.05` made
-$13.0 an hour there with the interpolated clock and -$14.4 with the causal one.

**What each signal predicts** (`cli.paper_factors`, `eval/paper/factors_20261106.json`). Every
coin was sampled every 100 ms. Each signal was correlated with the seen mid's move over the next
1, 10 and 60 s (the information coefficient), averaged over the nine coins:

| Signal | 1 s | 10 s | 60 s | 10 s, held out |
|---|---:|---:|---:|---:|
| Coinbase gap z (A1) | 0.50 | 0.23 | 0.10 | 0.23 |
| Microprice | 0.20 | 0.10 | 0.05 | 0.13 |
| Wallet factor, 1 s (A1) | 0.075 | 0.035 | 0.015 | 0.056 |
| Wallet factor, 5 s (A1) | 0.046 | 0.021 | 0.011 | 0.060 |
| Taker imbalance, 5 s | 0.030 | 0.015 | 0.008 | 0.013 |
| Hawkes burst | 0.025 | 0.017 | 0.006 | 0.015 |

Over 1 s the wallet factor is positive in all nine coins at 1 and 10 s on the held-out hours, and
in 53 of 54 coin-segments at 10 s in the selection hours. It is weak next to the gap. In a linear model of
the 10 s move, adding it to the gap raised the held-out R^2 in only 4 of 9 coins. As a pull rule
it does better than that.

**Backtest** (`eval/paper/tune_guard_home_20261106.{json,md}`, `report_guard_*_20261106.json`): the
8.19 selection hours, and the tuned run's 20:03-22:03 UTC held out. $250 quotes, 4 a coin, $5,000.

| Strategy | Orders per $ | $/h | Held out | Against `zgap@0.05`, $/h [95%] | Held out against it | Mean net position | Correlation with BTC |
|---|---:|---:|---:|---|---|---:|---:|
| `zgap@0.05` (running in the tuned run) | 0.59 | +1.8 | +1.9 | | | $1,972 | 0.18 |
| `guard@z=0.05/w=1.5/win=5` (pick) | 0.61 | +4.3 | +3.9 | +2.4 [-0.9, +6.1] | +2.0 [-1.2, +5.4] | $1,907 | 0.19 |
| `guard@z=0.05/w=1/win=1` | 0.62 | +2.1 | +4.1 | +0.3 [-3.1, +3.9] | +2.2 [+1.3, +3.2] | $2,038 | 0.13 |
| `guard@z=0.05/net=2000` | 0.60 | -2.5 | -5.5 | -4.2 [-9.6, +0.6] | -7.4 [-16.4, +0.7] | $1,241 | 0.04 |
| `guard@z=0.05/lean=0.5` | 0.64 | -1.1 | +1.2 | -2.8 [-6.3, +0.4] | -0.7 [-4.7, +3.4] | $1,495 | -0.01 |
| `guard@z=0.05/stop=30` | 0.51 | -4.4 | +2.8 | -6.0 [-9.3, -2.6] | +1.0 [-6.4, +8.8] | $1,897 | 0.08 |
| `mm@h=2/skew=6` | 0.86 | -12.9 | -9.3 | -14.1 [-24.4, -5.3] | -11.1 [-29.9, +7.9] | $174 | -0.02 |
| `touch` | 0.10 | -145.6 | -86.6 | | | $2,111 | -0.16 |

- **8 of the 10 wallet settings beat `zgap@0.05` in-sample** (+$2.1 to +$4.3 an hour against
  +$1.8). The pick is the same on four of five left-out folds; left-one-segment-out it makes +$3.1.
  - On the held-out hours every setting is ahead too (+$2.2 to +$6.2 against +$1.9).
  - The pick's paired interval includes zero in both periods. About 7 days of live data would
    resolve +$2 an hour.
- **Where it comes from:** the pick's spread, 1 s move and fees per filled dollar are those of
  `zgap@0.05` (+0.17, -0.40, -1.50 bp against +0.15, -0.38, -1.50). Its position PnL is larger:
  +2.60 bp against +2.06. Pulling the side informed wallets take keeps it out of positions that
  are about to go against it.
- **Position control costs the edge:**
  - The $2,000 net cap cuts the correlation with BTC from 0.18 to 0.04 and the mean net
    position by more than a third. It also loses $4.2 an hour against `zgap@0.05`.
  - The stop loses $6.0 an hour in-sample.
  - The profit is the position the Coinbase lead points to, and capping the position caps it.
  - Over these hours the gap quoter's PnL moves with BTC, not against it (0.18). The negative
    stretch on Caesar's screenshot was a short window of net-short inventory. `touch`, which
    holds whatever fills, is the one that is reliably against BTC (-0.53 on the held-out hours).
- **Is it new?** Not as a factor. Zhai (arXiv:2608.04373, August 2026) scores Hyperliquid wallets
  by the 10 s markout of their aggressive orders and finds the scores add forecasting power beyond
  anonymous order-flow features. Cartea and Sánchez-Betancourt use client identity in FX to detect
  toxic flow, and Barone and Lillo (arXiv:2606.15715) study adverse selection on Hyperliquid.
  Commercial tools sell wallet tracking. What is this project's own:
  - the score updated online as each markout resolves, shrunk toward zero;
  - its pre-registered test (A1);
  - its use as a pull rule beside the Coinbase gap;
  - a test against fees, latency, queue position and Hyperliquid's rate limit.
  Zhai's paper leaves an implementable strategy out of scope.
- **Registered:** `guard@z=0.05/w=1.5/win=5` against `zgap@0.05` on the same blocks, 7 days live
  on paper in the market maker's window (`docs/preregistration/paper-mm-20261106.md`, second
  hypothesis; `scripts/run_paper_mm.ps1`, port 8767). The results page draws on
  `eval/paper/results_20261106/` (`scripts/paper_results_data.py`).

## A fill-toxicity quoter, an optimal-control market maker, and one locked test (2026-11-07)

**Question:** is there a better market maker, built from the project's results and tested without
cheating? Everything was chosen on the selection hours. The 2 h held out were checked. Then
5.91 h recorded on the PC after all of them were locked and scored once
(`docs/preregistration/paper-locked-test-20261107.md`).

**MarketImmune's own question asked of every quote** (`paper/immune.py`, `cli.paper_fills`,
`cli.paper_immune_fit`; `eval/paper/immune_fit_20261106.json`):

- **Data:** `touch` quoting every coin without limit gives every fill a touch quote could get:
  36,903 in the selection hours. Each is joined with the signals of the last tick at least 200 ms
  before it, the last moment a cancel could still have landed.
- **Model:** ridge regression per horizon, with an intercept per coin, of the fill's markout (bps
  from its price to the seen mid 10, 30 or 60 s later).
- **Held out:**
  - **Accuracy:** correlation 0.30 at 10 s, 0.20 at 30 s, 0.10 at 60 s. LightGBM adds 0.02 at
    10 s.
  - **Touch fills:** they lose 2.9 bp after the fee on average, and the decile the model likes
    best only breaks even before it.
- **The quoter:** `immune@h=<s>/t=<bps>/risk=<phi>` quotes a side while
  `predicted markout - fee - phi * sigma_h^2 * (2 * side * position + quote) / 1e4 >= t`. The last
  term is the mean-variance cost of the inventory the fill adds.

**The market maker's optimal control problem** (`paper/optimal.py`, `cli.paper_optimal_fit`;
`eval/paper/optimal_fit_20261106.json`):

- **Model,** per coin, one step a second:
  - **States:** the position, from -4 to +4 quotes, and 7 market states, the quantiles of a
    least-squares prediction of the next 10 s move from gap z, microprice, wallet factor and taker
    imbalance.
  - **Measured:** the drift in each state, a Markov chain between states, and each side's fill
    probability and first-second fill value from the touch fills.
  - **Reward:** position x drift - phi x position^2 x variance + fills x (value - fee).
- **Value iteration** gives the policy.
- **With any inventory aversion it never opens a position.**
  - **Edge:** the predictable move is at most about 1.2 bp in the top state, and spent within
    5-15 s; it saturates by then.
  - **Cost:** the 1.5 bp fee plus 0.5-1 bp of adverse move on a fill.
  - Under the model, no quoting policy is profitable from these signals' short-term
    predictability.
  - What the gap quoters earn is position held for minutes.

**Selection** (`eval/paper/tune_immune_home_20261106.{json,md}`):

- **The toxicity veto on top of gap + wallets:** -$1.8 an hour in-sample at `veto=-2`, +$3.4 on
  the held-out hours.
- **`immune@h=30/t=-1`:** +$8.5 an hour in-sample, but its model was fitted on those hours, and it
  sends 1.18 orders per $. It made +$1.2 an hour on the held-out hours.

**Overfitting** (`paper/overfit.py`, `cli.paper_overfit`; `eval/paper/overfit_20261106.json`), on
46 candidate settings in 34 blocks:

- **Probability of backtest overfitting by CSCV:** 0.03.
- **Deflated Sharpe ratio of the gap + wallets pick:** 0.001, counting 186 settings tried on these
  hours. Its plain probabilistic Sharpe is 0.78.
- **Reading:** a good choice among candidates, but not separable from luck.

**The locked test** (5.91 h, 24 blocks; `eval/paper/locked_test_20261107.{json,md}`,
`locked_test_report_20261107.json`):

| Strategy | $/h [95%] | Against `zgap@0.05` [95%] | Net position | BTC correlation |
|---|---|---|---:|---:|
| `immune@h=30/t=-1` | +2.40 [-1.04, +5.44] | +3.52 [-1.24, +7.56], 16/24 blocks | $818 | +0.01 |
| `optimal@phi=0.01` | 0 (never traded) | +1.16 | $0 | |
| `guard@.../veto=-2` | -0.13 | +1.03 | $1,243 | +0.04 |
| `zgap@0.05` | -1.18 [-4.80, +2.60] | | $1,344 | -0.11 |
| `guard@z=0.05/w=1.5/win=5` | -1.75 [-5.16, +1.76] | -0.56 [-1.64, +0.56] | $1,219 | -0.14 |
| `mm@h=2/skew=6` | -7.04 [-9.08, -5.04] | -5.77 | $172 | +0.22 |
| `touch` | -46.88 | -44.97 | $1,604 | +0.25 |

- **The registered primary failed.** The wallet factor did not add to the gap quoter on fresh
  hours.
- **The toxicity quoter came first,** with the least exposure and no BTC correlation.
  - **Per filled dollar:** spread +0.60 bp, 1 s move -0.13, fee -1.50, position +3.39.
  - **Over the held-out and locked hours:** about +$2 an hour over 7.9 fresh hours.
  - Its interval still includes zero. A live registered test is the next step, not money.

## Why every strategy loses in quiet hours, and the range test (2026-11-07)

**Data:**
- The tuned run's fresh live hours, 04:09-14:10 UTC: 10 h, `eval/paper/report_live_tuned_20261107.json`.
- All 27.9 recorded hours of mids: `eval/paper/range_vr_20261107.json`.
- Code: `paper/range_study.py`, `cli/paper_range.py`.

**The fee is three times the edge.**

| Live, fresh hours, bp per filled $ | spread | 1 s move | position | fee | total | break-even maker fee |
|---|---:|---:|---:|---:|---:|---:|
| `zgap@0.05` | +0.33 | -0.20 | +0.39 | -1.50 | -0.98 | 0.52 |
| `gap@0.1` | +0.25 | -0.43 | +0.54 | -1.50 | -1.14 | 0.36 |
| `hawkes@1.25` | +0.34 | -0.20 | +0.01 | -1.50 | -1.35 | 0.15 |
| `touch` | +0.04 | -1.11 | -0.38 | -1.50 | -2.94 | -1.44 |

- **Spreads are narrower than the fee.** The median spread at a fill is 0.1 bp (BTC, SOL), 0.45 (ETH)
  and up to 1.8 (LINK). A maker round trip at the touch earns at most one spread and pays 3 bp.
- **Moves continue within the minute.** Var(n s)/(n Var(1 s)) is 1.2-1.4 at 5 s and 1.35-1.8 at
  60 s, so a fill at the touch is followed by more of the same move.
- **Minutes look like a random walk.** Variance ratios of 1-minute returns at 5, 15 and 30 minutes
  average 1.01, 0.99 and 0.86. The permutation null gives 0.99, 0.97 and 0.95 (p = 0.60, 0.61, 0.26).
- **A volatility filter does not rescue it** (`eval/paper/vol_regime_20261107.json`; 86 blocks of
  `zgap@0.05`, by trailing 30-minute volatility):
  - $ an hour by tercile: quiet -2.0, middle -6.7, busy +0.7.
  - The correlation with volatility is 0.0.

**The range (band) maker** (registered: `docs/preregistration/paper-range-20261107.md`)
- **Rule:**
  - **Quotes:** rest a buy and a sell about 7.7 one-minute sd from a 60-minute average of the mid.
  - **Exits:** leave at the average as a maker, or at 3 bands or 120 minutes as a taker.
- **Selection hours:** the best of 96 settings ($1.24 an hour at $500 a trade) is no better than the best
  of 96 settings on hour-shuffled copies ($0.8-1.3).
- **Held-out hours, scored once** (11.2 h):
  - **Gross:** +2.4 bp per round trip, above all 40 shuffled copies (mean -2.3).
  - **Net:** -1.0 bp and -$0.14 an hour [-2.07, +1.47].
  - **Reading:** the reversion is real, but smaller than the 3 bp of maker fees. With no fee at all it
    would make $0.27 an hour.

**The fee schedule** (Hyperliquid docs):
- **Volume tiers:** perps maker 1.5 bp at tier 0; 1.2 above $5M of 14-day volume; 0.8 above $25M;
  0.4 above $100M; 0 above $500M.
- **Staking discounts:** 5-40%, with 40% at 500,000 HYPE staked.
- **Referral:** 4% for the first $25M.
- **Rebates:** only above 0.5% of the venue's maker volume.
- **What it takes:** the best break-even fee here (0.52 bp) needs tier 3, about $300,000 of volume
  an hour.

**Funding** (`eval/paper/funding_20261107.json`, 60 days to 2026-11-07):
- **Shorts are paid in quiet markets:** with no premium, Hyperliquid's funding is the interest
  term, 0.00125% an hour (about 11% a year), paid by longs to shorts.
- **BTC:** 9.0% a year over 60 days; positive in 93% of hours and exactly the base rate in 68%.
- **Other coins:** 7-11%, HYPE 10.7%.
- **The carry trade:** short the perp, hold the coin, and the price risk cancels. It is the only edge
  in these data that is larger than its cost, and it is small: about $1.2 a day on $5,000 hedged.

## Five candidate winning strategies, each scored once (2026-11-07)

Registered in `docs/preregistration/paper-five-candidates-20261107.md`; settings fixed on the
selection hours; held-out A + B = 2026-11-07 04:09-17:00 UTC (12.8 h).

| # | Candidate (what it uses) | Result [95%] |
|---|---|---|
| 1 | **Funding carry**: short perp + Hyperliquid spot, BTC/ETH/SOL/HYPE/AVAX (funding) | **+7.4% a year net [5.4, 9.5]** over 60 days, t = 7.9, both 30-day halves positive |
| 2 | Fill-toxicity quoter `immune@h=30/t=-1`, replayed (ridge markout model) | -$1.33/h [-4.48, +1.72]; vs the gap quoter +$3.50/h [+0.56, +6.56] |
| 3 | Range swing maker: exit half a band past the average (range reversion) | -$0.38/h [-2.58, +1.70]; gross +1.8 bp beats 40/40 shuffled copies |
| 4 | Hybrid Transformer on 120 s of 1-s bars + the ridge features (Coinbase lead, flow, book) | correlation 0.30 (ridge 0.35); kept fills -$0.34/h [-0.73, +0.07] |
| 5 | Cross-coin pairs against BTC (residual reversion at 30-60 min) | eliminated in selection: all 36 settings negative after four maker fees |

- **Market making:** all four candidates carry real information, and none clears the base maker fee.
  - The best tenth of touch fills by either model earns +0.1-0.2 bp before a 1.5 bp fee.
  - The toxicity quoter is the better live choice than `zgap@0.05`: it loses $3.50 an hour less,
    an interval above zero.
- **Carry:** funding at the interest rate is the one edge larger than its cost. It is small, about
  $1 a day per $5,000 hedged, and needs the spot leg (Hyperliquid spot fees 4 / 7 bp).

## Five market-making candidates, scored once on unseen hours (2026-11-07, evening)

Registered in `docs/preregistration/paper-mm-five-20261107.md` (and Addenda A and B).
- **New engine quoters:** `disloc@`, `lead@` and `sweep@` (`paper/strategies.py`).
- **Transformer gate:** `cli/paper_gate.py`.
- **Long-tail simulator:** `paper/tailmm.py`.
- **Bar-level exploration:** `paper/mmlab.py`.

**What was new:**
- **Coinbase-anchored quoting:** quotes anchored to the Coinbase-implied fair price instead of
  Hyperliquid's own mid.
- **A Transformer gate:** it guesses each fill's probability of beating the fee.
- **A new market:** perps whose spread exceeds two maker fees, recorded live for the purpose (24
  coins).

| Candidate | Picked on, $/h | Unseen hours, $/h [95%] |
|---|---:|---|
| Lead-lag dislocation maker `disloc@d=3/x=1` | -4.5 | -2.06 [-3.00, -0.96] |
| Lead-lag Avellaneda-Stoikov `lead@h0=2` | -4.8 | -1.17 [-2.08, -0.08] |
| Sweep catcher `sweep@move=5` | -3.9 | -0.39 [-0.56, -0.16] |
| Transformer win-probability gate on `zgap@0.05` | -0.28 (validation) | -0.03 [-0.16, +0.11], 8 of 366 fills kept |
| Long-tail spread maker `tail@spread=4/n=1/flow=10` | -14.1 | -22.25 marked; 60 s markout after the fee -20.04 [-33.93, -9.02] |
| `zgap@0.05` at 0 bp and 400 ms (zero-fee venue proxy) | +0.97 | -0.27 [-2.36, +1.80] |
| `zgap@0.05` (baseline) | -3.5 | -4.76 [-6.72, -2.24] |

- **Distance does not escape adverse selection.** Quoting further from the touch earns more spread
  per filled dollar, and loses as much to the move within the next second:
  - `disloc@d=5`: spread +1.41 bp against a -1.80 bp move.
  - `lead@h0=4`: spread +2.12 bp against a -2.50 bp move.
  - Anchoring to Coinbase does not change this. A fill far from the mid usually comes from a move
    Coinbase is making too, faster than a 200 ms quote update.
- **The Transformer ranks fills but finds none that pay.** AUC was 0.62 on validation and 0.65 on
  the test. Even the fills it is most sure of lose after the fee.
- **The long tail is worse, not better.**
  - Fills earn about 2.2 bp of spread against the mid.
  - The mid 60 s later is past the fill price against them (-1.7 bp on the test hour).
  - Takers in thin markets are informed, or the quotes flicker.
- **Speed and fee are the levers, not the signal** (exploratory, the gap quoter at 0 bp):
  - On the selection hours its break-even maker fee rises from 0.18 bp at 400 ms to 1.01 bp at 50 ms.
  - On the evening's unseen hours it lost before any fee at every delay.
  - A Hyperliquid account would need both colocation and a fee tier near 0.8 bp, which needs about
    $25M of 14-day volume.

## The quiet-depth maker: A1's wallet score as a quoting gate (`hush@`, 2026-11-07, night)

Built from this project's own result rather than a textbook rule: A1/A4's per-wallet toxicity score
(`paper/signals.py`, `Wallets`), shared across coins and updated live from the trade feed.
Registered in `docs/preregistration/paper-hush-20261107.md` with Addendum A. The test hours are the
PC's 23:20-15:20 UTC segments, which were recorded after the registration commit.

**The rule.**
- Rest a bid and an ask `d` bp from Hyperliquid's mid, passive only.
- Quote only while no wallet scoring at least `inf` bp (with ≥5 scored takes) has taken the coin in
  the last `quiet` seconds. `signals.CoinState.informed_quiet_ms` tracks this.
- **Why** (trade-level check, 39.5 h, 300k taker events, 27k wallets):
  - The top tenth of wallets cost the maker −2.07 bp at 10 s.
  - Prints at least 1 bp from the mid earned +1.52 bp at 30 s [1.06, 1.86] when no informed wallet
    had taken for 5 s.
  - A1: informed toxicity decays over about 100 blocks (7 s).

**Selection** (31.9 h; `eval/paper/tune_hush_{selection,controls}_20261107.*`,
`hush_markouts_20261107.csv`):
- **The gate works.** On the same 3 bp quotes, every gated setting beats the ungated one, with the
  paired interval above zero:
  - ungated `hush@d=3/quiet=0`: −$2.57/h;
  - gated: +$1.1 to +$2.3/h, paired +$3.6 to +$4.8/h;
  - `inf=0.665`: +4.77 [+2.24, +8.16], better in 84 of 130 quarter-hours.
  - The fills' 30-minute markout improves from −3.71 to −2.19 bp.
- **Depth matters:** d = 1 / 2 / 3 bp gives −$18.7 / −$5.2 / +$1.1 an hour.
- **The registered pick,** `hush@d=3/quiet=5/inf=0.665/tol=0.3`:
  - +$2.28/h [−0.52, +5.12]; left-out +2.3; 0.62 orders per $.
  - This is the first maker in this project positive on its selection hours within the rate
    limit. Every earlier candidate was negative there.
- **Where its money comes from.** The fills lose before the fee at every horizon up to 30 minutes:
  −1.31 bp at 1 s, −2.43 at 60 s, −3.41 at 5 min, −2.19 at 30 min.
  - The total is positive because quotes 3 bp deep on both sides build a position against large
    moves, and in these range-bound hours those moves came back within the hour. This is the same
    reversion the band test measured (gross +2.4 bp per round trip).
  - In a trending market the same position would lose.
- **Why the trade-level +1.52 bp does not carry over.**
  - At 200 ms, a resting quote 3 bp from the mid is filled mostly by moves that slide to it over
    several blocks, not by one sweep. For the pick, 495 of 1,548 fills came within 0.5 bp of the
    previous block's mid.
  - **By the slide toward the quote in the previous 300 ms,** markout at 30 s:
    - more than 2 bp: −3.56 bp;
    - under 0.25 bp: −0.39 bp.
  - Even the cleanest fills lose before the fee.
  - **Where the gate helps.** It does not help on the single-sweep fills: those more than 2.5 bp
    from the previous mid make +0.40 bp at 30 s ungated, −0.96 gated. It helps on the slides. Fills
    after a 2 bp+ slide lose −5.31 bp ungated and −3.56 gated. The informed wallets are the ones
    pushing the price into the quote, which is what A1's lead time describes.
- **Over the rate limit:** adding the Coinbase gap pull (`z=0.05`) gives fills with positive
  markouts (+0.3 to +0.9 bp) and intervals above zero (+$2.2/h). These variants send about four
  orders per filled dollar, so Hyperliquid's limit rules them out at this size.

**Correction to earlier selection replays.** `paper_tune --clock` kept only its last value, so
`--clock live --clock tuned` corrected one chain. It now accepts every flag (2e00e44).
- **This round:** the 2026-11-06 16:06 and 18:06 segments were replayed again with the correction
  before the pick was fixed (Addendum A).
- **The evening's five market-making candidates:**
  - **Selection replays** (`tune_{lead,latency50,latency100,zerofee}_selection_20261107`): only the
    `tunedB` chain was corrected, so those numbers include about 3.5 h replayed at 420-550 ms.
  - **Test replays:** their chain was corrected (`fresh`), so the registered results stand.

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
- **Funding** is not booked by the engine. `cli.paper_report --funding` settles Hyperliquid's
  hourly funding on the held positions (`paper/funding.py`, rates cached per run). On the 24-hour
  run's first segment (2 h, $1,000 quotes) it was under $0.35 for every strategy.

## Files

| File | What |
|---|---|
| `eval/paper/forward_test_20261106.json` | The held-out hours, every strategy and coin (`cli.paper_report`) |
| `eval/paper/forward_test_verdict_20261106.json` | The registered statistic, 0.8 bp tier, and each candidate vs `touch` |
| `eval/paper/forward_test_drift_timing_20261106.json` | Position PnL split into drift and timing, per coin and segment |
| `eval/paper/selection_20261106.json` | The live selection hour |
| `eval/paper/selection_grid_*.json` | The grid the candidates were picked from (first 70 minutes, replayed) |
| `eval/paper/replay_{us200,us50,tokyo}_20261106.json` | The held-out hours replayed at each location and latency |
| `eval/paper/tune_20261106.{json,md}` | Every family's grid at three sizings and a $5,000 budget on 8.19 hours; picks within Hyperliquid's rate limit, left-one-segment-out estimates |
| `eval/paper/clock_and_market_20261106.json` | The first live segment and the night replayed with and without the PC's clock error; the clock offset; each coin's trend and volatility in both periods |
| `eval/paper/tune_mm_{home,tokyo,fee0,tokyo_rebate}_20261106.{json,md}` | The market maker's grid and risk-control switches with the gap quoters and `touch`, at 200 ms, from Tokyo, at a 0 bp maker fee, and from Tokyo at -0.3 bp; picks within the rate limit, left-one-segment-out estimates, and the held-out hour |
| `eval/paper/report_mm_*_20261106.json` | The same runs' PnL split into spread, move within 1 s, fee and the rest, per strategy and coin (`cli.paper_report`); `home_heldout` is the held-out hour |
| `eval/paper/tune_guard_home_20261106.{json,md}`, `report_guard_home{,_heldout}_20261106.json` | The wallet-factor quoter's grid (wallet threshold and window, position controls) with `zgap@0.05`, `mm` and `touch`; each strategy paired with `zgap@0.05` on the same blocks, with its drawdown, net position and correlation with BTC |
| `eval/paper/factors_20261106.json` | Each signal's information coefficient at 1, 10 and 60 s per coin, selection and held out (`cli.paper_factors`) |
| `eval/paper/lookahead_20261106.json`, `lookahead_interpolated_clock_20261106.json` | The prefix test with the causal clock correction (identical) and with the interpolated one (differs) (`cli.paper_lookahead`) |
| `eval/paper/results_20261106/*.csv` | The tables the results page reads (`scripts/paper_results_data.py`) |
| `eval/paper/report_live_tuned_20261107.json` | The tuned run's fresh live hours (04:09-14:10 UTC) split into spread, 1 s move, position and fee, per strategy and coin |
| `eval/paper/range_vr_20261107.json` | Volatility, within-minute trend ratios, and variance ratios at 5-30 minutes with a permutation null, all 27.9 recorded hours (`cli.paper_range study`) |
| `eval/paper/range_sweep_selection_20261107.json`, `range_test*_20261107.json` | The band maker's 96-setting sweep on the selection hours with hour-shuffled nulls, and its registered held-out test (`cli.paper_range sweep`, `test`) |
| `eval/paper/vol_regime_20261107.json`, `funding_20261107.json` | 15-minute PnL by trailing volatility; 60 days of Hyperliquid funding by coin |
| `eval/paper/tune_lead_selection_20261107.{json,md}`, `..._report_20261107.json` | The lead-lag quoters (`disloc@`, `lead@`, `sweep@`) and `zgap@0.05` on the 28.9 selection hours, with PnL per filled $ by component |
| `eval/paper/tune_zerofee_selection_*`, `tune_latency{50,100}_selection_*` | The same at 0 bp fees and 400, 50 and 100 ms |
| `eval/paper/mmfive_test*_20261107.*`, `gate_zgap_{train,test}_20261107.json`, `tail_{selection,test}_20261107.json` | The five market-making candidates' registered scoring on unseen hours, and the exploratory latency replays |
| `eval/paper/results_mm5_20261107/*.csv` | The tables the results page reads for the candidates |
| `eval/paper/journal_night_20261106.{json,md}` | The night's decision journals read by `cli.paper_journal`: fills by markout horizon and by what the strategy saw, side changes, pulls, actions |

The raw recordings (about 300 MB, `data/paper/*/raw/`) are not committed.
| `eval/paper/tune_hush_{selection,controls}_20261107.{json,md}`, `..._report_20261107.json` | The quiet-depth maker's two grids (depth, quiet window, wallet threshold, ungated control, Coinbase-gap variants) on 31.9 h with the clock corrected; each gated setting paired with the ungated one |
| `eval/paper/hush_markouts_20261107.csv` | Each `hush@` setting's fill markouts at 1 s, 10 s, 60 s, 5 min and 30 min before the fee |
