# Block-accurate quote simulator

The v3 plan's economic test (plan, Integration) needs a maker's PnL with its own quotes in the
book. `sim/pnl.py` and `simulate_policy` approximate it with a fill filter: every historical maker
fill is an opportunity, and a policy says whether it would have been quoting. That ignores queue
position and when our cancels land. It also hands the policies information a quoting maker does
not have (see "What the fill filter got wrong" below).

This simulator replays the rebuilt Hyperliquid book block by block with our orders in it.

## Data: near-touch L4 events

`build_albers_silver --mbo` writes `silver/hyperliquid/mbo/<COIN>/<COIN>-<date>.parquet`
(`albers_l4.MBO_SCHEMA`) from the same replay as Silver L2, after the same warm-up:

- every add and cancel within the top five levels of its side;
- every fill of a resting order, at any depth.

Each row has the order's time priority (`added_ns`, when it started resting at its price) and
whether it was post-only (`alo`). Silver L2 and order events are byte-identical with and without
the flag (2025-12-01 hours 0 to 3). Size on SOL: about 0.75M events an hour, 114 MB a day,
3.5 GB for December. ALO is 99.8% of resting adds.

## Engine (`marketimmune/sim/engine.py`)

Every simulated maker runs through one pass over the day: Silver L2 rows give the book's top,
and the near-touch events give the queue.

- **Block order.** HyperCore runs post-only orders, then cancels, then GTC/IOC orders inside a
  block. An action of ours lands before every taker of its block. Others' post-only adds in that
  block go ahead of us (their order relative to ours is not recorded); GTC adds go behind.
- **Latency.** A decision taken after the block of an L2 row lands `delay` later (feed plus
  order trip; default 200 ms), in the first block at or after that time.
