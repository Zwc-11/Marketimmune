# Results: the ETH December 2025 feature ladder (confirmatory)

Rules: `docs/preregistration/eth-dec-2025-ladder.md`. ETH is the test of what SOL found:

- **Confirmatory:** H2 (on both primary metrics) and H4 on pinball (via the `forced_60s`
  route).
- **Replications:** H1 and H5.
- **Reported:** H3, a null on SOL.

One run, finished 2026-10-31 23:04 UTC, reports in `eval/eth_dec/`. Every rung's sidecar passed
the no-look-ahead check (`leakage_safe` on all 16 reports). The only deviation is the
data-quality gate's stop on 2025-12-15 (a 77-level sweep; see the pre-registration's
Deviations). The rules are unchanged.

Reproduce the verdicts:

    python -m marketimmune.cli.score_ladder --runs eval/eth_dec --name eth_dec --out eval/eth_dec/ladder_verdicts.json

## Verdicts

Each cell reads Brier / pinball at tau 0.1.

| H | Comparison | Role | Supported | Verdict |
|---|---|---|---|---|
| H1 | L1 vs L0, all fills | Replication | yes / yes | **Replicated** |
| H2 | L2 vs L1, all fills | Confirmatory | yes / yes | **Confirmed** |
| H3 | L3a vs L2, `cex_move`; placebo not significant | Null replication | no / no | Null replicated |
| H4 | L3b vs L2, `forced_60s` or all | Confirmatory (pinball) | no / no | **Not confirmed** |
| H5 | L0 and L1 outside the MCS (alpha 0.10) | Replication | yes / yes | **Replicated** |

Mean daily loss reduction, days improved, DM p (Holm), bootstrap 95% CI:

| H | Route | Brier | Pinball tau 0.1 |
|---|---|---|---|
| H1 | all | +0.0182, 24/24, p 1.8e-18 (7.4e-18), [0.0168, 0.0195] | +0.130, 24/24, p 1.1e-13 (4.3e-13), [0.115, 0.146] |
| H2 | all | +0.0168, 24/24, p 5.1e-6 (1.5e-5), [0.0115, 0.0229] | +0.067, 24/24, p 1.8e-8 (5.4e-8), [0.051, 0.084] |
| H3 | `cex_move` | +0.0007, 16/24, p 0.028 (0.057), [0.0002, 0.0012] | +0.0008, 11/24, p 0.62 (0.95), [-0.0023, 0.0040] |
| H4 | `forced_60s` | +0.0001, 10/21, p 0.95 | +0.0098, 14/21, p 0.24, [-0.0051, 0.0249] |
| H4 | all | +0.0004, 12/22, p 0.073, [0.0001, 0.0008] | -0.0006, 10/22, p 0.74 |

The Holm-adjusted p for H4 is 0.15 on Brier and 0.95 on pinball: the smaller route's p,
doubled.

- **H2 is confirmed.** Taker-wallet scores add to the CEX gap on both metrics, on every test
  day. With SOL as the discovery, the claim "taker-wallet scores add to the CEX gap" now stands.
- **H4 (pinball) is not confirmed.**
  - On SOL's corrected run, the forced-flow columns improved q10 pinball in the 60 s after forced
    fills (+0.025, 16/21 days).
  - On ETH the same test gives +0.0098, 14/21 days, with an interval that includes zero.
  - Under the pre-registration this is a failed replication, reported with its interval. The
    forced-flow claim is not made.
- **H3:** the placebo (L2 plus opposite-side lost races) is itself significant over all fills
  on Brier (raw p 0.004) and in `quiet` (p 0.028). H3 would fail on that clause alone, as on
  SOL.
- **H5's model confidence sets:** Brier {L3a, L3b, L3, placebo}; pinball {L2, L3a, L3b, L3,
  placebo}.

## Secondary results (not used for claims)

- **Quantile skill** (q10 / q50 / q90, against the training window's climatology, 6,792,832
  fills; L3 and L3b 6,135,786):

  | L0 | L1 | L2 | L3a | L3b | L3 |
  |---|---|---|---|---|---|
  | 0.172 / 0.187 / 0.216 | 0.373 / 0.323 / 0.330 | 0.472 / 0.357 / 0.330 | 0.472 / 0.360 / 0.330 | 0.472 / 0.355 / 0.327 | 0.472 / 0.356 / 0.330 |

- **Realised forced flow alone** (`l3b_realised` vs L2), pinball in `forced_60s`: +0.014,
  16/23 days, p 0.036. Over all fills: +0.0002, p 0.89.
- **Decomposition** of the L3 model's predicted 1 s adverse selection (tau 0.5 contributions,
  1,401,454 fills, 22 days):

  | Group | Share | 95% CI |
  |---|---|---|
  | Latency-arb | 71.7% | [63.1, 78.6] |
  | Wallet | 22.6% | [16.6, 30.5] |
  | State | 6.4% | [5.1, 7.7] |
  | Forced | -0.7% | [-1.9, 0.1] |

- **Fill-filter policies** (1 s, no fee, $1,000 a fill). These are not economic claims. S2 and
  S3 here pull on ladder models that see the fill's size and the taker's wallet, which a quoting
  maker cannot know (`docs/research/block-simulator.md`).

  | Policy | Quotes | bps per fill | S1 on its days |
  |---|---|---|---|
  | S2 | 39.5% of fills | +0.48 | -0.37 |
  | S3 | 41.1% | +0.45 | -0.35 |
  | Stale-quote rule (500 ms) | 90.1% | -0.21 | -0.40 |

## What follows

- H2 is the project's confirmed claim: SOL found it, and ETH confirmed it under a fixed
  pre-registration.
- The forced-flow result stays exploratory. A BTC run would need its own pre-registration and
  would not overrule this verdict. The January 2027 held-out month remains the second
  confirmatory test.
