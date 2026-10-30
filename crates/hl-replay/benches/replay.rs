//! Throughput of the match-mode engine on a synthetic action stream.
//!
//! Until the first real day is extracted this uses a generated stream shaped
//! like a busy perp: about half post-only adds near the touch, 40% cancels of
//! live orders, 10% IOC takers, ~60 actions per batch. Replace with one day of
//! BTC from `replica_cmds` once Phase 1's extractor lands, and report both.

use std::hint::black_box;

use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use hl_replay::{Action, BatchOut, Book, EngineConfig, Op, Side, Tif, apply_batch};

struct XorShift(u64);

impl XorShift {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }
    fn below(&mut self, n: u64) -> u64 {
        self.next() % n
    }
}

/// Generate `n_actions` in batches by driving a live book, so cancels name
/// orders that exist (or just filled) the way real cancels do.
fn stream(n_actions: usize, seed: u64) -> Vec<Vec<Action>> {
    let mut rng = XorShift(seed);
    let mut book = Book::with_capacity(1 << 16);
    let mut out = BatchOut::default();
    let cfg = EngineConfig::default();
    let mut live: Vec<u64> = Vec::new();
    let (mut oid, mut mid, mut made) = (1u64, 1_000_000i64, 0usize);
    let mut batches = Vec::new();
    while made < n_actions {
        let len = 30 + rng.below(60) as usize;
        let mut batch = Vec::with_capacity(len);
        for _ in 0..len {
            let user = rng.below(2_000) as u32;
            let side = if rng.below(2) == 0 { Side::Bid } else { Side::Ask };
            let r = rng.below(100);
            let op = if r < 50 {
                let off = 1 + rng.below(10) as i64;
                let tick = if side == Side::Bid { mid - off } else { mid + off };
                oid += 1;
                live.push(oid);
                Op::Order { oid, side, tick, lots: 1 + rng.below(50), tif: Tif::Alo }
            } else if r < 90 && !live.is_empty() {
                let k = rng.below(live.len() as u64) as usize;
                Op::Cancel { oid: live.swap_remove(k) }
            } else {
                let through = rng.below(4) as i64;
                let tick = if side == Side::Bid { mid + through } else { mid - through };
                oid += 1;
                Op::Order { oid, side, tick, lots: 1 + rng.below(40), tif: Tif::Ioc }
            };
            batch.push(Action { user, op, nonce_ms: 0, prio_gas: 0 });
        }
        apply_batch(&mut book, &batch, &cfg, &mut out);
        mid += rng.below(3) as i64 - 1;
        made += batch.len();
        batches.push(batch);
    }
    batches
}

fn replay(batches: &[Vec<Action>]) -> usize {
    let mut book = Book::with_capacity(1 << 16);
    let mut out = BatchOut::default();
    let cfg = EngineConfig::default();
    let mut fills = 0;
    for b in batches {
        apply_batch(&mut book, b, &cfg, &mut out);
        fills += out.matched.fills.len();
    }
    fills
}

fn bench(c: &mut Criterion) {
    let mut g = c.benchmark_group("match_mode");
    for n in [100_000usize, 1_000_000] {
        let batches = stream(n, 0x9E37_79B9_7F4A_7C15);
        let total: usize = batches.iter().map(Vec::len).sum();
        g.throughput(Throughput::Elements(total as u64));
        g.bench_with_input(BenchmarkId::new("synthetic_actions", total), &batches, |b, s| {
            b.iter(|| black_box(replay(black_box(s))))
        });
    }
    g.finish();
}

criterion_group!(benches, bench);
criterion_main!(benches);
