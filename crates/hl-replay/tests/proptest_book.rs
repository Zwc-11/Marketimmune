//! Property tests: the slab book and batch engine against a naive reference.
//!
//! Random streams of post-only, GTC and IOC orders and cancels (including
//! cancels of filled orders and duplicate order ids) are applied batch by batch
//! to both implementations. After every batch they must agree on every status,
//! every fill and the full order-by-order book, and the slab book must pass its
//! structural checks: uncrossed, cached level totals equal to the sum of their
//! orders, and each successful cancel removing exactly the order it named.

use hl_replay::{
    Action, BatchOut, Book, EngineConfig, Fill, Lots, Oid, Op, Side, Status, Stp, Tick, Tif, UserId,
    apply_batch,
};
use proptest::prelude::*;
use proptest::test_runner::FileFailurePersistence;

#[derive(Clone, Debug)]
struct RefOrder {
    oid: Oid,
    user: UserId,
    side: Side,
    tick: Tick,
    lots: Lots,
    seq: u64,
}

#[derive(Default)]
struct RefBook {
    orders: Vec<RefOrder>,
    seq: u64,
}

impl RefBook {
    fn has(&self, oid: Oid) -> bool {
        self.orders.iter().any(|o| o.oid == oid)
    }

    fn crosses(&self, side: Side, tick: Tick) -> bool {
        self.orders.iter().any(|o| match side {
            Side::Bid => o.side == Side::Ask && o.tick <= tick,
            Side::Ask => o.side == Side::Bid && o.tick >= tick,
        })
    }

    fn add(&mut self, oid: Oid, user: UserId, side: Side, tick: Tick, lots: Lots) {
        self.seq += 1;
        self.orders.push(RefOrder { oid, user, side, tick, lots, seq: self.seq });
    }

    fn cancel(&mut self, oid: Oid) -> Option<Lots> {
        let i = self.orders.iter().position(|o| o.oid == oid)?;
        Some(self.orders.remove(i).lots)
    }

    #[allow(clippy::too_many_arguments)]
    fn take(
        &mut self,
        taker_oid: Oid,
        taker: UserId,
        side: Side,
        limit: Tick,
        mut lots: Lots,
        stp: Stp,
        fills: &mut Vec<Fill>,
        expired: &mut Vec<Oid>,
    ) -> Lots {
        while lots > 0 {
            let best = self
                .orders
                .iter()
                .enumerate()
                .filter(|(_, o)| match side {
                    Side::Bid => o.side == Side::Ask && o.tick <= limit,
                    Side::Ask => o.side == Side::Bid && o.tick >= limit,
                })
                .min_by_key(|(_, o)| (if side == Side::Bid { o.tick } else { -o.tick }, o.seq))
                .map(|(i, _)| i);
            let Some(i) = best else { break };
            if stp == Stp::ExpireMaker && self.orders[i].user == taker {
                expired.push(self.orders.remove(i).oid);
                continue;
            }
            let o = &mut self.orders[i];
            let q = o.lots.min(lots);
            fills.push(Fill {
                maker_oid: o.oid,
                maker: o.user,
                taker_oid,
                taker,
                taker_side: side,
                tick: o.tick,
                lots: q,
            });
            o.lots -= q;
            lots -= q;
            if o.lots == 0 {
                self.orders.remove(i);
            }
        }
        lots
    }

    fn snapshot(&self) -> hl_replay::book::Snapshot {
        let side = |s: Side| {
            let mut os: Vec<&RefOrder> = self.orders.iter().filter(|o| o.side == s).collect();
            os.sort_by_key(|o| (if s == Side::Bid { -o.tick } else { o.tick }, o.seq));
            let mut out: Vec<(Tick, Vec<(Oid, Lots)>)> = Vec::new();
            for o in os {
                match out.last_mut() {
                    Some((t, v)) if *t == o.tick => v.push((o.oid, o.lots)),
                    _ => out.push((o.tick, vec![(o.oid, o.lots)])),
                }
            }
            out
        };
        (side(Side::Bid), side(Side::Ask))
    }

    fn apply_batch(&mut self, actions: &[Action], stp: Stp) -> (Vec<Status>, Vec<Fill>, Vec<Oid>) {
        let mut idx: Vec<usize> = (0..actions.len()).collect();
        idx.sort_by_key(|&i| actions[i].cls());
        let mut statuses = vec![Status::CancelMissing; actions.len()];
        let (mut fills, mut expired) = (Vec::new(), Vec::new());
        for i in idx {
            let a = actions[i];
            statuses[i] = match a.op {
                Op::Cancel { oid } => {
                    self.cancel(oid).map_or(Status::CancelMissing, |lots| Status::Canceled { lots })
                }
                Op::Order { lots: 0, .. } => Status::ZeroSize,
                Op::Order { oid, .. } if self.has(oid) => Status::DuplicateOid,
                Op::Order { oid, side, tick, lots, tif: Tif::Alo } => {
                    if self.crosses(side, tick) {
                        Status::AloRejected
                    } else {
                        self.add(oid, a.user, side, tick, lots);
                        Status::Resting { filled: 0 }
                    }
                }
                Op::Order { oid, side, tick, lots, tif } => {
                    let left = self.take(oid, a.user, side, tick, lots, stp, &mut fills, &mut expired);
                    let filled = lots - left;
                    match (left, tif) {
                        (0, _) => Status::Filled { filled },
                        (_, Tif::Gtc) => {
                            self.add(oid, a.user, side, tick, left);
                            Status::Resting { filled }
                        }
                        _ => Status::IocCanceled { filled },
                    }
                }
            };
        }
        (statuses, fills, expired)
    }
}

