# Pre-registration: five market-making candidates (2026-11-07, evening)

Written 2026-11-07 about 19:30 UTC, before any candidate below is run on its test hours. The
commit time is the registration time. Candidate 5's setting goes in an addendum, committed at the
end of its selection hour and before its test hour has been recorded. Drafted by Claude at
Caesar's request:
> "think about how can we improve the strategy, and really guess it, using Transformer to guess the
> possibility of the winning strategy ... I need the top 5 guessing winning strategy that could use
> our information to win this. ... We want market making strategy."

## Why these five

**What is already known** (`docs/research/paper-trading.md`):
- **Fee versus edge:** on our nine coins the maker fee (1.5 bp) is about three times the gap
  quoters' edge.
- **Spreads:** 0.1-1.8 bp.
- **Short-term trend:** prices trend within the minute, so touch fills are adversely selected.
- **Earlier candidates:** none of the earlier market-making candidates cleared the fee (the
  fill-toxicity quoter, a range swing maker, a Transformer fill model).

The five candidates here attack the fee from two directions:

1. **Catch only Hyperliquid's own moves.** Quote away from the Coinbase-implied fair price, so a
   fill happens when Hyperliquid alone moves. Coinbase leads Hyperliquid (IC 0.5 at 1 s), so those
   moves should come back.
2. **Go where the spread pays.** 40 Hyperliquid perps with at least $0.3M a day of volume have a
   spread of 3 bp or more, wider than two maker fees (scan of 2026-11-07 ~19:00 UTC).

## The candidates

The engine quoters are added to `paper/strategies.py`:
- **Fair price:** Hyperliquid's mid moved by the demeaned Coinbase gap.
- **Passive only:** a bid at most the best bid, an ask at least the best ask.
- **Risk layer and fills:** the shared risk layer, with the engine's latency, queue and fills.

1. **Lead-lag dislocation maker:** `disloc@d=3/x=1/tol=0.3/hold=120/stop=20`.
   - **Quotes:** a bid 3 bp under the fair price and an ask 3 bp over it.
   - **Exit:** with a position, it rests the exit 1 bp past fair; it leaves as a taker after 120 s
     or 20 bp against it.
2. **Lead-lag Avellaneda-Stoikov:** `lead@h0=2/skew=0.5/tol=0.3`.
   - **Quotes:** both sides 2 bp from a centre at the fair price.
   - **Inventory skew:** the centre moves 0.5 x 2 bp per quote of inventory against it.
3. **Sweep catcher:** `sweep@move=5/win=3/wait=5/hold=60/stop=20`.
   - **Trigger:** Hyperliquid moved 5 bp in 3 s and the gap to Coinbase opened by at least half of that.
   - **Quote:** it joins the touch on the side that profits if the move comes back, for 5 s.
   - **Exit:** at fair; a taker exit after 60 s or 20 bp against it.
4. **Transformer win-probability gate on `zgap@0.05`:** `paper/seqmodel.py`'s Transformer trained
   as a classifier (`cli/paper_gate.py`).
   - **Input:** the last 120 one-second bars of the coin and BTC.
   - **Output:** the probability that a fill's 30 s markout clears the 1.5 bp fee.
   - **Kept fills:** those with probability at least 0.6.
   - **Frozen model:** `marketimmune/paper/models/gate_zgap_30s.pt`.
5. **Long-tail spread maker:** `paper/tailmm.py`.
   - **Quotes:** join the best bid and ask ($200 each) of Hyperliquid perps whose spread is wide.
   - **Inventory:** a cap.
   - **Fills:** the engine's queue model (join behind the displayed size, trades eat the queue,
     cancels from behind, a trade through fills).
   - **Coins:** 24, fixed at 19:05 UTC from the scan (`data/paper/wide2/raw`, recorded from this
     workspace): LIT, AERO, INJ, CRV, DOT, TAO, WLFI, STRK, ZRO, GRAM, TIA, FARTCOIN, ASTER, JUP,
     ETHFI, MON, ICP, DASH, PUMP, kPEPE, CASHCAT, USELESS, SPX, CHIP.

## Selection (before this registration)

