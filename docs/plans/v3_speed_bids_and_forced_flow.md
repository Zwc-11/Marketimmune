# MarketImmune v3: Speed Bids and Forced Flow

Oct 30, 2026 · @Caesar

A 13-week plan, Nov 2, 2026 to Jan 31, 2027, to add two inputs no toxicity model has used to MarketImmune's detector: takers' public priority fees, and a forecast of forced liquidation flow from Hyperliquid's public position book.

## Scope

MarketImmune keeps its job: predict which fills on Hyperliquid will hurt a market maker, and say what the maker should do. v3 adds two information sources to the detector and prices the result in a simulator. Nothing in v2's pipeline is thrown away; the parts around the model move to `legacy/`.

|  | v2 (today) | v3 (this plan) |
| --- | --- | --- |
| Question | Is this fill toxic? (10 s markout below −1 bp, SOL, 6 days) | What is the maker's markout on the next fill, per side, at 1/5/30 s, and how much of it comes from latency arbitrage vs forced liquidations vs informed flow? |
| Inputs | Top-of-book state, OFI, funding, open interest | v2 inputs, fixed, plus **A: speed bids** (priority fees takers paid in recent blocks) and **B: forced-flow forecast** (expected liquidation volume per side from the public position book) |
| Model | CatBoost classifier with isotonic calibration | LightGBM quantile regressions in a feature ladder; v2's model is rung L0 |
| Evidence | PR-AUC 0.556, Brier 0.233 on one holdout day | Out-of-sample gain over the CEX-gap control, Diebold–Mariano by day, and bps per filled dollar in a simulator |
| Data | SOL, May 27 – Jun 1, 2026 | BTC, ETH, SOL; Jul 2025 onward for B; from the priority-fee rollout (Apr 2026, per coin) for A |

### Fix v2 first

The audit of the current master found these. They are the first week's work, because every v3 number inherits them otherwise.

| ID | Fix | Where |
| --- | --- | --- |
| B1 | Write the real fee to Gold; `fee_bps` is currently always 0 | `lake/tables.py:197-214` |
| B2 | Dedupe the two legs of each match on `(block_time, coin, tid)`; keep both wallets | Silver fills |
| B3 | Replace the hard-coded `leakage_safe = True` with a test that recomputes features after deleting all future rows | `models/markout_evaluation.py:69` |
| B4 | Fit the calibrator on a held-out tail of the final training window, or drop isotonic | `train_hyperliquid_markout.py:385-396` |
| B5 | True rolling walk-forward by day; the current "walk-forward" is purged K-fold and trains on the future | `models/walk_forward.py:35-45` |
| B6 | Retire the Judge's promotion rule; significance comes from the statistics section | `models/promotion.py`, `agentic/judge.py` |
| L1 | Strict `<` in the as-of join so the snapshot in the fill's own millisecond is excluded | `features/hyperliquid_features.py:208` |
| L2 | Label from the mid just before the fill; drop `fill_vs_mid_bps` from pre-trade features | Labels, features |
| L3 | Promote `user` from Bronze `raw_json` to Silver as `maker_user`, `taker_user` | `hyperliquid_lake.py:131` |
| L4 | Keep five book levels in Silver, not just the top | Silver L2 |

### Why these two inputs

