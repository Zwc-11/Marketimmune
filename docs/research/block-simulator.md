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
- **Post-only rejection is worth 0.55 to 0.62 bps per filled dollar to a touch quoter.** Without
  the L2 rule the engine trades less than half as much and loses less per dollar. That rule
  exists only in L4 data, because only L4 says which orders were post-only.
- **The queue model matters less than staleness.** Risk-averse and probabilistic queues give the
  same result in hftbacktest: most of S1's fills come from the price moving through quotes not
  yet updated.

On the same day the stale-quote rule improves S1 from -2.71 to -2.29 bps (`fifo`) and from -2.67
to -2.21 (`risk_averse`). Every maker loses money: even before the fee, S1 is -1.21 bps at the
touch.

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
  trade volume against adverse selection. A frontier over limits is the next comparison, if
  wanted, but no limit was chosen from these results.

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
