# Results: the SOL December 2025 feature ladder

Rules: `docs/preregistration/sol-dec-2025-ladder.md`. Two runs, scored with the same
rules:

- **Registered:** code `8f731c0`, Dec 12 excluded, reports in `eval/sol_dec_registered/`.
- **Corrected:** the month rebuilt after the three data fixes in Deviations
  (2026-10-31), Dec 12 kept, reports in `eval/sol_dec_corrected/`.

A hypothesis is claimed only if both runs support it on both primary metrics.
Reproduce the table (it writes `eval/ladder_verdicts.json`):

    python -m marketimmune.cli.score_ladder --runs eval/sol_dec_registered,eval/sol_dec_corrected

Holm runs across H1-H4 within a metric. H4 has two registered routes (`forced_60s` or
overall): the one with the smaller p enters Holm with that p doubled.

## Verdicts

Each cell reads Brier / pinball at tau 0.1.

| H | Comparison | Registered | Corrected | Verdict |
|---|---|---|---|---|
| H1 | L1 vs L0, all fills | yes / yes | yes / yes | **Claimed** |
| H2 | L2 vs L1, all fills | yes / no (Holm p 0.074) | yes / yes | Not claimed; exploratory |
| H3 | L3a vs L2, `cex_move`; placebo not significant | no / no | no / no | Null |
| H4 | L3b vs L2, `forced_60s` or all | no / no | no / yes | Not claimed; exploratory (pinball only) |
| H5 | L0 and L1 outside the MCS (alpha 0.10) | yes / yes | yes / yes | **Claimed** |

Mean daily loss reduction, days improved, DM p (Holm), bootstrap 95% CI:

| H | Run | Brier | Pinball tau 0.1 |
|---|---|---|---|
| H1 | Registered | +0.0096, 21/23, p 4.8e-6 (1.4e-5), [0.0064, 0.0122] | +0.128, 22/23, p 0.012 (0.046), [0.069, 0.230] |
| H1 | Corrected | +0.0113, 24/24, p 2.6e-14 (1.0e-13), [0.0101, 0.0126] | +0.077, 24/24, p 9.0e-12 (3.6e-11), [0.065, 0.090] |
| H2 | Registered | +0.0110, 22/23, p 2.3e-6 (9.3e-6), [0.0080, 0.0143] | +0.042, 22/23, p 0.025 (0.074), [0.007, 0.074] |
| H2 | Corrected | +0.0129, 24/24, p 4.2e-9 (1.3e-8), [0.0103, 0.0155] | +0.059, 24/24, p 8.6e-7 (2.6e-6), [0.041, 0.076] |
| H3 | Registered | -0.0055, 11/23, p 0.22 | +0.0068, 9/23, p 0.50 |
| H3 | Corrected | -0.0003, 13/24, p 0.49 | -0.0009, 10/24, p 0.85 |
| H4 | Registered | all +0.0026, 12/21, p 0.28 | `forced_60s` +0.079, 14/20, p 0.12 (0.48), [0.018, 0.180] |
| H4 | Corrected | all +0.0005, 17/22, p 0.21 | `forced_60s` +0.025, 16/21, p 0.0008 (0.003), [0.013, 0.039] |

- **H3's placebo** (L2 plus opposite-side lost races) is itself significant at raw p ≤ 0.10
  in both runs: registered pinball `forced_60s` p 0.026, corrected Brier
  `taker_liquidation` p 0.051. H3 would fail on that clause alone.
- **H5's model confidence sets:** registered {L2, L3a, L3b, L3, placebo} on both metrics.
  Corrected: Brier {L3a, L3b, L3}, pinball {L2, L3a, L3b, L3, placebo}.
- **What the fixes changed:** mostly noise. The phantom books and duplicated fills of
  Dec 9, 15, 18, 19, 21 and 30 added loss variance across days. H1's Brier interval is
  2.3x narrower in the corrected run, and H2's pinball p falls from 0.025 to 8.6e-7.
  Because the fixes came after the results were seen, H2 and the H4 pinball result stay
  exploratory until data the analysis has not touched confirms them.

## Secondary results (not used for claims)

- **Realised forced flow alone** (`l3b_realised` vs L2), pinball in `forced_60s`:
  registered +0.022 (17/22 days, p 0.0004), corrected +0.016 (19/23, p 0.024). L3b,
  which adds the forecast, gives +0.025 in the corrected run. No direct L3b vs
  `l3b_realised` test was run.
- **Forced-flow forecaster** (29 days, 60 s horizon unless stated, corrected run):
  - Beats climatology and the liquidation heatmap at 5, 15 and 60 s on Brier (p ≤ 0.0008).
  - On its own it loses to persistence at every horizon.
  - Model + persistence beats persistence at 60 s (p 0.0023; registered 0.0065), but
    not at 5 s (p 0.17) or 15 s (p 0.059).
  - Lead time over 606 onsets: the model catches 43.1% at a 5.2% alarm rate, the
    heatmap 34.0% at 7.8%. The hit-rate difference is not significant (p 0.92).
- **Decomposition** (L3 quantile model, tau 0.5, TreeSHAP groups), share of predicted
  adverse selection:

  | Run | Latency-arb | Forced | Residual (wallet + state) |
  |---|---|---|---|
  | Registered, all fills | 57.8% | 3.8% | 38.5% |
  | Corrected, all fills | 58.0% [48.2, 64.4] | 1.7% [0.3, 3.3] | 40.3% (27.6 + 12.7) |

  In the corrected run, latency-arb is 78.0% in `cex_move` and 73.6% in `forced_60s`,
  where forced flow is 8.2%.
- **Policies.** These use the fill-filter approximation: queue position is ignored,
  fees are zero, and each fill is $1,000. They are not economic claims (pre-registration,
  "What will not be done"). At 1 s:

  | Policy | Registered | Corrected |
  |---|---|---|
  | S1, quote on every fill | +0.128 bps | -0.219 bps |
  | S2, quote when q10 ≥ -2 bps (43% of fills) | -2.27 bps | +0.66 bps, better than S1 on 24/24 days |
  | S3 | +0.79 bps | +0.64 bps, 22/22 days |
  | Stale-quote rule, 500 ms | -0.16 bps | +0.03 bps |

  - The registered S1 was positive only because of the phantom Dec 19 book. The
    corrected S1 matches the Dec 1-11 figure disclosed before registration (-0.27 bps).
  - Every policy is below a 1.5 bp maker fee.