- **A exists only on Hyperliquid, since April 2026.** Takers pay on-chain for earlier arrival, and the fee is recorded on each fill (`priorityGas`) and on each order action. A taker pays for 45 ms only when it believes a resting quote is stale. Markouts already rise from 1.8 to 17.5 bps across fee bands in raw data ([0xArchive](https://0xarchive.io/resources/research/hyperliquid-priority-fees-internalizing-hft-revenue)). No toxicity model uses it.
- **B exists only where positions are public.** Every wallet's size, leverage and liquidation price are queryable; the liquidation engine is deterministic and documented; the mark price lags Binance by up to 3 s. Stops and liquidations are about 35% of volume in fast moves vs 6% normally ([hl-l4-interim](https://danielj86.github.io/hl-l4-interim/)). Heatmaps exist; a forecast fed to a maker does not.

## Architecture

&#91;embedded content: MarketImmune v3 pipeline · 4 sources, 2 new inputs, 1 detector\]

The left two columns are v2 after the fixes. The right two columns are new: the action log and the position book feed the two new inputs, which enter the ladder as extra columns. The decomposition and the simulator consume the ladder's predictions.

## Workstream A: speed bids as a toxicity signal

**Claim to test.** The priority fees takers paid in the last few blocks predict the maker's markout on the next fill, beyond what the Binance–Hyperliquid price gap already predicts.

### A.1 The mechanism in one paragraph

Hyperliquid matches in blocks of about 70 ms. Inside each consensus batch, post-only orders run first, then cancels, then taker orders ([order book](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/order-book.md)). Since April 2026 a taker can pay a priority fee p (0–8 bps of notional, burned) that moves its effective arrival earlier by about 45 ms per bp; above 8 bps the fee only breaks ties inside a 70 ms bucket ([priority fees](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/priority-fees.md)). A fee can never beat a cancel in the same batch, so it buys only a chance to land one batch earlier. A taker pays that when it is racing a maker's cancel for a quote that has gone stale, which happens after a Binance move, because Binance leads Hyperliquid by 600–800 ms. So fees paid in blocks b−k to b−1 announce that quotes on that side are stale at block b.

### A.2 Data

| Need | Source | Fields | Phase |
| --- | --- | --- | --- |
| Fees on executed taker orders | `node_fills_by_block` (already in v2's ingest) | `priorityGas`, `crossed`, `user`, `block_number`, `block_time` | A1 |
| Fees on taker orders that did **not** fill (missed the race) | `replica_cmds` action log; `grouping: {p}` on order actions, `nonce` per action | Order actions with `p > 0`, their block | A2 |
| Post-only priority (queue jumps) | Raw book diffs `insertBefore`, or `replica_cmds` ALO actions with `p > 0` | Which quotes bought queue position | A2 |
| Reference price | Binance USD-M `aggTrades` (history); your recorder's `bookTicker` (forward) | ms timestamps | A1 |
| Rollout date per coin | Measured: first day `priorityGas > 0` appears per coin | — | A1 |

A1 uses only data v2 already downloads, so the first result is cheap. A2 adds the action log, processed next to its bucket in ap-northeast-1 (see the build plan, Lesson 3.1).

### A.3 Features

For coin c, side j (the side a taker would hit), block b and window k blocks:

```latex
\mathrm{FP}^{j}_{b}(k) = \frac{\sum_{i \in \mathcal{T}^{j}_{b-k:b-1}} p_i N_i}{\sum_{i \in \mathcal{T}^{j}_{b-k:b-1}} N_i}
\qquad
\mathrm{FC}^{j}_{b}(k) = \#\{i \in \mathcal{T}^{j}_{b-k:b-1} : p_i > 0\}
\qquad
\mathrm{FM}^{j}_{b}(k) = \max_{i \in \mathcal{T}^{j}_{b-k:b-1}} p_i
```

𝒯 is the set of taker orders (A1: fills with `crossed = true`; A2: all IOC/GTC actions), pᵢ the fee in bps, Nᵢ the notional. Use k ∈ {3, 10, 30} blocks (about 0.2, 0.7, 2 s). Add:

- **Fee-weighted imbalance:** FP on the ask side minus FP on the bid side.
- **Priced-taker share:** fee-paying notional over all taker notional in the window.
- **Missed-race count (A2 only):** fee-paying IOC orders that did not execute. These are the most informative, because they mean a cancel won.

Every feature is lagged one block: a maker deciding at block b sees fees committed through b−1 only.

**The control that decides the result.** The direct staleness measure is

```latex
g_b = r^{\text{Binance}}_{t_b - \Delta} - r^{\text{HL}}_{t_b}
```

the Binance return since the last Hyperliquid mid change, with Δ your own feed latency so you never use a Binance print the maker could not have seen. If fee pressure only proxies g\_b, it adds nothing. Every rung of the ladder in the Integration section includes g\_b.

### A.4 Economic reading

A taker's fee f is rational only if its expected pick-off gain covers it:

```latex
\mathbb{E}[\,|J| - \delta \mid \text{pays } f\,] \;\ge\; f + \tau_T
```

where |J| is the move, δ the quote's half-spread and τ\_T the taker fee. So the fee distribution in the current window is a lower bound on how mispriced resting quotes are, posted by the traders best placed to know. This is what the model should recover: markout conditional on FP should be at least as negative as the fees imply.

### A.5 Tests specific to A

1. **Rollout check.** Per coin, the first date with `priorityGas > 0`. Features are undefined before it; the model must not see them earlier.
2. **Raw separation.** Maker markout by fee band of the taker (0, 0–2, 2–4, 4–8, 8+ bps), per coin, with day-level bootstrap intervals. This should reproduce the 0xArchive pattern before any model is fit.
3. **Incremental value.** Ladder rung L3 vs L2 (Integration section), split into windows within 1 s of a Binance move and quiet windows.
4. **Lead time.** Markout at 1 s as a function of how many blocks before the fill the first fee-paying taker appeared. This shows how long the warning lasts.
5. **Placebo.** The same features computed from fees on the *opposite* side should carry no information for this side's markout.

### A.6 Code

```python
import polars as pl

K = (3, 10, 30)

fills = pl.scan_parquet("data/silver/fills/coin=BTC/*.parquet")   # deduped, one row per match

# taker side = side that crossed; the maker was hit on the opposite side
takers = (fills.filter(pl.col("crossed"))
          .with_columns(hit_side=pl.when(pl.col("taker_is_buy")).then(pl.lit("A")).otherwise(pl.lit("B")),
                        prio_bps=pl.col("priorityGas").fill_null(0) / 1e4,
                        notional=pl.col("px") * pl.col("sz")))

per_block = (takers.group_by(["block_number", "hit_side"])
             .agg(fee_notional=(pl.col("prio_bps") * pl.col("notional")).sum(),
                  notional=pl.col("notional").sum(),
                  n_fee=(pl.col("prio_bps") > 0).sum(),
                  max_fee=pl.col("prio_bps").max()))

# dense block x side grid so windows count blocks, not rows
blocks = fills.select("block_number").unique()
grid = blocks.join(pl.LazyFrame({"hit_side": ["A", "B"]}), how="cross")

feat = grid.join(per_block, on=["block_number", "hit_side"], how="left").fill_null(0).sort("block_number")
for k in K:
    feat = feat.with_columns(
        (pl.col("fee_notional").rolling_sum(k) / pl.col("notional").rolling_sum(k).clip(lower_bound=1e-9))
            .over("hit_side").alias(f"fp_{k}"),
        pl.col("n_fee").rolling_sum(k).over("hit_side").alias(f"fc_{k}"),
        pl.col("max_fee").rolling_max(k).over("hit_side").alias(f"fm_{k}"))

# lag one block: at block b the maker sees fees through b-1
lagged = [c for c in feat.collect_schema().names() if c.startswith(("fp_", "fc_", "fm_"))]
feat = feat.with_columns(pl.col(lagged).shift(1).over("hit_side"))
```

## Workstream B: the forced-flow forecaster

**Claim to test.** The expected volume of forced liquidation orders per side over the next 5–60 s, computed from the public position book and the current Binance price, predicts maker markouts beyond volatility and open interest, and does so before the orders arrive.

### B.1 Why the flow is forecastable

Three published rules make forced flow a function of public state ([liquidations](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations), [contract specs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications), [robust price indices](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/robust-price-indices)):

1. **The trigger is public.** A position is liquidated when account equity falls below maintenance margin, which is half the initial margin at the asset's maximum leverage (1.25% at 40x, up to 16.7% at 3x). The liquidation price for a position of signed size s (positive long) entered at price p₀, with margin available M and maintenance leverage ℓ = 1/maintenance-margin-fraction, is

```latex
L = p_0 - \operatorname{sign}(s)\,\frac{M}{|s|}\,\frac{1}{1 - \operatorname{sign}(s)/\ell}
```

The API returns it directly as `liquidationPx` for any address, so the formula is for rolling positions forward between queries, not for guessing.

2. **The execution is mechanical.** At the trigger the engine sends market orders for the whole position to the book. Positions above 100k USDC go in 20% slices with a 30 s cooldown. If equity falls below two-thirds of maintenance margin and the book has not absorbed it, the backstop vault takes the position off-book. Fills carry `liquidation: {liquidatedUser, markPx, method: market | backstop}`.
3. **The clock is slow.** Liquidations use the mark price, which updates with the oracle about every 3 s. Binance leads Hyperliquid by 600–800 ms. So when Binance moves, the set of positions that will be triggered at the next mark update is known 1–3 s in advance.

### B.2 Data

| Need | Source | Fields | Notes |
| --- | --- | --- | --- |
| Positions of all wallets, historical | [Hydromancer Reservoir](https://docs.hydromancer.xyz/reservoir/schema-reference/snapshots) daily snapshots (requester pays, ap-northeast-1) | `user, coin, size, entry_px, liquidation_price, leverage, account_value` | From Jul 2025. Daily, so stale within the day |
| Position changes within a day | `node_fills_by_block` | `startPosition`, `sz`, `side`, `user` per fill | Every fill states the wallet's position before it; roll positions forward exactly for any wallet that trades |
| Margin changes | `misc_events_by_block` | Ledger updates (deposits, withdrawals, transfers), funding | Needed to keep `liquidationPx` correct between snapshots |
| Positions, live | `clearinghouseState` for one address; weight 2 of 1,200 per minute per IP | Positions with `liquidationPx`, `marginUsed`, `leverage` | About 600 addresses per minute. Refresh the top 2,000 wallets by notional every 4 min |
| Bulk state, optional | Node `periodic_abci_states` every 10,000 blocks (about 12 min) | Full state | If you run a node |
| Mark and oracle | `activeAssetCtx` (WS) / asset contexts (S3) | `markPx`, `oraclePx` | 3 s cadence |
| Realised forced flow (labels) | `node_fills_by_block` | Fills with `liquidation` set | Volume per side per block |
| Reference price | Binance `aggTrades`; recorder `bookTicker` |  | Leads the mark |

Glassnode found Hyperliquid's largest observed positions cover about 90% of liquidable open interest, so refreshing the top wallets captures most of the mass ([Glassnode](https://research.glassnode.com/liquidation-heatmaps/)).

### B.3 Position reconstruction

The state at any block is the last snapshot rolled forward:

1. Load the daily snapshot for the day.
2. Replay fills in block order; each fill gives `startPosition` and the signed change, so set the wallet's position to `startPosition + Δ` and recompute its liquidation price from entry, size, margin and the margin tier for that size. Reconcile against the fill's own `startPosition` on the wallet's next fill; a mismatch means a margin or transfer event was missed.
3. Apply ledger events from `misc_events_by_block` for margin changes.
4. Validate on a random sample of 500 wallets against the next day's snapshot; report the error distribution in liquidation price. The forecaster only needs positions within a few percent of the current mark, so error elsewhere does not matter.

### B.4 The forecast

For side j (the side forced orders will hit: longs liquidate into bids), horizon h, current mark m, and Binance-implied mark m̃ = m · (1 + g) using the gap g from A.3:

```latex
F_j(t, h) = \sum_{w \in W_j} \underbrace{\pi_w(t, h)}_{\text{P(trigger)}} \cdot \underbrace{|s_w|\, m}_{\text{notional}} \cdot \underbrace{\phi(|s_w| m)}_{\text{book fraction}}
```

- **Trigger probability.** The mark follows the Binance price with lag; model the h-ahead log-mark as a Brownian motion starting at ln m̃ with volatility σ̂ (EWMA of 1 s mark returns). A long is liquidated if the running minimum hits L\_w. By the reflection principle, with d\_w = ln(L\_w / m̃) < 0,

```latex
\pi_w(t, h) = 2\,\Phi\!\left(\frac{d_w}{\hat\sigma\sqrt{h}}\right), \qquad \pi_w = 1 \text{ if } L_w \ge \tilde m \text{ (already crossed; fires at the next mark update)}
```

The "already crossed" term is the part no heatmap has: positions the Binance move has doomed before the mark catches up.

- **Book fraction φ.** 1 for notional under 100k USDC; 0.2 for larger (first slice), with the rest spread over later 30 s windows. Positions deep enough that the backstop takes them contribute 0 to book flow; estimate that threshold from history (fills with `method = backstop`).
- **Cascade term.** Forced sells push the mark down and trigger more. Iterate once: add the expected impact of F\_j (using the coin's measured impact per unit notional) to m̃ and recompute. Report whether the second pass changes the forecast materially; Garcia Seuma finds cascades subcritical, so expect a small correction.

Targets: F\_j at h ∈ {5, 15, 60} s, plus the binary "forced flow above X USDC on side j within h". Compare to **four baselines**: zero, open-interest change, realised volatility, and the static heatmap mass within 1% of the mark (what dashboards show).

### B.5 Evaluation of the forecaster itself

| Metric | For | Against |
| --- | --- | --- |
| Pinball loss at τ = 0.5, 0.9 on realised forced notional per block window | F\_j | the four baselines |
| Brier score and reliability diagram for the binary target, decomposed into reliability and resolution | binary | baselines |
| Lead time: how many seconds before the first forced fill the forecast exceeded its threshold | binary | heatmap mass |
| Split by regime: quiet days vs top-5% volatility days vs the Oct 10, 2025 cascade (held out, reported separately) | all |  |

Daily block bootstrap for every interval. The claim should be about ordinary forced flow in fast moves; cascades are too rare to learn from and are reported as a stress test, not a result.

### B.6 Code

```python
import numpy as np
import polars as pl
from scipy.stats import norm

def forced_flow(pos: pl.DataFrame, mark: float, gap: float, sigma_1s: float, h_s: float) -> dict:
    """Expected forced notional hitting bids (long liquidations) and asks (short liquidations).
    pos: one row per wallet x coin with size (signed), liq_px, notional_usd."""
    m_tilde = mark * (1.0 + gap)                      # Binance-implied mark
    sig = sigma_1s * np.sqrt(h_s)
    longs = pos.filter(pl.col("size") > 0)
    shorts = pos.filter(pl.col("size") < 0)

    def prob(liq, is_long):
        d = np.log(liq / m_tilde)
        crossed = (d >= 0) if is_long else (d <= 0)
        p = 2.0 * norm.cdf(-np.abs(d) / sig)
        return np.where(crossed, 1.0, p)

    def frac(notional):
        return np.where(notional > 100_000, 0.2, 1.0)  # 20% slices above 100k USDC

    f_bid = float((prob(longs["liq_px"].to_numpy(), True) * longs["notional_usd"].to_numpy()
                   * frac(longs["notional_usd"].to_numpy())).sum())
    f_ask = float((prob(shorts["liq_px"].to_numpy(), False) * shorts["notional_usd"].to_numpy()
                   * frac(shorts["notional_usd"].to_numpy())).sum())
    return {"F_bid": f_bid, "F_ask": f_ask}
```

```python
# position roll-forward from fills (one coin, one day), after loading the daily snapshot into `state`
fills = (pl.read_parquet("data/silver/fills/coin=BTC/date=2026-03-10.parquet")
           .sort(["block_number", "tid"]))
for row in fills.iter_rows(named=True):
    for user_key, is_buy in (("maker_user", not row["taker_is_buy"]), ("taker_user", row["taker_is_buy"])):
        w = row[user_key]
        delta = row["sz"] if is_buy else -row["sz"]
        # fill records the wallet's position before this fill; reconcile, then update
        if w in state and abs(state[w]["size"] - row[f"{user_key}_start_position"]) > 1e-9:
            log_mismatch(w, row)                       # a margin/transfer event was missed
        state[w] = update_position(state.get(w), start=row[f"{user_key}_start_position"], delta=delta,
                                   px=row["px"], margin_tiers=TIERS["BTC"])
```

`update_position` recomputes entry price, size and liquidation price with the margin tier for the new size. Validate it against `clearinghouseState` for a sample of live wallets before trusting it on history.

## Integration: the ladder, the simulator, and success

Both workstreams end in the same place: new columns in the detector's feature table, and a quoting rule that uses them. The test is the increment each rung adds, not the absolute score.

### Target

The maker's markout on the next fill on side j, at 1, 5 and 30 s, in bps, scaled by σ̂ so coins pool (the build plan's Lesson 1 has the definition). Models are LightGBM quantile regressions at τ = 0.1, 0.5, 0.9, retrained daily on a rolling 30-day window, predicting the next day.

### The ladder

| Rung | Adds | Purpose |
| --- | --- | --- |
| L0 | v2's features, fixed: spread, microprice offset, 5-level OFI, volatility, funding, OI | The current MarketImmune, as the floor |
| L1 | CEX gap g\_b, lagged Binance returns, lagged BTC/ETH OFI for altcoins | The control everything must beat |
| L2 | Shrunk wallet toxicity scores of active takers | The published state of the art (Zhai 2026) |
| L3a | Speed-bid features (A) | Workstream A's result is L3a vs L2 |
| L3b | Forced-flow forecast F\_bid, F\_ask at 5/15/60 s and the binary trigger (B) | Workstream B's result is L3b vs L2 |
| L3 | Both | The v3 detector |

Report each increment with Diebold–Mariano on daily pinball loss, the Model Confidence Set over all rungs, and a split into three regimes: within 1 s of a Binance move, within 60 s of a forced fill, and quiet. The hypothesis is that A matters in the first regime, B in the second, and neither in the third.

### Decomposed reading

With A and B in the model, each fill's predicted markout splits into parts the maker treats differently:

- **Latency-arbitrage component**, carried by g\_b and the speed features. Response: cancel or widen for a few blocks.
- **Forced-flow component**, carried by F. Response: skew away from the side forced orders will hit, and quote to absorb at a better price once the slices arrive.
- **Residual**, informed flow. Response: wallet-level treatment from L2.

Report the share of predicted adverse selection attributed to each, by coin and regime. This is the number that distinguishes v3 from every toxicity paper that reports one score.

### The economic test

The simulator from the build plan (block-accurate replay with your quotes injected, hftbacktest as the continuous baseline) runs four strategies: S1 inventory-only quotes, S2 with L2 signals, S3a with speed features, S3b with the forced-flow forecast, S3 with both. Rules per side: widen by the predicted adverse move, pull when the 10th-percentile markout is below a limit, cancel at once when fee pressure spikes, skew away from forecast forced flow.

Output: bps per filled dollar and daily PnL split into spread capture, fees and rebates, adverse selection, inventory and hedging, each with stationary-bootstrap intervals over days. The headline is S3 minus S2.

### What counts as success

| Result | Meaning |
| --- | --- |
| L3a beats L2 in the CEX-move regime with a Diebold–Mariano t above 3, and the placebo (opposite-side fees) shows nothing | Speed bids carry information beyond the price gap |
| L3b beats L2 in the forced-fill regime, and the forecaster beats the static heatmap on pinball loss and lead time | The position book forecasts flow, not just maps it |
| S3 minus S2 is positive with an interval that excludes zero, under both queue models | The signals are worth money to a maker, not only statistically visible |
| Any of the above fails cleanly | Still a publishable result: a documented null on a dataset nobody has tested |

## Stack and repository

v3 extends the existing `Zwc-11/MarketImmune` repository. New modules sit beside v2's; the dashboard and agent loop move to `legacy/`. Rust enters only where volume demands it: decoding the action log and replaying blocks.

### Technologies and roles

| Layer | Technology | Role | New in v3? |
| --- | --- | --- | --- |
| Ingest | boto3 (requester pays), lz4 | S3 download; v2's Bronze/Silver/Gold layout | Kept |
|  | EC2 spot instance in ap-northeast-1 | Process `replica_cmds` and Hydromancer snapshots next to their buckets | New |
|  | hyperliquid-python-sdk 0.24 | `clearinghouseState` polling, asset metadata | Kept |
|  | websockets, asyncio, chrony | Recorder: Hyperliquid `l2Book`/`bbo`/`trades`/`activeAssetCtx`, Binance `bookTicker` | New |
| Transform | polars 2.1 (pinned), DuckDB, pyarrow | As-of joins, dedupe, features, position roll-forward | Kept |
| Replay | Rust: `hl-replay` crate (`lz4_flex`, `serde_json`, `rmp-serde`, `k256`, `arrow`, `parquet`, `pyo3`) | Action-log decoding, signer recovery, block-accurate book, injection for the simulator | New |
| Models | LightGBM | Quantile ladder L0–L3 | Replaces CatBoost as primary; CatBoost kept as L0 reference |
|  | SciPy | Forecaster probabilities | New |
| Evaluation | statsmodels, arch | Diebold–Mariano, Model Confidence Set, stationary bootstrap | New |
| Simulation | `hl-replay` match mode; hftbacktest 2.4.4 | Block-accurate and continuous baselines | New |
| Quality | ruff, mypy, pytest (coverage gate kept), cargo fmt/clippy/test, GitHub Actions |  | Kept, extended |
| Writing | Markdown results pages in `docs/`, one JSON per run in `results/` |  | Kept |

### Folder structure

```text
MarketImmune/
├── README.md                          # v3 thesis, headline numbers with CIs, how to reproduce
├── pyproject.toml                     # pinned; adds lightgbm, arch, scipy, hftbacktest
├── Cargo.toml                         # workspace for crates/
├── Makefile                           # make fix | ingest | positions | features | ladder | forecast | sim | report
├── .github/workflows/{python.yml, rust.yml}
├── configs/
│   ├── data.yaml                      # coins, date ranges, rollout dates per coin
│   ├── features.yaml                  # windows k, horizons h, thresholds
│   ├── forecast.yaml                  # sigma EWMA, slice rules, backstop threshold
│   └── sim.yaml                       # latency, queue model, fee tier
├── crates/
│   └── hl-replay/                     # see the build plan, Lesson 7
│       ├── src/{lib.rs, types.rs, engine.rs, inject.rs, episodes.rs}
│       ├── src/io/{replica_cmds.rs, fills.rs, l4.rs, parquet_out.rs}
│       ├── src/sig/{payload.rs, recover.rs}
│       ├── src/book/{mod.rs, level.rs}
│       ├── tests/{proptest_book.rs, golden_l2.rs, cross_mode.rs}
│       └── benches/replay.rs
├── marketimmune/
│   ├── ingest/                        # v2, with fixes B1, B2, L3, L4
│   │   ├── hyperliquid_fills.py       # + maker_user, taker_user, start_position, priorityGas, liquidation
│   │   ├── hyperliquid_lake.py        # + fee_bps written to Gold; 5 book levels
│   │   ├── hyperliquid_archive.py
│   │   ├── hyperliquid_asset_ctxs.py
│   │   ├── replica_cmds.py            # NEW: action log -> silver actions (prototype; Rust in prod)
│   │   ├── positions_snapshot.py      # NEW: Hydromancer daily snapshots
│   │   ├── misc_events.py             # NEW: ledger updates for margin
│   │   └── binance.py                 # NEW: aggTrades history; recorder bookTicker
│   ├── recorder/
│   │   ├── record.py                  # NEW
│   │   └── systemd/recorder.service
│   ├── labels/
│   │   ├── markout.py                 # fix L2: pre-fill mid; multi-horizon; vol-scaled
│   │   └── leakage.py                 # fix B3: real no-lookahead test
│   ├── features/
│   │   ├── hyperliquid_features.py    # fix L1 (strict as-of); L0 features
│   │   ├── cex_gap.py                 # NEW: L1 control g_b with feed latency
│   │   ├── wallet_toxicity.py         # NEW: L2 shrunk scores
│   │   ├── speed.py                   # NEW: A features fp/fc/fm, imbalance, missed races
│   │   └── forced_flow_features.py    # NEW: B outputs as features
│   ├── forced/
│   │   ├── margin_tiers.py            # NEW: maintenance margin by asset and size
│   │   ├── positions.py               # NEW: snapshot + fill roll-forward + ledger
│   │   ├── forecaster.py              # NEW: F_j(t,h), trigger probabilities, slices, cascade pass
│   │   ├── live_refresh.py            # NEW: clearinghouseState polling of top wallets
│   │   └── evaluate.py                # NEW: pinball, Brier, lead time vs baselines
│   ├── models/
│   │   ├── walk_forward.py            # fix B5: rolling daily
│   │   ├── calibration.py             # fix B4
│   │   ├── ladder.py                  # NEW: L0-L3 LightGBM quantile models
│   │   ├── decomposition.py           # NEW: attribution to arb / forced / residual
│   │   └── markout_evaluation.py      # + DM, MCS, regime splits
│   ├── sim/
│   │   ├── quoting.py                 # NEW: widen / pull / cancel-on-signal / skew-on-forecast
│   │   ├── sim_block.py               # NEW: drives hl-replay match mode
│   │   ├── sim_hftbt.py               # NEW: continuous baseline
│   │   └── pnl.py                     # NEW: attribution
│   └── stats/
│       ├── bootstrap.py               # NEW
│       └── dm.py                      # NEW
├── scripts/
│   ├── 00_fix_and_rebuild_gold.py     # applies B1-B6, L1-L4; regenerates v2's benchmark for comparison
│   ├── 01_rollout_dates.py            # first priorityGas>0 per coin
│   ├── 02_speed_features.py
│   ├── 03_positions.py
│   ├── 04_forecast.py
│   ├── 05_ladder.py
│   ├── 06_sim.py
│   └── 07_report.py
├── tests/                             # existing + no_lookahead, dedupe, speed, positions, forecaster, stats
├── docs/
│   ├── benchmarks/                    # v2 JSON kept; v3 JSONs added
│   ├── preregistration.md
│   └── results/{speed.md, forced_flow.md, ladder.md, simulation.md}
├── results/                           # one JSON per run
├── legacy/
│   ├── agentic/                       # v2 immune loop, Judge
│   ├── dashboard/                     # Django + React
│   └── risk_head/                     # v1 synthetic model
└── data/                              # gitignored
```

## Schedule

Thirteen weeks. The first result (speed bids from data v2 already has) lands on Nov 29, inside the co-op term, because it needs no new infrastructure. The heavier phases start after the term ends.

&#91;embedded content: Schedule · 6 phases, 13 weeks\]

A1 comes before B because it reuses v2's fills and gives an early read on whether the whole approach is worth continuing. A2 (the action log) is deferred to January because it needs the Tokyo processing setup and the Rust extractor; if A1 shows nothing after the CEX-gap control, A2 can be dropped and the time given to B.

## Task list

### Phase 0: Fix v2 and open the data (Nov 2–15)

- [ ] Apply B1–B6 and L1–L4; rerun v2's SOL benchmark on the fixed pipeline and commit the new JSON beside the old one, so the before/after is on record.
- [ ] Move `agentic/`, the dashboard and the v1 risk head to `legacy/`; keep their tests passing or mark them skipped.
- [ ] Add `maker_user`, `taker_user`, `start_position`, `priorityGas` and `liquidation` to Silver fills; dedupe on `(block_time, coin, tid)`.
- [ ] Download `node_fills_by_block` for BTC, ETH, SOL from 2026-03-01 to the latest day; run `01_rollout_dates.py` to find the first `priorityGas > 0` per coin.
- [ ] Download Binance `aggTrades` for the same range; build the CEX-gap feature g\_b with a conservative feed latency Δ = 300 ms.
- [ ] Start the recorder on a VPS.
- [ ] Read Hyperliquid's terms of use on API access from Ontario; write the conclusion into `docs/`.

**Gate G0:** fixed v2 benchmark committed; rollout date per coin known; g\_b computed and passing the no-lookahead test.

### Phase A1: Speed bids from fills (Nov 16–29)

- [ ] `features/speed.py`: FP, FC, FM for k = 3, 10, 30; imbalance; priced-taker share; one-block lag; unit tests on a hand-built block sequence.
- [ ] Raw separation table: maker markout by taker fee band, per coin, with day-level bootstrap CIs.
- [ ] Multi-horizon labels (1, 5, 30 s) from the pre-fill mid; vol-scaled targets.
- [ ] Ladder L0, L1, L2, L3a with rolling walk-forward; Diebold–Mariano L3a vs L2, split by regime; placebo with opposite-side fees.
- [ ] Write `docs/results/speed.md`.

**Gate A1:** L3a vs L2 reported with CIs in both regimes. If the CEX-move-regime gain is not positive, A2 is cancelled and its weeks go to B.

### Phase B1: Position reconstruction (Nov 30 – Dec 20)

- [ ] Pull Hydromancer daily position snapshots for BTC, ETH, SOL, 2025-09-01 onward (in ap-northeast-1).
- [ ] `forced/margin_tiers.py` from the contract specs; `forced/positions.py` roll-forward from fills (`startPosition`) and ledger events.
- [ ] Validate: roll one day forward and compare with the next snapshot for 500 random wallets; report the liquidation-price error distribution. Separately, compare live `clearinghouseState` for 200 wallets against your rolled state.
- [ ] `forced/live_refresh.py`: poll the top 2,000 wallets by notional within the 1,200-weight/min budget.

**Gate B1:** median liquidation-price error under 0.1% for wallets within 5% of the mark; mismatches logged and explained.

### Phase B2: Forecaster and evaluation (Dec 21 – Jan 3)

- [ ] `forced/forecaster.py`: trigger probabilities with the Binance-implied mark, slice rule, backstop threshold estimated from history, one cascade pass.
- [ ] Realised forced-flow labels per side per block window from `liquidation` fills.
- [ ] Evaluation vs four baselines (zero, OI change, volatility, static heatmap mass): pinball, Brier with decomposition, lead time; regime split; Oct 10, 2025 as a held-out stress case.
- [ ] `features/forced_flow_features.py`: F at 5/15/60 s and the binary trigger as ladder columns.
- [ ] Write `docs/results/forced_flow.md`.

**Gate B2:** forecaster beats the static heatmap on pinball loss and lead time with CIs; L3b vs L2 reported.

### Phase A2: Action log and missed races (Jan 4–17)

- [ ] Rust extractor for `replica_cmds` (fee `p`, nonce, order and cancel actions) for BTC, ETH, SOL over the A1 window, processed in Tokyo.
- [ ] Missed-race count: fee-paying IOC orders with no matching fill in the same block.
- [ ] Post-only priority: ALO orders with `p > 0` and `insertBefore` book diffs where available.
- [ ] Re-run the A ladder with the extended features.

**Gate A2:** the missed-race feature's incremental value over A1's fill-only features is reported.

### Integration (Jan 18–30)

- [ ] Full ladder L0–L3; Model Confidence Set; decomposition into latency-arb, forced and residual shares by coin and regime.
- [ ] Quoting rules in `sim/quoting.py`; S1–S3 in the block-accurate simulator and in hftbacktest; PnL attribution with stationary-bootstrap CIs.
- [ ] Pre-registration committed before the final held-out month (January 2027) is scored; score it once.
- [ ] README with headline numbers and CIs; `docs/results/ladder.md` and `simulation.md`; one JSON per run in `results/`.
- [ ] Publish on Jan 31.

## Risks and open questions

| Risk | Effect | Mitigation | Check |
| --- | --- | --- | --- |
| Speed features only proxy the CEX gap | A shows no incremental value | g\_b is in every rung; the placebo and the lead-time test tell proxy from signal. A clean null is still publishable | Gate A1 |
| Short sample for A: core perps got fees after Apr 2026, at a date still to be measured | Few months of data, few cascade-free regimes | Pool BTC, ETH, SOL; report per coin; keep the recorder running to extend | Phase 0 |
| `priorityGas` only on executed orders in A1 | Misses the most informative cases (fees paid, race lost) | A2 adds the action log; A1 is a lower bound | Gate A2 |
| Daily position snapshots stale within the day | Wrong liquidation prices for active wallets | Roll forward from fills' `startPosition` and ledger events; validate against next-day snapshot and live state | Gate B1 |
| Margin changes invisible between snapshots | Liquidation price drifts | Ledger events from `misc_events_by_block`; accept error for wallets far from the mark | Gate B1 |
| Forced flow is rare outside fast moves | Forecaster scores well only on quiet days by predicting zero | Evaluate in the fast-move regime; use pinball at τ = 0.9 and lead time, not only mean error | Gate B2 |
| Backstop absorbs large liquidations off-book | Forecast overstates book flow | Estimate the backstop threshold from `method = backstop` fills; cap book fraction | Phase B2 |
| Cascades (Oct 10, 2025) dominate averages | One day drives conclusions | Held-out stress case, reported separately; day-level bootstrap | Throughout |
| Rate limits on `clearinghouseState` | Live refresh covers only top wallets | Top 2,000 by notional cover most liquidable OI; measure coverage against snapshots | Phase B1 |
| Processing `replica_cmds` outside Tokyo | Egress cost | EC2 spot in ap-northeast-1; one-day probe first | Phase A2 |
| Terms of use for Ontario | API access question | Read before Phase 0 ends; the plan places no live orders | Phase 0 |

### Open before starting

- Which window for A1: everything since each coin's rollout date, or a fixed 90 days? Recommendation: everything since rollout, with results also shown for the latest 60 days.
- Does Hydromancer's snapshot include `liquidation_price` as the exchange computed it, or must it be recomputed? Check one day's schema before writing `positions.py`.
- Run the live refresh now (cheap, and it builds a validation set for B1), or wait until Phase B1?

## Sources

**Hyperliquid mechanics and data**

- [Order book: within-batch processing order](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/order-book.md) · [Priority fees](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/priority-fees.md) · [Liquidations](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations) · [Contract specifications and margin tiers](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications) · [Robust price indices (mark price)](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/robust-price-indices) · [Oracle](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle) · [Info endpoint: `clearinghouseState`](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md) · [Rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) · [WebSocket subscriptions (fill fields)](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions.md) · [Historical data buckets](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data.md)
- [Dwellir fills schema](https://www.dwellir.com/docs/hyperliquid/data-catalog/node-feeds/fills.md) · [Dwellir replica\_cmds schema](https://www.dwellir.com/docs/hyperliquid/data-catalog/node-feeds/blocks.md) · [Hydromancer position snapshots](https://docs.hydromancer.xyz/reservoir/schema-reference/snapshots)
- Priority-fee rollout: [Odaily](https://www.odaily.news/en/newsflash/476501), [Blockworks Research](https://app.blockworksresearch.com/unlocked/hyper-liquid-priority-fees-internalizing-high-frequency-trading-revenue), [0xArchive markouts by fee band](https://0xarchive.io/resources/research/hyperliquid-priority-fees-internalizing-hft-revenue)

**Evidence behind the two inputs**

- [hl-l4-interim: block ordering, cancel rates, stops and liquidations share of fast-move volume](https://danielj86.github.io/hl-l4-interim/) · [Arrakis: Binance leads Hyperliquid by 600–800 ms](https://arrakis.finance/blog/crypto-price-discovery) · [Glassnode liquidation heatmaps](https://research.glassnode.com/liquidation-heatmaps/) · [Garcia Seuma, cascade engine](https://arxiv.org/html/2608.03616) · [Chitra, autodeleveraging](https://arxiv.org/abs/2512.01112)

**Baselines and methods**

- [Zhai, Public Trader Identity (L2 baseline)](https://arxiv.org/abs/2608.04373) · [Cont, Kukanov & Stoikov, OFI](https://arxiv.org/abs/1011.6402) · [Avellaneda & Stoikov](https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf) · [Cartea & Wang, alpha signals](https://ora.ox.ac.uk/objects/uuid:c2ba6656-8eab-4b2e-a24a-e9e842d1378f/files/s41687h481) · [Diebold–Mariano (statsmodels)](https://www.statsmodels.org/dev/generated/statsmodels.tsa.stattools.diebold_mariano_test.html) · [Hansen, Lunde & Nason, Model Confidence Set](https://repec.econ.au.dk/repec/creates/rp/10/rp10_76.pdf) · [Politis & Romano, stationary bootstrap](https://www.jstor.org/stable/2290993) · [hftbacktest](https://github.com/nkaz001/hftbacktest)

**The repository being extended**

- [Zwc-11/MarketImmune](https://github.com/Zwc-11/MarketImmune); the audit findings (B1–B6, L1–L4) are in the earlier MarketImmune v3 research plan.
