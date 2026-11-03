# Pre-registration: January 2027 confirmation (BTC, ETH, SOL)

Written 2026-11-03, before any January 2027 data exists. Drafted by Claude at Caesar's request.
The commit time is the registration time. `scripts/run_jan2027.ps1` refuses to start
until this file is committed and unchanged. Any later change goes in **Deviations** with its date
and reason.

**The question.** The Binance-Hyperliquid price gap and the taker's wallet score have held in every
test so far: December 2025 on the rebuilt book, and Sep-Oct 2026 on node fills (A1, A3 and A4).
Do they still predict the maker's 10 s markout on a month nobody has seen? And does the one trace
priority fees left in A1, at the 1 s horizon, hold when it is tested on its own?

**Why January 2027.** It is the first full month after this registration, so every tested row is
out of sample in time, not only out of fold. The whole month is confirmation; there is no
discovery period.

**Seen before registration (disclosed):**

- **Every December 2025 result:** the SOL and ETH ladders, the block simulator, the pull-limit
  frontier, the back-off run and the fee-tier table (`docs/research/block-simulator.md`).
- **All of A1** (`docs/research/a1-results.md`): Apr 25 to Oct 31, 2026, discovery and
  confirmation, the 1 s, 10 s and 60 s horizons, the secondary losses and the lead-time curve.
- **The 1 s fee trace that J3 tests.** At 1 s, `l3_fee` beat `l2_trade` on Brier by +0.48 to
  +0.51 x1e-3 in all three coins (Holm p 0.00075 to 0.0072), about 2% of the CEX gap's
  improvement at that horizon. It held in no coin under A1's rules: BTC's placebo had p 0.098
  (the rule needs p > 0.10), and pinball improved only in BTC. **J3's design (1 s, Brier only)
  was chosen after seeing this.** That is why it gets a fresh month instead of a claim on the old
  one.
- **Not seen:** anything from a date after 2026-10-31.

## Data

As in A1 (`docs/preregistration/a1-speed-bids-2026.md`, Data), with these dates:

| Item | Value |
| --- | --- |
| Markets | Hyperliquid BTC, ETH and SOL perpetuals, each tested on its own |
| Gold | 2026-11-01 to 2027-01-31, built by `build_node_gold` unchanged. The wallet scores' history starts on 2026-11-01: two months before the first tested day (A1's confirmation days had four to six) |
| Fills | `node_fills_by_block` (`pull_node_fills`), one row per match, maker's side |
| Book | None (no L4 archive for 2027). The state rung is built from trades only |
| Mid | The trade-implied mid, in execution order (`priority.fees.trade_mids`) |
| Reference | Binance USD-M BTCUSDT, ETHUSDT and SOLUSDT aggTrades, feed latency 300 ms |
| Fee | `priorityGas` x HYPE/USD (hourly `info` candles) / notional, in bps |
| Label | Maker markout from the last trade-implied mid strictly before the fill's block. **10 s** for J1, J2 and J4; **1 s** for J3. `toxic = markout < -1 bp` |
| Exclusions | A date with no Binance file, or whose `.leakage.json` has `passed = false`, is excluded from every rung and horizon, passed to `run_jan2027.ps1 -Exclude`, and reported |

If the S3 node-fill format or the fee fields change before the pull, the change and how the
builder handles it go in **Deviations** before any model is trained.

## Rungs

Unchanged from A1: `l0_trade`, `l1_trade`, `l2_trade`, `l3_fee`, `l3_fee_placebo` (definitions in
the A1 registration, Rungs). Fee windows count blocks by block number.

## Tested days

- Every date from 2027-01-01 to 2027-01-31, minus exclusions: at most 31 days.
- Each tested day is scored by models trained on the 7 days before it, one panel per day
  (`a1_ladder`), at 10 s and at 1 s, classifier and quantile.
- Seeds: 42 plus the day's place in the tested list.

## Fixed settings

A1's, unchanged:

