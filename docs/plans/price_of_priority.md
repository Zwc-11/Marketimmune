# The Price of Priority

What Hyperliquid's cancel-first sequencing rule and its priority-fee market are
worth, and to whom, measured on a block-accurate replay of the exchange, and
then used to quote better.

## The question

HyperCore cuts arrivals into blocks of about 70 ms and processes each consensus
batch in a fixed order: post-only orders, then **cancels**, then takers. A maker
whose cancel lands in the same block as a snipe wins the race, however fast the
sniper was. Since April 2026 takers can also pay a priority fee (0–8 bps) to be
treated as arriving earlier, which can move a snipe into an *earlier* block but
can never beat a cancel inside the same one.

| Exp. | Asks | Method |
| ---- | ---- | ------ |
| E1a  | How many dollars a day does the cancel-first rule transfer to makers? | Counterfactual FIFO accounting on same-block races, bootstrapped over latency estimates |
| E1b  | What does losing a race by one block do to the maker afterwards? | Fuzzy regression discontinuity at the block cut (nonce-based arrival times) |
| E2   | What did selling priority change for maker adverse selection? | Staggered and exposure-intensity event studies over the fee rollout |
| E3   | What is a queue position worth when the size ahead can cancel first? | Competing-risk survival + counterparty-conditioned adverse selection (Moallemi–Yuan extended) |
| Signal | Do priority bids forecast toxicity beyond the CEX gap and wallet history? | L0–L3 LightGBM quantile ladder, Diebold–Mariano by regime, block-accurate simulation |

Deliverables (Mar 21, 2027): a sequencer memo with numbers, a tested Rust replay
crate, the race-episode dataset, and a preprint. Hypotheses H1–H5 are
pre-registered before the held-out window is scored.

## Status (2026-10-30, Phase 0)

| Component | State |
| --------- | ----- |
| `hl-replay` book + batch engine (match mode) | **Done.** Slab FIFO book, class-ordered `apply_batch`, property-tested against a reference model |
| `hl-replay-py` bindings | `Book` exposed; `replay(path, coin)` lands with the Phase 1 readers |
| G0 probe (`marketimmune/cli/probe_s3_day.py`) | Written and tested on synthetic files; waits for the AWS account |
| Recorder (`recorder/`) | Written and tested against a local server; goes live once `docs/jurisdiction.md`'s open question is settled |
| Albers L4 data (166 GB) | Downloading locally, md5-verified per file |
| Binance aggTrades | Downloader verified on real files (sha256) |
| Outcome mode, `replica_cmds` extractor, signer recovery, episodes | Phase 1 (Nov 16 – Dec 13) |
| E3 · E1 · E2 · signal + simulator | Phases 2–5 |

## Correctness

- **Property tests** (`crates/hl-replay/tests/proptest_book.rs`): 2 × 1,024 random
  streams of post-only, GTC and IOC orders and cancels (including cancels of
  filled orders and duplicate ids), with and without self-trade prevention, are
  applied batch by batch to the slab book and to a naive `Vec` reference. After
  every batch both must agree on every status, every fill and the full
  order-by-order book; the slab book must stay uncrossed, keep each level's
  cached total equal to the sum of its orders, and let a cancel remove only an
  order it can reach (one resting before the batch or a post-only placed in it,
  never a GTC placed later in the same batch).
- **Ordering rule** (`engine.rs` tests): a cancel beats a taker for the same
  quote in one batch whichever the proposer put first; across batches the earlier
  snipe fills and the later cancel finds nothing.
- **Next:** golden test of outcome mode against Hyperliquid's hourly L2 snapshots
  (Phase 1) and the cross-mode test, match mode == outcome mode on every block of
  a December 2025 day (Phase 3).

## Benchmark

Match-mode engine, 1,000,024 **synthetic** actions (≈50% post-only adds near the
touch, 40% cancels of live orders, 10% IOC takers, ~60 per batch), criterion:

| Machine | Time per run | Throughput | Per action |
| ------- | ------------ | ---------- | ---------- |
| 2 vCPU Intel Xeon @ 2.10 GHz (cloud VM), Rust 1.97, release + thin LTO | 95.8 ms | 10.4 M actions/s | ~96 ns |

The same benchmark on one real day of BTC from `replica_cmds`, with peak memory
and a flamegraph, replaces this once the Phase 1 extractor exists.

## Reproduce

The study now lives inside MarketImmune (merged 2026-10-30); commands run from the
repository root.

