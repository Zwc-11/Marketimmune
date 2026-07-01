# MarketImmune — résumé bullets (honest now vs. target)

Two versions. Use the **interim** set today — it survives a full read of the repo.
Move to the **target** set only after Phase 2 of `AUDIT_AND_PLAN.md` makes the claims
true. Rule: never ship a bullet the repo can't survive a `grep` of.

---

## Interim (true today — defensible against a code review)

- Built an **AI market-safety platform** that detects risky autonomous-trading behavior
  and produces auditable risk decisions, with a **React/TypeScript** dashboard over a
  **Django REST API**.
- Designed a **Generate → Detect → Investigate → Decide → Remember** loop (5 stages,
  8 modular agent roles), persisting every tool call, decision trace, and policy action
  to an **append-only Django ORM audit log** — fully reproducible.
- Engineered a multi-window **order-flow feature store** and a **gradient-boosting risk
  head** (scikit-learn) with a held-out benchmark (PR-AUC / F1 / sub-ms inference),
  plus a CT-LSTM/Neural-Hawkes temporal baseline.
- Enforced engineering rigor: `mypy --strict`, `ruff`, 32 test modules with a 100%
  coverage gate, and GitHub Actions CI.

> Optional honesty flourish (strong signal in quant/ML interviews): "…and identified
> that the original benchmark trained on self-generated scenarios (label leakage), then
> scoped a leakage-proof v2 (purged/embargoed walk-forward CV on real perp data)."

## Target (true after Phase 2 — your current bullets, then backed by code)

- Built a toxic-flow detection platform on **real Hyperliquid perpetual-swap data**,
  helping trading agents detect adverse selection and audit risk decisions.
- Implemented a **Generate → Detect → Investigate → Decide → Remember** loop across the
  agent cast, storing traces and policy decisions in a Django ORM audit log.
- Engineered **point-in-time** order-flow features and trained a **CatBoost** markout
  classifier under **purged/embargoed walk-forward CV** (isotonic-calibrated), lifting
  out-of-sample **markout by N bps** vs. an OFI baseline.
  *(Report the measured N — whatever the honest number is. Modest + real beats large + fake.)*

---

## What changed and why (for your own reference)

The original bullets described the **target** system (`CLAUDE.md` vocabulary), but the
code today is: **synthetic** scenario data → **scikit-learn GradientBoosting** (not
CatBoost) → **random train/test split** (not purged walk-forward) → **binary
hostile/benign** label (no markout, no bps). The Hyperliquid port/adapter is an empty
seam. See `AUDIT_AND_PLAN.md §1` for the claim-by-claim breakdown.