- **Validation:** rolling daily walk-forward, 7-day training window, 60 s purge.
- **CatBoost:** 150 iterations, depth 6, learning rate 0.08, seed 42, calibration 0.2.
- **LightGBM quantile:** tau 0.1/0.5/0.9, 300 trees, learning rate 0.05, 31 leaves, min child
  200, seed 42.
- **Tests:** daily mean loss; Diebold-Mariano with Newey-West lag 2 and the HLN factor;
  stationary bootstrap, mean block 3 days, 5,000 draws, seed 0; MCS alpha 0.10.
- **Regimes:** `cex_move` when |Binance 1 s return| >= 2 bps; `quiet` for the rest.
- **Scoring:** `score_a1`, unchanged, run once per horizon on that horizon's comparisons. Per
  metric (Brier; pinball at tau 0.1), a test is supported for a coin with the stated sign, a DM
  p < 0.05 after Holm across the 12 tests of that horizon (A1-A4 x 3 coins), and a bootstrap 95%
  interval that excludes zero. A1 and A2 also need the placebo (`l3_fee_placebo` vs `l2_trade`)
  at raw p > 0.10 in every regime.

## Hypotheses and decision rules

| ID | Role | Horizon | Test (`score_a1` name) | Supported for a coin if |
| --- | --- | --- | --- | --- |
| J1 | **Confirmatory** | 10 s | A3: `l1_trade` vs `l0_trade`, all fills | It holds on both Brier and pinball (`held.A3`) |
| J2 | **Confirmatory** | 10 s | A4: `l2_trade` vs `l1_trade`, all fills | It holds on both metrics (`held.A4`) |
| J3 | **Confirmatory** | 1 s | A2: `l3_fee` vs `l2_trade`, all fills, with the placebo condition | It is supported on Brier (`metrics.brier.<coin>.A2.supported`) |
| J4 | Replication of a null | 10 s | A1 and A2 | Reported with intervals; no claim |

**Claims:**

- **The CEX gap replicates on January 2027** if J1 is supported in at least two of the three
  coins.
- **The taker's wallet score replicates on January 2027** if J2 is supported in at least two
  coins.
- **Priority fees carry a 1 s signal beyond the gap and the wallet score** if J3 is supported in
  at least two coins and its Brier point estimate is not negative in the third. If not, A1's
  conclusion (fees add nothing once the gap and the wallet score are known) is extended to 1 s.
- **J4:** if `score_a1`'s fee claim or gate holds at 10 s, it is reported as a contradiction of
  A1 and nothing more.

A hypothesis that is not supported is reported as a null with its interval.

Secondary, reported without claims: J3 on pinball at tau 0.1; the 1 s results of A1, A3 and A4;
the model confidence sets at each horizon; log loss.

## What will not be done

- No change to features, windows, thresholds, regimes, settings or rules after any January 2027
  result is seen.
- No dropping of days, coins, rungs or horizons because of their results.
- No economic claim. There is no L4 book for 2027, so the block simulator cannot run; its
  results stay December 2025 results.
- No other horizon, coin or month added to this registration.

## Run

The data is complete once 2027-01-31 is in the archives (from about 2027-02-02):

```
# EC2 in Tokyo (deploy/ec2_tokyo.md, section 5)
uv run python -m marketimmune.cli.pull_node_fills --dates 20261101..20270131 --out /data/node_fills
# locally, after copying the fills to data/bronze/node_fills
python -m marketimmune.cli.pull_candles --dates 20261101..20270131
python -m marketimmune.cli.download_binance aggtrades BTCUSDT 2026-11-01 2027-01-31   # and ETHUSDT, SOLUSDT
powershell -ExecutionPolicy Bypass -File .\scripts\run_jan2027.ps1                     # -Exclude 2027MMDD,... if needed
```

Verdicts: `eval/jan2027/h10s/verdicts.json` (J1, J2, J4) and `eval/jan2027/h1s/verdicts.json` (J3).

## Deviations

(none)
