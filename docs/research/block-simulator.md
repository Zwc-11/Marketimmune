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

## Run

```
python -m marketimmune.cli.build_albers_silver --coin SOL --dates 20251201..20251231 --mbo
python -m marketimmune.cli.simulate_quotes --coin SOL --dates 20251201..20251231 --out eval/sim_sol.json
```

hftbacktest 2.4.4 needs numpy < 2.3 and the main environment has 2.4, so the baseline gets its
own venv:

```
python -m venv .venv-sim
.venv-sim/Scripts/python -m pip install -e .[sim]
.venv-sim/Scripts/python -m marketimmune.cli.hft_baseline --coin SOL --dates 20251201..20251231 --out eval/sim_hft_sol.json
```

Speed: one SOL day takes about 13 s for four makers (2 vCPU VM); the hftbacktest comparison takes 23 s.
