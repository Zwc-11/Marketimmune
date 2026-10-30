//! Apply one consensus batch in HyperCore's processing order (match mode).
//!
//! HyperCore sorts each consensus batch into three groups and keeps the
//! proposer's order inside each group:
//!
//! 1. actions that place no GTC or IOC order (post-only / ALO adds),
//! 2. cancels,
//! 3. actions that place at least one GTC or IOC order (takers).
//!
//! So a cancel always beats a taker in the same batch, whatever priority fee
//! the taker paid. A block holds one or two batches; when batch boundaries are
//! unknown, applying the rule per block is an approximation, and how often it
//! bites is something to measure, not assume.

use crate::book::{Book, BookError, MatchOut, Stp};
use crate::types::{Lots, Oid, Side, Tick, UserId};

/// Processing group inside a batch. The discriminant is the sort key.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Debug)]
pub enum Cls {
    PostOnly = 0,
    Cancel = 1,
    Taker = 2,
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Tif {
    /// Add liquidity only: rejected if it would cross.
    Alo,
    /// Good till cancelled: matches, then the remainder rests.
    Gtc,
    /// Immediate or cancel: matches, then the remainder is dropped.
    Ioc,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Op {
    Order { oid: Oid, side: Side, tick: Tick, lots: Lots, tif: Tif },
    Cancel { oid: Oid },
}

/// One signed action as it appears in a block.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Action {
    pub user: UserId,
    pub op: Op,
    /// Client nonce (milliseconds for SDK-style clients).
    pub nonce_ms: u64,
    /// Priority fee as written in `grouping.p` (rate * 1e8 of notional; 80_000 = 8 bps).
    pub prio_gas: u64,
}

impl Action {
    pub fn cls(&self) -> Cls {
        match self.op {
            Op::Order { tif: Tif::Alo, .. } => Cls::PostOnly,
            Op::Cancel { .. } => Cls::Cancel,
            Op::Order { tif: Tif::Gtc | Tif::Ioc, .. } => Cls::Taker,
        }
    }
}

/// What happened to one action. These line up with the order-status labels in
/// node output (`open`, `filled`, `iocCancelRejected`, `badAloPxRejected`,
/// `canceled`) so match mode can be checked against recorded outcomes.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Status {
    /// Order is resting; `filled` lots executed before it rested.
    Resting { filled: Lots },
    /// Order executed in full.
    Filled { filled: Lots },
    /// IOC remainder dropped after `filled` lots executed (0 = nothing matched).
    IocCanceled { filled: Lots },
    /// Post-only order would have crossed.
    AloRejected,
    /// Cancel removed a resting order of this size.
    Canceled { lots: Lots },
    /// Cancel found nothing to remove: the order already filled, was already
    /// cancelled, or never rested. A cancel that lost its race ends here.
    CancelMissing,
    /// Order id already resting.
    DuplicateOid,
    /// Order with zero size.
    ZeroSize,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct EngineConfig {
    pub stp: Stp,
}

/// Reusable output buffers for [`apply_batch`].
#[derive(Clone, Debug, Default)]
pub struct BatchOut {
    /// One status per input action, in input order.
    pub statuses: Vec<Status>,
    /// Fills and self-trade cancels in execution order.
    pub matched: MatchOut,
    order: Vec<u32>,
}

/// Apply `actions` (one consensus batch, in proposer order) to `book`.
pub fn apply_batch(book: &mut Book, actions: &[Action], cfg: &EngineConfig, out: &mut BatchOut) {
    out.statuses.clear();
    out.statuses.resize(actions.len(), Status::CancelMissing);
    out.matched.clear();
    out.order.clear();
    out.order.extend(0..actions.len() as u32);
    out.order.sort_by_key(|&i| actions[i as usize].cls()); // stable: keeps proposer order

    for &i in &out.order {
        let a = &actions[i as usize];
        out.statuses[i as usize] = match a.op {
            Op::Cancel { oid } => match book.cancel(oid) {
                Some(lots) => Status::Canceled { lots },
                None => Status::CancelMissing,
            },
            Op::Order { lots: 0, .. } => Status::ZeroSize,
            Op::Order { oid, .. } if book.order(oid).is_some() => Status::DuplicateOid,
            Op::Order { oid, side, tick, lots, tif: Tif::Alo } => {
                if book.crosses(side, tick) {
                    Status::AloRejected
                } else {
                    rest(book, oid, a.user, side, tick, lots, 0)
                }
            }
            Op::Order { oid, side, tick, lots, tif } => {
                let before = out.matched.fills.len();
                let left = book.take(oid, a.user, side, tick, lots, cfg.stp, &mut out.matched);
                debug_assert!(
                    out.matched.fills[before..].iter().map(|f| f.lots).sum::<Lots>() == lots - left
                );
                let filled = lots - left;
                match (left, tif) {
                    (0, _) => Status::Filled { filled },
                    (_, Tif::Gtc) => rest(book, oid, a.user, side, tick, left, filled),
                    _ => Status::IocCanceled { filled },
                }
            }
        };
    }
}

fn rest(book: &mut Book, oid: Oid, user: UserId, side: Side, tick: Tick, lots: Lots, filled: Lots) -> Status {
    match book.add(oid, user, side, tick, lots) {
        Ok(()) => Status::Resting { filled },
        Err(BookError::DuplicateOid(_)) => Status::DuplicateOid,
        Err(BookError::ZeroLots) => Status::ZeroSize,
        Err(e) => unreachable!("add cannot fail with {e}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn order(user: UserId, oid: Oid, side: Side, tick: Tick, lots: Lots, tif: Tif) -> Action {
        Action { user, op: Op::Order { oid, side, tick, lots, tif }, nonce_ms: 0, prio_gas: 0 }
    }

    fn cancel(user: UserId, oid: Oid) -> Action {
        Action { user, op: Op::Cancel { oid }, nonce_ms: 0, prio_gas: 0 }
    }

    /// Lesson 7, check-yourself 2: a cancel and a taker for the same resting
    /// order arrive in one batch. The cancel wins whatever the proposer order.
    #[test]
    fn cancel_beats_taker_in_same_batch() {
        for taker_first in [true, false] {
            let mut book = Book::new();
            book.add(1, 1, Side::Ask, 100, 5).unwrap();
            let snipe = Action { prio_gas: 80_000, ..order(2, 9, Side::Bid, 100, 5, Tif::Ioc) };
            let pull = cancel(1, 1);
            let batch = if taker_first { vec![snipe, pull] } else { vec![pull, snipe] };
            let mut out = BatchOut::default();
            apply_batch(&mut book, &batch, &EngineConfig::default(), &mut out);
            let (s_snipe, s_pull) = if taker_first {
                (out.statuses[0], out.statuses[1])
            } else {
                (out.statuses[1], out.statuses[0])
            };
            assert_eq!(s_pull, Status::Canceled { lots: 5 });
            assert_eq!(s_snipe, Status::IocCanceled { filled: 0 });
            assert!(out.matched.fills.is_empty());
            assert!(book.is_empty());
        }
    }

    /// Across batches the order of arrival decides: the snipe in the earlier
    /// batch fills and the later cancel finds nothing.
    #[test]
    fn snipe_in_earlier_batch_wins() {
        let mut book = Book::new();
        book.add(1, 1, Side::Ask, 100, 5).unwrap();
        let mut out = BatchOut::default();
        let cfg = EngineConfig::default();
        apply_batch(&mut book, &[order(2, 9, Side::Bid, 100, 5, Tif::Ioc)], &cfg, &mut out);
        assert_eq!(out.statuses, vec![Status::Filled { filled: 5 }]);
        apply_batch(&mut book, &[cancel(1, 1)], &cfg, &mut out);
        assert_eq!(out.statuses, vec![Status::CancelMissing]);
    }

    /// A post-only quote placed in the same batch as a taker rests first and
    /// can be hit by it, even if the taker came first in proposer order.
    #[test]
    fn post_only_runs_before_takers() {
        let mut book = Book::new();
        let batch = [order(2, 9, Side::Bid, 100, 3, Tif::Ioc), order(1, 1, Side::Ask, 100, 5, Tif::Alo)];
        let mut out = BatchOut::default();
        apply_batch(&mut book, &batch, &EngineConfig::default(), &mut out);
        assert_eq!(out.statuses, vec![Status::Filled { filled: 3 }, Status::Resting { filled: 0 }]);
        assert_eq!(book.best_ask(), Some((100, 2)));
    }

    #[test]
    fn alo_that_crosses_is_rejected() {
        let mut book = Book::new();
        book.add(1, 1, Side::Ask, 100, 5).unwrap();
        let mut out = BatchOut::default();
        apply_batch(
            &mut book,
            &[order(2, 2, Side::Bid, 100, 1, Tif::Alo)],
            &EngineConfig::default(),
            &mut out,
        );
        assert_eq!(out.statuses, vec![Status::AloRejected]);
        assert_eq!(book.len(), 1);
    }

    #[test]
    fn gtc_remainder_rests_ioc_remainder_drops() {
        let mut book = Book::new();
        book.add(1, 1, Side::Ask, 100, 2).unwrap();
        book.add(2, 1, Side::Ask, 101, 2).unwrap();
        let mut out = BatchOut::default();
        let cfg = EngineConfig::default();
        apply_batch(&mut book, &[order(2, 9, Side::Bid, 100, 5, Tif::Gtc)], &cfg, &mut out);
        assert_eq!(out.statuses, vec![Status::Resting { filled: 2 }]);
        assert_eq!(book.best_bid(), Some((100, 3)));
        apply_batch(&mut book, &[order(3, 10, Side::Ask, 99, 9, Tif::Ioc)], &cfg, &mut out);
        assert_eq!(out.statuses, vec![Status::IocCanceled { filled: 3 }]);
        assert_eq!(book.best_bid(), None);
    }

    #[test]
    fn stable_within_class() {
        let mut book = Book::new();
        let batch = [
            order(1, 1, Side::Ask, 100, 1, Tif::Alo),
            order(2, 2, Side::Ask, 100, 1, Tif::Alo),
            order(3, 3, Side::Ask, 100, 1, Tif::Alo),
        ];
        let mut out = BatchOut::default();
        apply_batch(&mut book, &batch, &EngineConfig::default(), &mut out);
        let oids: Vec<_> = book.level_orders(Side::Ask, 100).iter().map(|o| o.oid).collect();
        assert_eq!(oids, vec![1, 2, 3]);
    }
}