#[derive(Clone, Debug)]
enum Spec {
    Order { user: UserId, side: Side, tick: Tick, lots: Lots, tif: Tif, reuse: Option<usize> },
    Cancel { pick: usize },
}

fn spec() -> impl Strategy<Value = Spec> {
    let side = prop_oneof![Just(Side::Bid), Just(Side::Ask)];
    let tif = prop_oneof![3 => Just(Tif::Alo), 1 => Just(Tif::Gtc), 2 => Just(Tif::Ioc)];
    let order = (0u32..4, side, 95i64..=105, 0u64..=8, tif, prop::option::weighted(0.05, any::<usize>()))
        .prop_map(|(user, side, tick, lots, tif, reuse)| Spec::Order { user, side, tick, lots, tif, reuse });
    prop_oneof![3 => order, 2 => any::<usize>().prop_map(|pick| Spec::Cancel { pick })]
}

fn stream() -> impl Strategy<Value = Vec<Vec<Spec>>> {
    prop::collection::vec(prop::collection::vec(spec(), 1..20), 1..30)
}

fn run(batches: Vec<Vec<Spec>>, stp: Stp) -> Result<(), TestCaseError> {
    let mut book = Book::new();
    let mut reference = RefBook::default();
    let mut out = BatchOut::default();
    let cfg = EngineConfig { stp };
    let mut issued: Vec<Oid> = Vec::new();
    let mut next_oid: Oid = 1;
    for specs in batches {
        let actions: Vec<Action> = specs
            .into_iter()
            .map(|s| {
                let (user, op) = match s {
                    Spec::Order { user, side, tick, lots, tif, reuse } => {
                        let oid = match reuse {
                            Some(k) if !issued.is_empty() => issued[k % issued.len()],
                            _ => {
                                next_oid += 1;
                                issued.push(next_oid);
                                next_oid
                            }
                        };
                        (user, Op::Order { oid, side, tick, lots, tif })
                    }
                    Spec::Cancel { pick } => {
                        let oid = if issued.is_empty() { 0 } else { issued[pick % issued.len()] };
                        (0, Op::Cancel { oid })
                    }
                };
                Action { user, op, nonce_ms: 0, prio_gas: 0 }
            })
            .collect();

        // Orders a cancel in this batch may remove: those resting before the
        // batch, plus post-only orders placed in it (group 1 runs before cancels).
        // GTC/IOC orders placed in the batch run after the cancels and are not
        // removable by them.
        let mut cancellable: Vec<Oid> = actions
            .iter()
            .filter_map(|a| match a.op {
                Op::Cancel { oid } if book.order(oid).is_some() => Some(oid),
                _ => None,
            })
            .collect();
        let resting_before = cancellable.clone();
        cancellable.extend(actions.iter().filter_map(|a| match a.op {
            Op::Order { oid, tif: Tif::Alo, .. } => Some(oid),
            _ => None,
        }));

        apply_batch(&mut book, &actions, &cfg, &mut out);
        let (statuses, fills, expired) = reference.apply_batch(&actions, stp);

        prop_assert_eq!(&out.statuses, &statuses);
        prop_assert_eq!(&out.matched.fills, &fills);
        prop_assert_eq!(&out.matched.stp_canceled, &expired);
        prop_assert_eq!(book.snapshot(), reference.snapshot());
        prop_assert!(book.check_invariants().is_ok(), "{:?}", book.check_invariants());
        prop_assert!(!book.is_crossed(), "book crossed after a batch");

        let gtc_in_batch: Vec<Oid> = actions
            .iter()
            .filter_map(|a| match a.op {
                Op::Order { oid, tif: Tif::Gtc, .. } if !resting_before.contains(&oid) => Some(oid),
                _ => None,
            })
            .collect();
        let mut removed: Vec<Oid> = Vec::new();
        for (a, s) in actions.iter().zip(&out.statuses) {
            let Op::Cancel { oid } = a.op else { continue };
            if let Status::Canceled { .. } = s {
                prop_assert!(cancellable.contains(&oid), "cancel {} removed an order it cannot reach", oid);
                let reused = actions.iter().any(|b| matches!(b.op, Op::Order { oid: o, .. } if o == oid));
                prop_assert!(
                    reused || book.order(oid).is_none(),
                    "cancel {} left its order on the book",
                    oid
                );
                prop_assert!(!removed.contains(&oid), "order {} removed twice", oid);
                removed.push(oid);
            } else if gtc_in_batch.contains(&oid) && !resting_before.contains(&oid) {
                prop_assert_eq!(*s, Status::CancelMissing, "cancel reached a GTC placed later in its batch");
            }
        }
    }
    Ok(())
}

proptest! {
    #![proptest_config(ProptestConfig {
        cases: 1024,
        failure_persistence: Some(Box::new(FileFailurePersistence::Direct("tests/proptest-regressions.txt"))),
        ..ProptestConfig::default()
    })]

    #[test]
    fn engine_matches_reference(batches in stream()) {
        run(batches, Stp::Off)?;
    }

    #[test]
    fn engine_matches_reference_with_stp(batches in stream()) {
        run(batches, Stp::ExpireMaker)?;
    }
}