```bash
make rust-test        # cargo test --workspace --release (includes the proptests)
make rust-lint        # rustfmt, clippy -D warnings
make bench            # criterion replay benchmark + pipeline timings
make wheel            # maturin build of the hl_replay extension

make download-albers                      # 166 GB into data/bronze/albers, resumable
make download-binance COIN=SOL            # Dec 2025 aggTrades
python -m marketimmune.cli.probe_s3_day --date 2025-12-15   # on EC2 in Tokyo
```

Infrastructure: `deploy/ec2_tokyo.md` (requester-pays processing next to the
bucket), `deploy/recorder/README.md` (VPS with chrony and zstd rotation).

## Layout

```text
crates/hl-replay/                  Rust: types, book/, engine.rs, io/lz4_lines.rs; tests/, benches/
crates/hl-replay-py/               PyO3 bindings (maturin), module hl_replay
deploy/recorder/                   record.py, rotate.sh, chrony.conf, systemd/
deploy/ec2_tokyo.md, hyperliquid_node.md
marketimmune/config.py             paths, date windows, thresholds from configs/*.yaml
marketimmune/sources/              albers_download, binance_aggtrades, hyperliquid_s3,
                                   hyperliquid_meta, hyperliquid_replica (prototype parser)
marketimmune/lake/checks.py        data checks (fill legs, heights, block times, nonce delays)
marketimmune/priority/             fills.py (dedupe, pair, markouts), nonces.py (signer latency)
marketimmune/cli/probe_s3_day.py   Gate G0 probe
configs/                           data.yaml, episodes.yaml, sim.yaml
docs/research/                     jurisdiction.md, g0_probe_note.md
eval/                              one JSON per run, committed
data/                              gitignored: bronze/ silver/ gold/ logs/
```

Later phases (episodes, E1 to E3, signal, market maker, stats) are added with their
code, in Python under `marketimmune/priority/` and in Rust under `crates/`, not as stubs.

## Schedule

| Phase | Dates | Gate |
| ----- | ----- | ---- |
| 0 Setup and data access | Nov 2–15 | G0: resps in `replica_cmds`? cost per day? E1 dates? core-perp fee launch date? |
| Apply (Ellipsis 2027 SWE) | by Nov 20 | repository, recorder running, README |
| 1 Replay engine and episodes | Nov 16 – Dec 13 | G1: episode table with outcome counts; golden test; benchmarks |
| 2 E3 queue value | Dec 14 – Jan 3 | G2: H4 estimate with CI; pre-registration committed |
| 3 E1a and E1b | Jan 4–31 | G3: density and balance tests pass, or E1b reported as descriptive |
| 4 E2 event study | Feb 1–14 | G4: flat pre-trends in one design, or E2 descriptive |
| 5 Speed signal and simulator | Feb 15 – Mar 7 | G5: simulator == outcome mode with no injection; L3 vs L2 CI |
| 6 Held-out test, memo, release | Mar 8–20 | release Mar 21, 2027 |

## Data and licences

- Albers, Cucuringu, Howison & Shestopaloff, *An Open Book: Level 4 Order Book
  Data from the Hyperliquid Exchange*, Zenodo, doi:10.5281/zenodo.18184441,
  CC BY 4.0.
- Binance Vision datasets, CC BY-NC-SA 4.0: research use; anything released that
  contains Binance-derived fields carries the same licence.
- Hyperliquid S3 archives: requester pays; raw files are not redistributed.
- No order is ever placed: the strategy runs only in simulation. Access terms and
  the open question about live API use are in `docs/jurisdiction.md`.

## Deviations from the build plan

- `numpy==2.2.6`, not the latest: `hftbacktest 2.4.4` requires `numpy<2.3`.
- `duckdb==1.5.6`: 2.0.0 was nine days old on the day of pinning.
- The book core was started in Phase 0. It has no data dependency, and the
  Nov 20 application needs the replay engine's first correctness test.
- Added `marketimmune/sources/albers_download.py` (Zenodo throttles single connections to about
  1 MB/s, so it fetches 8 byte ranges per file in parallel) and
  `marketimmune/sources/hyperliquid_replica.py` (the Lesson 3.1 prototype parser the probe uses).
- The recorder writes hourly files itself; `rotate.sh` only compresses closed hours.

## Licence

The Rust crates declare MIT in `Cargo.toml`; the Python package declares Apache-2.0.