- **Queue models:**
  - `fifo` (exact from L4): starts behind the level's size plus same-block post-only adds. Every
    cancel or fill of an order that rested before ours moves us up. A fill of an order behind
    ours fills ours first.
  - `risk_averse` (L2, hftbacktest's): moves up only with volume traded at our price, capped by
    the level's size.
- **Sweeps.** A fill beyond our price (an ask lifted above our ask) swept our level, so it fills
  us up to its size.
- **Crossing orders.** A GTC order resting through our quote on the other side would have traded
  with us. A post-only one would have been rejected, so it does not fill us.
- **Rejection.** Our post-only order is rejected if it would cross the book before its block.
- **No market impact.** History replays unchanged: nobody reacts to our orders, and makers do
  not see each other.
- **Data gaps.** Every order is dropped at a gap of more than 30 s (the rebuild resets its book).

Strategies (`sim/strategies.py`), both deciding after every L2 row:

- **S1:** join the best bid and ask with $1,000 a side; stop adding beyond 5 quotes of position.
- **stale:** S1, but pull a side while Binance has moved 2 bps against it since Hyperliquid's mid
  last changed (`cex_gap_maker_bps`, Binance read 300 ms late).
- **S2, S3:** S1, but pull a side while a quote-time model's 10th-percentile markout for that
  side's next fill is below -2 bps (see "Quote-time models" below).

PnL (`sim/attribution.py`), per fill, in USD and bps per filled dollar:

- spread `s(m0 - px)`;
- adverse selection `s(m_1s - m0)`;
- inventory `s(m_end - m_1s)`;
- maker fee (1.5 bp);
- hedge: flatten the day's last position, paying half the spread and a 4.5 bp taker fee.

They add up to the day's PnL. Each day starts flat, so days run in parallel and are bootstrap
units.

## hftbacktest baseline (`sim/hft_baseline.py`, extra `sim`)

The same day goes to hftbacktest 2.4.4 as continuous L2 depth (diffs of Silver rows) and
trades (the fill events). S1 runs in numba every 100 ms, with 100 ms feed and 100 ms order
latency, under hftbacktest's risk-averse and power-probability (n = 3) queue models.

- Its `PartialFillExchange` with the risk-averse model stops with error 14 (InvalidOrderStatus)
  147 s into SOL 2025-12-01, with both of our orders resting and unfilled. So the baseline uses
  `NoPartialFillExchange`. Compare bps per filled dollar, not fill counts or notional.
- An L2 backtester cannot tell post-only orders from GTC, so it fills us whenever the other
  side's book moves through our quote. The engine's `l2_crossing_fills` applies the same rule,
  for reconciliation.

SOL 2025-12-01 (one day), bps per filled dollar:

| Maker | Fills | Spread | Adverse 1 s | Inventory | Fee | Total |
|---|---:|---:|---:|---:|---:|---:|
| Engine `fifo` | 19,636 | +0.30 | -2.02 | +0.51 | -1.50 | **-2.71** |
| Engine `risk_averse` | 17,820 | +0.27 | -2.17 | +0.74 | -1.50 | **-2.67** |
| Engine `fifo` + L2 crossing rule | 44,654 | -0.06 | -1.39 | -0.30 | -1.50 | **-3.26** |
| Engine `risk_averse` + L2 crossing rule | 43,497 | -0.08 | -1.40 | -0.30 | -1.50 | **-3.29** |
| hftbacktest risk-averse | 34,349 | -0.36 | -1.11 | -0.31 | -1.50 | **-3.28** |
| hftbacktest power-prob 3 | 34,820 | -0.33 | -1.12 | -0.31 | -1.50 | **-3.26** |

- **The engines agree.** With the L2 rule, the engine and hftbacktest land within 0.03 bps per
  filled dollar. The split between spread and adverse selection differs because hftbacktest
  stamps a fill at its exchange event, the engine at its block.
- **On this day, post-only rejection is worth 0.55 to 0.62 bps per filled dollar to a touch
  quoter.** Without the L2 rule the engine trades less than half as much and loses less per
  dollar. That rule exists only in L4 data, because only L4 says which orders were post-only.
  Over the month the per-dollar effect does not hold (below); the volume effect does.
- **The queue model matters less than staleness.** Risk-averse and probabilistic queues give the
  same result in hftbacktest: most of S1's fills come from the price moving through quotes not
  yet updated.

On the same day the stale-quote rule improves S1 from -2.71 to -2.29 bps (`fifo`) and from -2.67
to -2.21 (`risk_averse`). Every maker loses money: even before the fee, S1 is -1.21 bps at the
touch.

### The whole month (`eval/sim_hft_sol.json`, SOL Dec 1-31)

| Maker | Fills | Spread | Adverse 1 s | Inventory | Fee | Total | USD/day [95%] |
|---|---:|---:|---:|---:|---:|---:|---|
| Engine `fifo` | 324,155 | +0.28 | -1.76 | -0.18 | -1.50 | **-3.18** | -1,104 [-1,343, -863] |
| Engine `risk_averse` | 267,403 | +0.24 | -1.93 | -0.15 | -1.50 | **-3.35** | -931 [-1,140, -721] |
| Engine `fifo` + L2 crossing rule | 861,530 | -0.09 | -1.24 | -0.36 | -1.50 | **-3.19** | -6,528 [-7,857, -5,090] |
| Engine `risk_averse` + L2 crossing rule | 811,525 | -0.11 | -1.25 | -0.36 | -1.50 | **-3.23** | -6,488 [-7,812, -5,056] |
| hftbacktest risk-averse | 624,692 | -0.40 | -0.95 | -0.36 | -1.50 | **-3.21** | -6,477 [-7,796, -5,052] |
| hftbacktest power-prob 3 | 634,582 | -0.36 | -0.96 | -0.36 | -1.50 | **-3.18** | -6,520 [-7,839, -5,093] |

- **The engines agree on every day.** With the L2 rule, the engine's daily total is within 0.1
  bps per filled dollar of hftbacktest's on 31 of 31 days. The mean gaps are +0.023 (`fifo` vs
  risk-averse), -0.015 (`risk_averse` vs risk-averse) and -0.007 (`fifo` vs power-prob) bps.
- **Over the month, post-only rejection changes volume, not the loss per dollar.**
  - Per filled dollar, without the rule minus with it: +0.10 bps for `fifo` (day-level 95%
    interval [-0.04, +0.26], DM p 0.22) and +0.00 for `risk_averse` (p 0.98).
  - The sign varies by day: the rule costs more than 0.3 bps on 10 days and helps by more than
    0.3 on 8. Dec 1 (+0.54) was one of the costly days.
  - The volume effect is large and stable. An L2 backtester fills S1 2.7 to 3.0 times as often,
    and so loses six to seven times as many dollars a day ($6.5k against $0.9k-1.1k).
