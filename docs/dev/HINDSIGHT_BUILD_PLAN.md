# Hindsight — Implementation Plan (execution layer)

> **What this is.** The *Engineering Spec & Build Plan* you wrote is the **what/why**.
> This document is the **how/when**, reconciled against the actual state of
> `C:\MarketImmune` as of 2026-06-30. Read the spec first; this plan only adds
> sequencing, the concrete file/task breakdown, and — most importantly — the
> places where the spec's assumptions **do not match what is on disk**, with the
> corrective action for each.
>
> **Golden rule inherited from the spec:** ship each milestone *fully green*
> before starting the next. This plan is ordered so you never build ahead.

---

## 1. Spec ↔ repo reconciliation (read this before writing any code)

The spec's §3 reuse map is **largely accurate** — `schemas/events.py`,
`replay/{cursor,clock,replay_runner}.py`, `lake/{parquet_io,manifest}.py`,
`simulator/data_loader.py`, and the `ingest/binance_*` parsers all exist and are
shaped as described. `EventCursor`, `ReplayClock`, `run_hash`, and `stable_hash`
are tiny and clean to port. But several load-bearing assumptions are wrong, and
each one changes a milestone task list:

| # | Spec says | Repo actually is | Corrective action |
|---|-----------|------------------|-------------------|
| R1 | "Coverage 100% — `pyproject.toml` sets `fail_under = 100`" (§0.3) | `fail_under = 95` (`pyproject.toml:93`) | Treat 95 as the **repo gate**. Adding `hindsight` to `[tool.coverage.run] source` means weakly-covered hindsight code drags the **whole repo** under 95 → every hindsight module ships with real tests in the same change. Target ~100% on hindsight for headroom; do **not** unilaterally raise the global `fail_under` to 100 (may break other modules). See Open Decision O1. |
| R2 | M0: "add `hindsight*` to pyproject setuptools + mypy + coverage" (§17.2) | `scripts/typecheck.py` **hardcodes** `mypy … marketimmune aegisbench` and an AST-fallback `python_files()` list; it does **not** read `[tool.mypy] packages` | Editing pyproject is necessary but **not sufficient**. Also add `"hindsight"` to the `subprocess.run([... "mypy", ..., "marketimmune", "aegisbench"])` arg list **and** to `python_files()` in `scripts/typecheck.py`, or hindsight is silently never type-checked in CI. |
| R3 | "No Hyperliquid data or adapter in the repo yet"; HL is an M3 concern | A full `data/hyperliquid/` **bronze/silver/gold medallion lake exists** (real `fills`, `markout`, `training` parquet), plus `ingest/hyperliquid_*` modules and a `hyperliquid` optional-deps group | Re-scope M3: the ingest + lake exist; what's missing is a `MarketDataPort` **adapter** and a canonical-event mapping. This also unlocks the M2 markout track early (see §2). |
| R4 | M1 fill oracle = trade-through fills against real `aggTrades`; mark against `bookTicker`; validated on "the Binance data that already exists" | Binance lake on disk = **one day** (2026-06-20), **klines + bookDepth only**, **90 kline rows**, **no `aggTrades`, no `bookTicker`** | The headline limit-fill path has nothing to run against on Binance. Resolve via the data strategy in §2: synthetic fixtures for correctness, existing Binance klines for the M1 *demo*, HL fills for the M2 markout track. |
| R5 | Feed HL prints through the canonical event model (§3.1) | `TradeEvent`/`AggTradeEvent` hardcode `source: Literal[EventSource.BINANCE_PUBLIC]`, and `EventSource` only has `BINANCE_PUBLIC` / `SYNTHETIC_AGENT` | To ingest HL fills honestly, extend the schema in place (spec §3.1 sanctions this): add `EventSource.HYPERLIQUID_PUBLIC` and widen the `source` Literal (or add an HL fill event type), and update `tests/schemas`. This is an M2/M3 task, not M0. |
| R6 | "normalize at the adapter boundary" (§16 timezone landmine) | `data_loader.py::_parse_iso` returns **naive** datetimes (`.replace(tzinfo=None)`, line 72). The event schema's `timestamp_must_be_aware` validator **raises** on naive input | Confirmed real. The hindsight adapter must attach `tz=UTC` before constructing events. Good news: the validator makes this **fail-loud**, not silent — but the adapter code must convert. |
| R7 | Branch `feat/hindsight-m0`, "one PR per milestone" | Working tree is **dirty on `master`** (many `M`/`D` files; the spec-referenced `MarketImmune_v2_Refactor_Plan.md` and `RECRUITER_ROADMAP.md` are staged **deleted**). No `main`. | Commit/stash the dirty tree first, or the feature branch inherits unrelated churn. Confirm the git flow (Open Decision O2) — solo local `master` may not want a formal PR-per-milestone dance. |
| R8 | New `hindsight/ports/market_data.py::MarketDataPort` | `marketimmune/ports/market_data.py` already defines `KlineSource`/`DepthSource` Protocols and `marketimmune/adapters/{binance,factory}.py` already alias the repositories | No conflict (different, broader streaming port), but **reuse** the established ports-and-adapters pattern and the `adapters/binance.py` alias style rather than inventing a second convention. |