**Candidates 1-3:** `cli.paper_tune` with the causal clock; $250 x 4 quotes; $5,000 budget; 200 ms;
fees 1.5 / 4.5 bp.
- **Hours:** all 28.9 recorded hours to 2026-11-07 17:00 UTC (night, live, tuned and market-maker
  runs).
- **Output:** `eval/paper/tune_lead_selection_20261107.{json,md}`.
- **Grid:** 11 settings, `zgap@0.05` included.

Every candidate loses on the selection hours. Bps per filled $ from `cli.paper_report`:

| Family | Pick (within the rate limit) | $/h | Spread | Move in 1 s | Total bp |
|---|---|---:|---:|---:|---:|
| `zgap@0.05` (running live) | - | -3.5 | +0.23 | -0.36 | -0.77 |
| sweep | `move=5` | -3.9 | -0.21 | -0.86 | -3.32 |
| disloc | `d=3/x=1` | -4.5 | +0.87 | -1.13 | -2.79 |
| lead | `h0=2` | -4.8 | +1.15 | -1.45 | -2.25 |

- **Quoting further from fair earns more spread, but the move within a second grows as fast:**
  - `disloc@d=5`: spread +1.41, move -1.80.
  - `lead@h0=4`: spread +2.12, move -2.50.
  - Both are also over Hyperliquid's order-rate limit.
- **Reading:** even anchored to Coinbase, a fill far from the mid usually comes from a move
  Coinbase is making too, faster than a 200 ms quote update.

**Candidate 4:**
- **Data:**
  - trained on `zgap@0.05`'s 4,302 maker fills before 2026-11-07 04:09 (win rate after the fee 33%);
  - validated on its 2,339 fills from 04:09 to 17:00 (win rate 26%).
  - Output: `eval/paper/gate_zgap_train_20261107.json`.
- **Validation:** AUC 0.625. The kept fills improve from -1.49 to -0.99 bp after the fee at p = 0.6
  (143 kept), but no threshold keeps a profitable set: -$0.28 an hour [-0.53, -0.05] at p = 0.6.
- **Registered threshold:** 0.6, the best on validation.

**Candidate 5:**
- **Selection hour:** 2026-11-07 19:06-20:00 UTC, recorded live in this workspace.
- **Grid:** minimum spread 2, 3 or 4 bp; inventory cap 1 or 2 quotes; a flow filter of 0 or 10 s
  (12 settings).
- **Pick:** the most marked PnL per hour, in Addendum A.

**Each candidate is tested once, even where it lost in selection,** so the write-up can show them all.

## Test hours and primary criteria

**Candidates 1-4: 2026-11-07 17:00-20:00 UTC**, recorded by the market-maker run on Caesar's PC.
- **Never used:** no analysis has read these hours. The 15:20 segment's files to 17:00 were staged
  before; hour 17 was not.
- **Replay:**
  - the 15:20 segment's hour-17 files (17:00-17:20), then the 17:20 segment (17:20-20:00), as one chain;
  - with `zgap@0.05`;
  - the same settings as the selection.
- **Primary, candidates 1-3:** $ an hour > 0, with the stationary-bootstrap 95% interval
  (15-minute blocks, mean block 3, 5,000 draws, seed 0) above zero.
- **Reported regardless:** each candidate paired with `zgap@0.05`.
- **Primary, candidate 4:** the kept fills of `zgap@0.05` in that replay make money after the fee
  at $250 a fill. The interval must be above zero.

**Candidate 5: 2026-11-07 20:00-21:00 UTC**, recorded live in this workspace after Addendum A is
committed.
- **Primary:** the marked PnL is above zero, and the fills' 60 s markout after the fee is above
  zero with its bootstrap interval (5-minute blocks) above zero.
- **Reported regardless:**
  - the PnL with positions closed at the touch with the taker fee;
  - spread captured and markouts at 10 s and 60 s;
  - by coin.

**Power:**
- **Candidates 1-4:** three hours give wide intervals; a pass would still need a longer forward run.
- **Candidate 5:** one hour is a first look at a family this project has never recorded.

**Ranking rule** (as in `paper-five-candidates-20261107.md`), by the strength of the test evidence:
1. an interval above zero;
2. a positive point estimate;
3. negative.

Ties are broken by the interval's lower bound.