- Run per day, cached in `data/gold/hyperliquid/sim_hft/<COIN>/`. `--max-days` bounds a call:
  about 25-35 s per SOL day on the 2-vCPU VM.

## What the fill filter got wrong

The ladder's L0 to L3 feature sets include `sz` (the trade's size) and, from L2 up,
`taker_tox_*` and `taker_log_n` (the taker's own wallet score). Both are known only once a taker
has hit the quote. They are right for the ladder's question: how toxic was this fill? A quoting
rule cannot use them. `simulate_policy`'s S2/S3, which pull on the ladder models' q10, therefore
used information from the fill itself.

S2 and S3 in this simulator need quote-time models: the same Gold rows and walk-forward folds,
without the fill-time columns, predicting each side's next-fill markout at every L2 row.

## Quote-time models (S2, S3)

`marketimmune.sim.signals` and `marketimmune.cli.quote_signals` build them.

- **Columns.** S2 is the `l2_book` rung and S3 the `l3_book` rung, each without `sz`,
  `taker_tox_1s`, `taker_tox_10s` and `taker_log_n`. Every rung-L2 column is a wallet score, so
  S2 is the `l1_book` rung without `sz`: book state, OFI and the CEX gap (15 columns). S3 adds
  the lost-race counts, realised forced flow and the forced-flow forecast (47 columns).
- **Training.** The ladder's own procedure, unchanged:
  - LightGBM quantiles at 0.1, 0.5 and 0.9 with the pre-registered settings;
  - label `markout_bps_1s`, on the same Gold rows (a row with a missing feature is dropped, as in
    the ladder);
  - rolling 7-day folds with a 60 s purge, seed 42 plus the fold number, and the three
    predictions sorted per row.
- **Serving.** Each fold's models predict on every Silver L2 row of the test day, once as a bid
  (`maker_side = +1`) and once as an ask. A row's features are those Gold gives a fill 1 ms
  after the row's block:
  - the book up to and including that block;
  - Binance up to 300 ms before that time;
  - order events and the forecast grid strictly before it.

  Signals sit on the simulator's rows (the last row per block time, as `sim.data.load_day`), in
  `data/gold/hyperliquid/quote_signals/<COIN>/<COIN>-<date>.parquet`.
- **Train/serve check.** Before a day is scored, `check_against_gold` evaluates the quote-time
  features at that day's Gold fill times and compares them with the matrix the models train on.
  A difference stops the run.
  - On SOL (Dec 1, 3, 10, 19 and 31; 55,754 to 160,233 fills a day, all 47 columns), every value
    matched.
  - The largest difference, in the CEX columns on the VM, is 8.9e-12 bps: numpy's `log` differs
    by one ulp between the Windows build that made Gold and the Linux VM. The check's tolerance is
    1e-9 relative.
- **Strategy.** `QuantilePuller` pulls a side while that side's q10 is below `-limit` (2 bps:
  `simulate_policy`'s rule). A row a model cannot score keeps quoting.
- **Coverage.** S3 starts later than S2:
  - S2's first test day is Dec 8.
  - The forecast grid is hazard-scaled from Dec 3, so S3's first test day is Dec 10.
  - Comparisons pair days, so S3 against S2 covers Dec 10 to 31.

### Skill (SOL, out of fold)

Pinball skill against the training window's climatology, on the same fills as the ladder rungs
(the corrected run's out-of-fold predictions):

| Model | Columns | Fills | q10 | q50 | q90 |
|---|---|---:|---:|---:|---:|
| Ladder `l2_book` | S2 + `sz` + wallet | 2,183,820 (Dec 8-31) | 0.413 | 0.320 | 0.311 |
| Ladder `l1_book` | S2 + `sz` | 2,183,820 | 0.327 | 0.296 | 0.307 |
| **S2** (quote time) | 15 | 2,183,820 | **0.287** | 0.282 | 0.307 |
| Ladder `l3_book` | S3 + `sz` + wallet | 1,944,199 (Dec 10-31) | 0.420 | 0.318 | 0.323 |
| **S3** (quote time) | 47 | 1,944,199 | **0.295** | 0.278 | 0.313 |

- The fill-time columns carry 0.126 of the ladder's q10 skill on Dec 8-31: 0.086 from the wallet
  score and 0.040 from the trade size.
- What a quoting maker can know (S2) still keeps 0.287.
- The race and forced-flow columns add little.
  - At quote time, on Dec 10-31's fills, S3's q10 skill is 0.295 against S2's 0.286 (+0.009).
  - In the ladder on the same fills, `l3_book` is 0.420 against `l2_book`'s 0.416 (+0.004).
- On the L2 rows, the 2 bps rule pulls a side on 15% to 58% of rows depending on the day
  (`eval/quote_signals_sol.json`).
- A 20-tree smoke run had q10 below -2 bps on every row. That model sits close to climatology,
  so a run with fewer trees is no guide to the quoting rate.

## SOL December: all strategies

`eval/sim_sol.json`: 200 ms delay, $1,000 quotes, 1.5 bp maker fee.

- S1 and stale are identical to the earlier run (324,155 and 239,933 `fifo` fills).
- The comparisons pair days, so each one covers only the days both makers have.

On the days S3 has (Dec 10-31, 22 days), `fifo`, bps per filled dollar:

| Maker | Fills | Spread | Adverse 1 s | Inventory | Fee | Total | Before fee | USD a day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | 197,086 | +0.28 | -1.74 | -0.23 | -1.50 | -3.19 | -1.69 | -976 |
| stale | 146,174 | +0.31 | -1.46 | -0.10 | -1.50 | -2.76 | -1.26 | -644 |
| S2 | 9,614 | +0.39 | -1.05 | -1.14 | -1.50 | -3.37 | -1.87 | -85 |
| S3 | 14,064 | +0.39 | -0.86 | -1.18 | -1.50 | -3.22 | -1.72 | -108 |

Daily PnL differences (challenger minus base, USD), stationary-bootstrap 95% interval:

| Pair | `fifo` | Days better | `risk_averse` | Days better |
|---|---|---:|---|---:|
| stale - S1 (31 days) | +371 [286, 454] | 31/31 | +295 [224, 363] | 30/31 |
| S2 - S1 (24 days) | +896 [655, 1,157] | 24/24 | +745 [537, 972] | 24/24 |
| S3 - S1 (22 days) | +867 [610, 1,146] | 22/22 | +724 [502, 966] | 22/22 |
| **S3 - S2 (22 days)** | **-23 [-71, +24], DM p 0.43** | 9/22 | **-17 [-62, +33], DM p 0.53** | 6/22 |
| S2 - stale (24 days) | +553 [398, 716] | 24/24 | +468 [334, 615] | 24/24 |

- **No strategy makes money, before or after the fee.**
  - Not quoting at all (PnL 0) beats every maker here.
  - S2's daily PnL interval is [-161, -58] USD; S3's is [-156, -63].
- **S2 and S3 lose less mainly by trading less.** They fill 5% (S2) and 7% (S3) of S1's
  volume.
  - Pulling 15% to 58% of rows removes about 95% of the fills: the models pull when fills
    arrive.
- **Per filled dollar, the models halve adverse selection, and inventory takes the gain back.**
  - Adverse selection at 1 s is -1.74 bps for S1, against -1.05 (S2) and -0.86 (S3).
  - Inventory gets worse, from -0.23 to -1.14 and -1.18. With few, one-sided fills a position is
    held for hours, so this term is mostly the day's drift on a small book.
  - In total per dollar, S2 is slightly worse than S1 and S3 is level with it.
- **S3 against S2, the plan's headline, shows nothing.**
  - The race and forced-flow columns give no measurable economic gain at quote time under either
    queue model.
  - This matches the ladder: H3 is null, and H4 did not replicate on ETH.
- The 2 bps limit is `simulate_policy`'s rule, set before these runs and not tuned. Other limits
  trade volume against adverse selection. The frontier below runs them (exploratory).

## Pull-limit frontier and a time-shifted placebo (exploratory)

`eval/sim_frontier_sol.json` (`cli.pull_frontier`), SOL Dec 8-31 (S3 from Dec 10), `fifo`, the
same engine, costs and S1 as above.
- S2 and S3 pull at limits of 0.5, 1, 2, 3 and 5 bps.
- `s2_shifted` pulls on S2's own q10 series rolled by half the day's L2 rows. It keeps how
  often S2 wants to pull, but not when.
- These limits were run after seeing the 2 bps result, so nothing here is confirmatory.

| Maker | Fills | Adverse 1 s | Inventory | Total | Before fee | USD a day |
|---|---:|---:|---:|---:|---:|---:|
| S1 | 222,231 | -1.75 | -0.21 | -3.19 | -1.69 | -1,004 |
| S2 @ 2 bps | 10,503 | -1.04 | -1.98 | -4.19 | -2.69 | -108 |
| S2 @ 3 | 60,259 | -1.06 | -0.18 | **-2.41** | -0.91 | -260 |
| S2 @ 5 | 170,542 | -1.28 | -0.17 | -2.65 | -1.15 | -663 |
| S3 @ 3 (Dec 10-31) | 61,788 | -0.99 | -0.24 | **-2.39** | -0.89 | -276 |
| S3 @ 5 | 152,534 | -1.28 | -0.13 | -2.60 | -1.10 | -630 |
| shifted @ 1 | 26,263 | -2.21 | -0.17 | -3.72 | -2.22 | -130 |
| shifted @ 2 | 100,524 | -2.02 | -0.08 | -3.38 | -1.88 | -476 |
| shifted @ 3 | 173,864 | -1.88 | -0.16 | -3.29 | -1.79 | -804 |

At 0.5 and 1 bps the models fill only 300 to 1,300 times in the month, so their per-dollar numbers
are dominated by inventory noise (-3 to -16 bps). They are in the JSON.

- **At the same volume, the model's quotes lose less per dollar.** Shifting the series leaves
  the pulls in quiet hours, so at the same limit the placebo trades far more. The fair comparison
  is at matched volume.
  - S2 @ 5 against the placebo @ 3: 170,542 and 173,864 fills (2% apart). S2's daily total
    is better by +0.54 bps per filled dollar [+0.42, +0.67], on 22 of 24 days (DM p 2e-7).
    Its adverse selection is better by +0.52, on 24 of 24 days.
  - S3 @ 5 against the placebo @ 3 on S3's days: 152,534 and 153,226 fills. S3 is better by
    +0.56 [+0.43, +0.70], on 20 of 22 days.
  - So the quote-time models carry information about when to pull. The 2 bps result
    ("they lose less mainly by trading less") was the extreme end of the frontier, where the
    inventory term swamps the gain.
- **Against S1 per filled dollar,** S2 @ 3 is better by +0.68 [+0.32, +1.03] (19 of 24 days),
  S3 @ 3 by +0.66 [+0.24, +1.07], and S2 @ 5 by +0.45 [+0.33, +0.57] at 77% of S1's volume.
- **Still nothing makes money.** The best point, -2.39 bps all in, is -0.89 before the 1.5 bp
  maker fee.
  - Every maker from the 2 bps limit up has a daily PnL interval below zero.
  - At 0.5 and 1 bps the models barely trade (-3 to -46 USD a day). Their intervals include zero.
  - At this fee and latency a touch quoter on SOL needs about 0.9 bps more per filled dollar
    than the best model gives.
  - At a 0 bp maker fee (high volume tiers) the best points would still lose about 0.9 bps.

## ETH December (`eval/sim_eth.json`, `eval/quote_signals_eth.json`)

The SOL pipeline unchanged (`scripts/run_eth_sim.ps1`): the month rebuilt with `--mbo`, S2 and S3
trained on ETH Gold, the same engine, costs and 2 bps limit.
- S2 runs from Dec 8 (24 days), S3 from Dec 10 (22 days). The train/serve check against Gold
  passed on all 24 days.
- **Quote-time skill** (pinball skill against climatology on the Gold fills each model did not
  train on, q10 / q50 / q90):
  - S2: 0.321 / 0.309 / 0.328 (4.84M fills).
  - S3: 0.332 / 0.306 / 0.321 (4.16M fills).
- **Rows pulled at 2 bps** (mean over days): S2 47% (bid) and 45% (ask); S3 37% and 33%. SOL's
  were 42% and 34% on the bid.

On the days S3 has (Dec 10-31, 22 days), `fifo`, bps per filled dollar:

| Maker | Fills | Spread | Adverse 1 s | Inventory | Total | Before fee | USD a day |
|---|---:|---:|---:|---:|---:|---:|---:|
| S1 | 314,835 | +0.06 | -1.67 | -0.22 | -3.33 | -1.83 | -1,772 |
| stale | 275,725 | +0.07 | -1.52 | -0.16 | -3.11 | -1.61 | -1,441 |
| S2 | 14,515 | +0.16 | -0.85 | +0.01 | -2.21 | -0.71 | -84 |
| S3 | 29,950 | +0.15 | -0.79 | -0.37 | -2.53 | -1.03 | -168 |

Daily PnL differences (challenger minus base, USD), stationary-bootstrap 95% interval:

| Pair | `fifo` | Days better | `risk_averse` | Days better |
|---|---|---:|---|---:|
| stale - S1 (31 days) | +388 [281, 488] | 31/31 | +334 [240, 423] | 31/31 |
| S2 - S1 (24 days) | +1,828 [1,289, 2,409] | 24/24 | +1,606 [1,113, 2,144] | 24/24 |
| S3 - S1 (22 days) | +1,604 [1,111, 2,139] | 22/22 | +1,405 [958, 1,890] | 22/22 |
| **S3 - S2 (22 days)** | **-84 [-146, -11], DM p 0.021** | 4/22 | **-70 [-134, +4], DM p 0.066** | 4/22 |
| S2 - stale (24 days) | +1,480 [1,046, 1,951] | 24/24 | +1,305 [906, 1,738] | 24/24 |

- **No strategy makes money on ETH either.** Every maker's daily PnL interval is below zero.
  - S2 comes closest: -0.71 bps per filled dollar before the fee on Dec 10-31, and -0.30 over
    its 24 days.
  - Unlike on SOL, its inventory term is flat (+0.01), so the halved adverse selection
    survives.
- **S3 is worse than S2 on ETH, not level as on SOL.** It loses $84 a day more, on 18 of 22
  days.
  - S3 trades twice S2's volume and does worse per dollar (-2.53 against -2.21), mostly
    through inventory.
  - The race and forced-flow columns lose money at quote time here. This matches the ladder: H3
    null in both coins, H4 not replicated on ETH.
- **The models' gain over S1 replicates:** +$1.4k-1.8k a day on every day, under both queue
  models.

## Run

```
python -m marketimmune.cli.build_albers_silver --coin SOL --dates 20251201..20251231 --mbo
python -m marketimmune.cli.simulate_quotes --coin SOL --dates 20251201..20251231 --out eval/sim_sol.json
```

With S2 and S3:

```
python -m marketimmune.cli.quote_signals --coin SOL --dates 20251201..20251231 --report eval/quote_signals_sol.json
python -m marketimmune.cli.simulate_quotes --coin SOL --dates 20251201..20251231 --signals-dir data/gold/hyperliquid/quote_signals --out eval/sim_sol.json
```

Frontier (needs the quote signals; days cached, `--max-days` per call):

```
python -m marketimmune.cli.pull_frontier --coin SOL --dates 20251208..20251231 --out eval/sim_frontier_sol.json
python -m marketimmune.cli.pull_frontier --coin ETH --dates 20251208..20251231 --workers 2 --out eval/sim_frontier_eth.json
```

Some ETH days need more than 4 GB, more than the VM has.

ETH, the same three steps (`eval/quote_signals_eth.json`, `eval/sim_eth.json`):

```
powershell -ExecutionPolicy Bypass -File .\scripts\run_eth_sim.ps1
```

`--score-dates 20251215` scores one day with the full run's folds and seeds (resume, or a day per
call).

hftbacktest 2.4.4 needs numpy < 2.3 and the main environment has 2.4, so the baseline gets its
own venv:

```
python -m venv .venv-sim
.venv-sim/Scripts/python -m pip install -e .[sim]
.venv-sim/Scripts/python -m marketimmune.cli.hft_baseline --coin SOL --dates 20251201..20251231 --out eval/sim_hft_sol.json
```

Speed: one SOL day takes about 13 s for four makers (2 vCPU VM); the hftbacktest comparison takes 23 s.