**Net:** M0 is essentially as the spec describes (plus the `typecheck.py` edit, R2). M1's
*correctness* is unaffected (synthetic fixtures), but its *real-data demo* must
use Binance klines, not aggTrades. M2 and M3 shift because the HL data/ingest
already exist.

---

## 2. Data strategy (resolved recommendation)

The engine is venue-agnostic behind `MarketDataPort`, so the *source* is a
per-milestone choice. The best option — solving the R4 gap while honoring the
spec's "don't build later milestones early" rule — is a hybrid keyed to what
each milestone genuinely **needs**:

**(a) All tests, determinism, and fill-model correctness → tiny synthetic fixtures.**
Checked into `tests/hindsight/fixtures/`. This is where limit trade-through
fills, partial-fill accumulation, PIT `LookaheadError`, funding sign, and the
golden-run hash are proven. These must be deterministic and tiny — never depend
on multi-hundred-MB parquet. **Reuse the CSVs that already exist** in
`tests/fixtures/` (`agg_trades.csv`, `book_ticker.csv`, `trades.csv`,
`klines.csv`) as seeds — they already carry the right columns.

**(b) M1's "naive-vs-realistic divergence" demo → the Binance klines already on disk.**
The spec's own fill model permits market fills at kline-close when `bookTicker`
is absent ("fall back to the most recent mid (kline close) and flag
`top_of_book_missing`"). So the `momentum` baseline demonstrates the edge
collapsing under fees + funding + latency on **real data with zero new
acquisition** and **no phasing violation**. Caveat: 90 one-minute bars is enough
to *show* divergence, not to compute a statistically meaningful Sharpe — treat
the M1 demo as **illustrative**, and defer real Sharpe/DSR/PBO to M2 on the
larger HL dataset.

**(c) M2's markout track → the Hyperliquid `fills`/`markout` already on disk.**
This is the earliest point real trade prints are *required* (markout needs real
subsequent prints; Binance has none on disk). And they are already present:

- `data/hyperliquid/bronze/hyperliquid/fills/SOL/*.parquet` — **210k real prints/day**,
  columns `coin, ts_ms, px, sz, side, crossed, maker_side, oid, tid, hash, fee,
  fee_token, builder_fee, direction, raw_json`. A real fill oracle **with fees**.
- `.../gold/hyperliquid/markout/SOL/*.parquet` — same keys + `markout_bps_1s/10s/60s`
  and `toxic_1s/10s/60s`. **Ground-truth markout and toxicity labels already
  computed** → the résumé's "markout lift" and "~0.769 PR-AUC toxic-flow" get a
  real, on-disk source, and the engine's own markout computation has something to
  reconcile against.
- `.../gold/hyperliquid/training/SOL/*.parquet` — full feature set (`l2_mid,
  l2_microprice, l2_spread_bps, l2_top_imbalance, l2_ofi_event/1s/5s/10s,
  asset_basis_bps, asset_funding, asset_open_interest, asset_premium`) **with a
  separate `feature_ts_ms`** — i.e. the as-of feature lag the spec's §9 wants is
  already materialized. Strong signal the leakage discipline is partly there.

Choosing HL for M2 pulls the HL adapter forward from the spec's M3, but that is
**not** "building M3 early for its own sake" — M2's DoD requires real prints and
the only real prints on disk are HL. Frame it that way in the PR.

**(d) Binance `aggTrades`/`bookTicker` download → optional, not a blocker.**
The ingest tooling exists (`ingest/binance_downloader.py`, `binance_parsers.py`).
Pull a slice only if you want a *second* real venue to prove venue-agnosticism on
the trade-through path. Guard it behind availability/requester-pays; never let it
gate a milestone.

**Caveats to flag in the plan and the résumé:**
- The HL data on disk is **SOL**, not `BTC-PERP`. "Real Hyperliquid
  perpetual-swap microstructure" is honest; the literal **`BTC-PERP`** claim
  needs a BTC HL backfill (`ingest/hyperliquid_backfill.py` can do it) — a small,
  non-blocking acquisition task (M3, or opportunistically earlier).
- The HL contiguous block is `20260527–20260601` (~6 days) plus one far-earlier
  `20250727` smoke day. Build M2 folds on the contiguous block; treat `20250727`
  as a smoke fixture, not a fold.

---

## 3. Cross-cutting conventions & gates (confirmed against the repo)

Every hindsight change must satisfy these **before** it is considered done. They
are enforced in `.github/workflows/ci.yml` and locally via `make` / the scripts.

- **Style / lint:** `ruff check .` clean — `select = ["E","F","I","UP","B","SIM"]`,
  line-length **100** (`pyproject.toml:52-57`).
- **Line budget:** `scripts/check_line_limit.py` fails any hand-written source
  file **> 1000 lines** (`.py/.ts/.tsx/.js/.jsx/.css`; markdown exempt). Keep
  `execution/simulator.py` and `evaluation/metrics.py` split before they bloat.
- **Types:** `scripts/typecheck.py` runs `mypy --strict` over the hardcoded
  package list → **must add `"hindsight"` there (R2)**. Conventions: `from
  __future__ import annotations` at the top of every module; no untyped defs; no
  `Any` across public interfaces.
- **Tests + coverage:** `pytest` green; `coverage run -m pytest && coverage
  report` at **`fail_under = 95`** over `source = ["marketimmune", "aegisbench"]`
  → **add `"hindsight"`** (R1). Tests live under `tests/hindsight/` mirroring the
  package; assert **behavior**, not line execution.
- **Value objects:** frozen — `@dataclass(frozen=True, slots=True)` for pure
  values; `pydantic.BaseModel` with `model_config = ConfigDict(frozen=True,
  extra="forbid")` for validated/serialized models; `StrEnum` for enums. (Mirror
  `core/types.py` and `execution/config.py` from the spec §7.)
- **Purity:** core/domain is dependency-free — no parquet, Django, or network
  inside `hindsight/core`, `pit`, `strategy`, `execution`, `portfolio`,
  `evaluation`. All IO lives in `hindsight/data/*` adapters (repository pattern).
- **Determinism:** `sha256(json.dumps(..., sort_keys=True,
  separators=(",",":"), default=str))` everywhere state is summarized — reuse the
  ported `stable_hash`/`run_hash`.
- **Time:** UTC-aware at the schema boundary; normalize naive parquet timestamps
  **inside the adapter** (R6).
- **Also runs in CI (don't break them):** `python manage.py check` +
  `makemigrations --check`, `frontend` typecheck + build, and
  `scripts/phase_metrics.py`. Hindsight is pure-Python/CLI, so these should stay
  green untouched — but run the full CI locally before each PR.

---

## 4. Milestone execution plans

Each milestone: **goal → ordered tasks (files) → tests → corrected DoD**. M0/M1
are detailed (they're next); M2 medium; M3/M4 lighter.

### M0 — Scaffold & reuse wiring  ·  branch `feat/hindsight-m0`

**Goal:** the package exists, is wired into all gates, and `hindsight run`
streams the existing Binance data through a no-op strategy to a valid (empty)
report + manifest.

**Ordered tasks:**

1. **Pre-flight (R7):** commit or stash the dirty `master` tree; branch
   `feat/hindsight-m0` from a clean base.
2. **Scaffold `hindsight/` tree** exactly per spec §6 — empty modules with
   docstrings + typed stubs.
3. **Wire the gates (R1/R2):**
   - `pyproject.toml`: add `hindsight*` to `[tool.setuptools] packages.include`;
     add `"hindsight"` to `[tool.mypy] packages`; add `"hindsight"` to
     `[tool.coverage.run] source`.
   - `scripts/typecheck.py`: add `"hindsight"` to the `mypy` subprocess args **and**
     to `python_files()`.
   - Add `tests/hindsight/` to the tree (pytest `testpaths = ["tests"]` already
     picks it up).
4. **Port primitives** into `hindsight/core/` with their own tests:
   `clock.py` (`ReplayClock`), `cursor.py` (`EventCursor`), `hashing.py`
   (`stable_hash`/`run_hash`). (Port, don't import, so `hindsight` core has no
   dependency back into `marketimmune.replay`; spec §3.2 allows either — porting
   keeps the layering clean.)
5. **`hindsight/execution/config.py`** — `ExecConfig` (frozen pydantic, spec §7),
   keep the `# TODO(verify)` fee notes.
6. **`hindsight/reporting/manifest.py`** — `RunManifest`; `git_sha` via
   `subprocess` `git rev-parse HEAD` with `"unknown"` fallback; `run_id =
   stable_hash(engine_version, git_sha, data_content_hash, config_hash, seed)`.
7. **`hindsight/ports/market_data.py`** — `MarketDataPort` Protocol (streaming
   contract, spec §7).
8. **`hindsight/data/repositories.py`** — `AggTradeRepository`,
   `BookTickerRepository` mirroring `KlineRepository`/`DepthRepository`. They
   return `[]` gracefully when files are absent (they will be, on Binance — R4).
9. **`hindsight/data/binance_adapter.py`** — `BinanceLakeAdapter(MarketDataPort)`,
   reusing `simulator/data_loader.py` repositories, **normalizing timestamps to
   UTC-aware at the boundary (R6)** and emitting canonical events in
   `(timestamp, sequence, event_id)` order.
10. **No-op `Strategy`** + the `hindsight run` CLI path (`hindsight/cli.py`) that
    streams events end-to-end and writes a valid empty JSON + Markdown report and
    a `RunManifest`.

**Tests:** primitive ports (clock monotonic-raise, cursor tie-break ordering,
hash stability); `ExecConfig`/`RunManifest` validation + `run_id` determinism;
repositories on a tiny fixture parquet (and the empty-dir path); adapter
timezone normalization (assert emitted events are tz-aware UTC); end-to-end
`hindsight run` on the on-disk Binance klines produces a schema-valid report.

**Corrected DoD:**
- [ ] `hindsight run` streams the existing Binance data through the no-op
  strategy → valid report + manifest.
- [ ] `ruff` clean · `scripts/typecheck.py` green **with hindsight in the mypy set (R2)** · `pytest` green.
- [ ] Coverage report ≥ 95 with `hindsight` in `source`; hindsight modules ~100%.
- [ ] `scripts/check_line_limit.py` passes.
- [ ] Package wired into pyproject **and** `scripts/typecheck.py`.
- [ ] PR opened with this checklist. **Stop — do not start M1 until merged.**

### M1 — Core engine (the shippable milestone)  ·  `feat/hindsight-m1`

**Goal:** a deterministic, PIT-safe, fee/funding/slippage/latency-realistic
engine with the naive-vs-realistic verdict, on the `momentum` baseline.

**Ordered tasks:**

1. **`hindsight/core/types.py`** — `OrderIntent`, `Fill`, `Position`,
   `PortfolioState`, `EquityPoint`, `OrderType`, `TimeInForce` (frozen; spec §7).
2. **`hindsight/pit/view.py`** — `PointInTimeView` wrapping event history + clock;
   accessors (`recent_trades`, `top_of_book`, `klines`) that **physically refuse**
   any record with `timestamp > clock.now`, raising `LookaheadError`.
3. **`hindsight/pit/features.py`** — as-of join with strict `feature.timestamp ≤
   t − feature_lag` (default `feature_lag ≥ 1` bar).
4. **`hindsight/strategy/base.py`** — `Strategy` Protocol + lifecycle hooks
   (`on_start/on_event/on_fill/on_finish`).
5. **`hindsight/execution/`** — `slippage.py` (pure impact formula, spec §8),
   `funding.py` (pure accrual; `funding_missing` WARN path), `simulator.py`
   (`ExecutionSimulator`: merged event+order stream via `EventCursor`,
   latency-to-active, market fills vs `bookTicker`→kline-close fallback flagged
   `top_of_book_missing`, limit trade-through fills against prints with
   `participation_cap`, maker/taker fees, funding). Split if it nears 1000 lines.
6. **`hindsight/portfolio/accounting.py`** — `Portfolio`: position, cash,
   realized/unrealized, `equity = cash + position·mark`, equity-point cadence.
7. **`hindsight/strategy/baselines/momentum.py`** — kline breakout.
8. **Naive-vs-realistic runner** — run twice (naive: mid fill, zero
   fee/funding/latency; realistic: full model); overlay curves + Sharpe delta +
   one-line verdict.
9. **`hindsight/reporting/`** — `json_report.py`, `markdown_report.py` (verdict
   banner → curves → fees/funding → manifest), `curves.py` (JSON always; PNG iff
   matplotlib importable; ASCII sparkline fallback — **no hard matplotlib dep**).

**Tests (spec §15):** property (clock monotonic; no fill before active time; PIT
fuzz never returns future data; equity conservation vs ledger; `run_hash`
stable); **golden-file** (tiny fixture + fixed strategy → snapshot full JSON
report); fill-unit (limit fills exactly when a print crosses and not otherwise;
partials accumulate; market touch + slippage sign; maker/taker fee; funding sign
for long/short).

**Corrected DoD:**
- [ ] Golden-run determinism test passes (same inputs+seed → identical `run_hash`).
- [ ] Real backtest **on the on-disk Binance klines** shows the two equity curves
  visibly diverge under realism (illustrative; see §2b caveat on 90 bars).
- [ ] Markdown report human-readable with verdict banner.
- [ ] PIT view provably raises `LookaheadError` on future access (tested).
- [ ] All gates green; hindsight coverage ~100%.

### M2 — Rigor & benchmark  ·  `feat/hindsight-m2`

**Goal:** purged/embargoed walk-forward, leakage auditor, DSR, PBO(CSCV), the
markout track, and the `ofi_quote` + `leaky` baselines — with the markout number
computed on **real HL data**.

**Key tasks:**
- `evaluation/walk_forward.py` — López de Prado purge + embargo (`label_horizon,
  purge, embargo, n_folds, train_window, test_window`); unit-test no
  purged/embargoed sample survives and folds never overlap. Use the contiguous HL
  block `20260527–20260601` (§2c).
- `evaluation/leakage.py` — the four probes (full-sample-normalization,
  target-leakage, look-ahead perturbation, temporal-overlap); hard vs soft
  violations.
- `evaluation/metrics.py` — Sharpe/drawdown/turnover/fees/funding + **markout**
  (realized N-s markout bps per fill) + **markout lift vs OFI baseline** (per
  fold, with CI) + Deflated Sharpe + PBO via CSCV. Reconcile the engine's markout
  against the on-disk `markout_bps_10s` gold column as a correctness check.
- **HL enablement (R3/R5):** `hindsight/data/hyperliquid_adapter.py`
  (`MarketDataPort`) reading `bronze/.../fills`; extend `schemas/events.py`
  (`EventSource.HYPERLIQUID_PUBLIC`, widen `source` Literal / HL fill event) +
  update `tests/schemas`; map `fills` columns → canonical events (`side` B/A →
  `Side`; `crossed`/`maker_side` → maker/taker; `fee` carried through).
- `strategy/baselines/{ofi_quote,leaky}.py`; `benchmark` suite → leaderboard CSV.

**Corrected DoD:** `leaky` is flagged and **fails the run**; a good-naive-Sharpe
strategy shows high PBO and DSR ≈ 0 after realism + multiple-testing; benchmark
CSV byte-for-byte reproducible across two runs; **markout-lift number produced
per fold with a CI** on real HL data; gates green.

### M3 — Hyperliquid demo layer & venue-agnostic proof  ·  `feat/hindsight-m3`

Re-scoped given R3 (ingest + lake already exist):
- If the HL adapter landed in M2, M3 = prove **the same strategy runs unchanged
  on Binance and Hyperliquid** via the port (venue-agnostic test); otherwise land
  the adapter here.
- Acquire a **`BTC-PERP` HL slice** via `ingest/hyperliquid_backfill.py` so the
  résumé's literal `BTC-PERP` claim is backed (§2 caveat).
- Wire the v2 toxic-flow model as the application on top; hosted dashboard
  **reusing the existing frontend design system** (`CLAUDE.md` — Geist terminal,
  do not redesign). Keep the "Preview · simulated data" honesty badge.

**DoD:** one strategy runs unchanged on both venues via the port; a live URL
shows the naive-vs-realistic verdict for ≥1 real episode; gates green.

### M4 — Polish & traction

README verdict demo (GIF of a curve collapsing when realism toggles on), docs,
writeup with the **computed** DSR/PBO/markout numbers (not claims), published.
**DoD:** repo legible in 60s; writeup with real numbers; posted.

---

## 5. Test & fixtures strategy

- **Reuse existing seeds:** `tests/fixtures/{agg_trades,book_ticker,trades,klines}.csv`
  already carry the right columns — build the tiny hindsight fixtures from them
  rather than inventing new ones. Mirror `tests/replay/test_replay.py` for style.
- **Fixture parquet:** a handful of rows per type under
  `tests/hindsight/fixtures/`, deterministic, checked in. Golden JSON reports live
  beside them; a diff must be an intentional, reviewed change.
- **Coverage is behavioral (R1):** the 95 gate over a `source` that now includes
  `hindsight` will tempt line-filler tests — reject them in review. Property +
  golden + adversarial tests are the substance.
- **Adversarial:** `leaky` must be caught by the auditor and fail; a hand-built
  overfit config must yield high PBO.

---

## 6. Risk register

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| **Timezone landmine (R6):** naive parquet timestamps crash the schema validator | High if unhandled | Normalize to UTC-aware inside every adapter; test that emitted events are tz-aware. Validator fails loud, so this surfaces immediately. |
| **Coverage drags whole repo < 95 (R1)** | Medium | Ship tests with code every change; keep hindsight ~100%; watch `coverage report` locally before PR. |
| **typecheck silently skips hindsight (R2)** | High if missed | Edit `scripts/typecheck.py` in M0; add a test/assert that hindsight is in the checked set. |
| **M1 fill oracle has no Binance prints (R4)** | Certain | Synthetic fixtures for the limit path; klines for the demo; HL fills for markout (§2). |
| **Same-ms event ordering** | Medium | Always tie-break `(timestamp, sequence, event_id)` via `EventCursor`; never insertion order. |
| **Funding correctness** | Medium | Configurable schedule/rate; missing rate → 0 + `funding_missing` WARN, never silent. |
| **`bookDepth` mistaken for L2** | Medium | It's %-from-mid notional bands; fill oracle is prints only; keep the honest band framing from `pricing.py`. |
| **Queue-position optimism** | By design | Front-of-queue is an optimistic bound; state it in every report. |
| **Scope creep (lakehouse/MLflow/Django)** | High | Out of scope until M3+; library + CLI first. Reject in review. |
| **SOL≠BTC-PERP (§2 caveat)** | Certain | Say "real HL perpetual-swap microstructure"; backfill BTC in M3 for the literal claim. |

---

## 7. Immediate next actions (execution-ready M0 checklist)

Corrected from spec §17 — do these, in order:

1. [ ] Commit/stash dirty `master`; create `feat/hindsight-m0` (R7).
2. [ ] Scaffold the `hindsight/` tree (§6 spec) — typed stubs + docstrings.
3. [ ] Wire gates: pyproject (setuptools/mypy/coverage) **+ `scripts/typecheck.py`** (R1/R2).
4. [ ] Port `EventCursor`, `ReplayClock`, `stable_hash`/`run_hash` into `hindsight/core/` + tests.
5. [ ] `ExecConfig` (`execution/config.py`), `RunManifest` (`reporting/manifest.py`, git-sha subprocess), `MarketDataPort` (`ports/market_data.py`).
6. [ ] `AggTradeRepository` + `BookTickerRepository` (`data/repositories.py`); `BinanceLakeAdapter` (`data/binance_adapter.py`) with UTC normalization (R6).
7. [ ] No-op `Strategy` + `hindsight run` → valid empty JSON+MD report + `RunManifest`.
8. [ ] All gates green, coverage 100% on hindsight → open the M0 PR. **Stop.**

---

## 8. Open decisions / assumptions

- **O1 — Coverage target.** Keep repo gate at 95 and hold hindsight ~100%
  (assumed), **or** raise global `fail_under` to 100 as the spec wants (risk:
  other modules may sit in 95–99 and break). Recommend: hold at 95 now, revisit
  after M1.
- **O2 — Git flow.** Spec wants branch + PR per milestone. This is a solo local
  `master` repo with no visible remote/PR process. Assumed: feature branch per
  milestone, DoD in the commit/PR body; skip formal PR ceremony if there's no
  remote. Confirm.
- **O3 — Keep the Binance `aggTrades` download?** Assumed optional (§2d) — only if
  a second real venue is wanted on the trade-through path. Default: skip until
  after M2.
- **O4 — `MarketImmune_v2_Refactor_Plan.md` is deleted** in the working tree but
  referenced by the spec (§2.1, Appendix A). Assumed intentional; the Hindsight
  spec supersedes it. Confirm before relying on it as a reference.
